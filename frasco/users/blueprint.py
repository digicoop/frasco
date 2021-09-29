from flask import Blueprint, request, redirect, current_app, flash, session, render_template, abort, make_response, jsonify, get_flashed_messages
from flask_login import logout_user, current_user
from frasco.helpers import url_for
from frasco.ext import get_extension_state, has_extension
from frasco.utils import populate_obj, AttrDict
from frasco.models import db, transaction
from frasco.mail import send_mail
from frasco.geoip import geolocate_country
import datetime
import requests
import logging
import re

from .forms import *
from .auth import authenticate
from .auth.oauth import clear_oauth_signup_session
from .signals import user_signed_up, email_validated
from .user import is_user_logged_in, login_user, signup_user, UserValidationFailedError, check_rate_limit, send_user_validation_email, validate_user_email, send_user_welcome_email
from .password import generate_reset_password_token, update_password, validate_password, send_reset_password_token, PasswordValidationFailedError
from .tokens import read_user_token, generate_user_token, TOKEN_NS_ACCESS_TOKEN, TOKEN_NS_2FA, TOKEN_NS_PASSWORD_RESET, TOKEN_NS_VALIDATE_EMAIL
from .otp import verify_2fa


users_blueprint = Blueprint("users", __name__, template_folder="templates")
logger = logging.getLogger('frasco.users')


LOGIN_FLOW_ACCESS_TOKEN = 'access_token'
LOGIN_FLOW_WEB_ACCESS_TOKEN = 'web_access_token'


def _is_login_flow(flow):
    return request.args.get('flow') == flow


def _is_programmatic_login():
    return request.is_json or _is_login_flow(LOGIN_FLOW_ACCESS_TOKEN)


def _login_redirect(url, **kwargs):
    if request.method == 'POST' and _is_programmatic_login():
        kwargs.setdefault('errors', get_flashed_messages())
        return jsonify(success=False, next=url, **kwargs)
    return redirect(url)


def _do_login(user, remember=None):
    with transaction():
        if "oauth_signup" in session:
            user.save_oauth_token_data(session['oauth_signup'], session['oauth_data'])
        login_user(user, remember=remember, provider=session.get('oauth_signup'), skip_session=_is_programmatic_login() or _is_login_flow(LOGIN_FLOW_WEB_ACCESS_TOKEN))
        clear_oauth_signup_session()


def _login_success(opt_redirect='redirect_after_login', allow_programmatic=True):
    state = get_extension_state('frasco_users')
    redirect_url = request.args.get("next") or _make_redirect_url(state.options[opt_redirect])
    if _is_login_flow(LOGIN_FLOW_WEB_ACCESS_TOKEN) and request.args.get("next") and state.options['enable_access_tokens'] and state.options['enable_access_tokens_web_flow']:
        for allowed_url_pattern in state.options['access_tokens_web_flow_allowed_redirects']:
            if re.match(allowed_url_pattern, redirect_url, re.I):
                redirect_url += '#access_token=%s' % generate_user_token(current_user, TOKEN_NS_ACCESS_TOKEN)
                break
    if allow_programmatic and _is_programmatic_login():
        return jsonify(success=True)
    return redirect(redirect_url)


@users_blueprint.route('/login', methods=['GET', 'POST'])
def login():
    state = get_extension_state('frasco_users')

    if request.method == "GET" and not "oauth" in request.args:
        # signup was accessed directly so we ensure that oauth
        # params stored in session are cleaned. this can happen
        # if a user started to login using an oauth provider but
        # didn't complete the process
        clear_oauth_signup_session()

    is_oauth = "oauth_signup" in session

    if is_user_logged_in():
        return _login_success()

    if not is_oauth and not request.args.get("no_redirect"):
        if state.options['login_redirect']:
            return _login_redirect(state.options['login_redirect'])
        if state.manager.login_view != "users.login":
            return _login_redirect(url_for(state.manager.login_view, next=request.args.get("next")))

    form = state.import_option('login_form_class')(meta={'csrf': current_app.config.get('WTF_CSRF_ENABLED', True) and not _is_programmatic_login()})

    if not state.options['allow_login']:
        if state.options["login_disallowed_message"]:
            flash(state.options["login_disallowed_message"], "error")
        if request.method == 'POST' and _is_programmatic_login():
            return jsonify(success=False, errors=get_flashed_messages())
        if state.options.get("redirect_after_login_disallowed"):
            return _login_redirect(_make_redirect_url(state.options.get("redirect_after_login_disallowed")))
    elif request.method == 'POST':
        user = None
        try:
            if request.is_json:
                payload = request.get_json()
                user = authenticate(payload.get('identifier'), payload.get('password'))
            elif form.validate():
                user = authenticate(form.identifier.data, form.password.data)
        except Exception as e:
            current_app.log_exception(e)

        if user:
            if (state.options['expire_password_after'] and user.last_password_change_at and \
              (datetime.datetime.utcnow() - user.last_password_change_at).total_seconds() > state.options['expire_password_after']) \
              or user.must_reset_password_at_login:
                token = generate_reset_password_token(user)
                flash(state.options['password_expired_message'], 'error')
                return _login_redirect(url_for('.reset_password', token=token))

            if state.options['enable_2fa'] and user.two_factor_auth_enabled:
                if _is_programmatic_login():
                    return jsonify(success=False, require_2fa=True)
                session['2fa'] = user.id
                session['login_remember'] = form.remember.data
                return redirect(url_for('.login_2fa', flow=request.args.get('flow'), next=request.args.get('next')))

            if state.options['block_non_email_validated_users'] and user.must_validate_email:
                clear_oauth_signup_session()
                return render_template("users/non_email_validated_users_block_page.html", email=user.email)

            _do_login(user, form.remember.data)

            if state.options['enable_access_tokens'] and _is_programmatic_login():
                return jsonify(success=True, access_token=generate_user_token(user, TOKEN_NS_ACCESS_TOKEN))
            
            return _login_success()

        flash(state.options['login_error_message'], 'error')

        if _is_programmatic_login():
            return jsonify(success=False, errors=get_flashed_messages())

    return render_template('users/login.html', form=form, is_oauth=is_oauth)


@users_blueprint.route('/login/2fa', methods=['GET', 'POST'])
def login_2fa():
    state = get_extension_state('frasco_users')
    if not state.options['enable_2fa'] or not session.get('2fa'):
        return redirect(url_for('.login', flow=request.args.get('flow'), next=request.args.get('next')))

    is_oauth = "oauth_signup" in session
    remember_2fa_max_age = state.options['2fa_remember_days']*3600*24

    if request.cookies.get('remember_2fa'):
        remember_user = read_user_token(request.cookies['remember_2fa'], TOKEN_NS_2FA, remember_2fa_max_age)
        user = state.Model.query.get(session.pop('2fa'))
        if remember_user == user:
            _do_login(user, session.pop('login_remember'))
            return _login_success()

    form = state.import_option('login_2fa_form_class')()
    if form.validate_on_submit():
        user = state.Model.query.get(session.pop('2fa'))
        remember = session.pop('login_remember')
        if verify_2fa(user, form.code.data):
            _do_login(user, remember)
            r = make_response(_login_success())
            if form.remember.data:
                r.set_cookie('remember_2fa', generate_user_token(user, TOKEN_NS_2FA),
                    max_age=remember_2fa_max_age, **state.options['2fa_remember_cookie_options'])
            return r
        flash(state.options['login_2fa_error_message'], 'error')
        return redirect(url_for('.login', flow=request.args.get('flow'), next=request.args.get('next')))

    return render_template('users/login_2fa.html', form=form, is_oauth=is_oauth)


@users_blueprint.route('/logout')
def logout():
    state = get_extension_state('frasco_users')
    redirect_url = request.args.get("next") or _make_redirect_url(state.options["redirect_after_logout"])
    logout_user()
    return redirect(redirect_url)


@users_blueprint.route('/signup', methods=['GET', 'POST'])
def signup():
    state = get_extension_state('frasco_users')
    if request.method == "GET" and not "oauth" in request.args:
        # signup was accessed directly so we ensure that oauth
        # params stored in session are cleaned. this can happen
        # if a user started to login using an oauth provider but
        # didn't complete the process
        clear_oauth_signup_session()

    if is_user_logged_in():
        return _login_success('redirect_after_signup', False)

    if state.options['signup_redirect']:
        return redirect(state.options['signup_redirect'])
        
    is_oauth = "oauth_signup" in session
    allow_signup = state.options["allow_signup"]
    if state.options["oauth_signup_only"] and not is_oauth:
        allow_signup = False

    if not allow_signup:
        if state.options["signup_disallowed_message"]:
            flash(state.options["signup_disallowed_message"], "error")
        return redirect(url_for(state.options.get("redirect_after_signup_disallowed") or\
            "users.login", next=request.args.get("next")))

    form = state.import_option('signup_form_class')(obj=AttrDict(session.get('oauth_user_defaults', {})))
    must_provide_password = not is_oauth or state.options["oauth_must_provide_password"]

    if form.validate_on_submit():
        try:
            if must_provide_password and not form.password.data:
                raise PasswordValidationFailedError()

            if not check_rate_limit(request.remote_addr, 'signup_from', 'signup_at'):
                raise UserValidationFailedError()

            if state.captcha_validator and (not current_app.debug and not current_app.testing or state.options['debug_captcha']):
                is_captcha_success = False
                try:
                    is_captcha_success = state.captcha_validator()
                except:
                    logger.exception("Error while checking recaptcha")
                if not is_captcha_success:
                    if state.options['captcha_fail_message']:
                        flash(state.options['captcha_fail_message'], 'error')
                    raise UserValidationFailedError()

            with transaction():
                user = state.Model()
                populate_obj(user, session.get("oauth_user_defaults", {}))
                signup_user(user, provider=session.get('oauth_signup'), send_signal=False, **form.data)
                if is_oauth:
                    _save_oauth(user)
                db.session.flush()
                user_signed_up.send(user=user)
                if state.options['block_non_email_validated_users'] and not user.email_validated:
                    clear_oauth_signup_session()
                    return render_template("users/non_email_validated_users_block_page.html", email=user.email)
                if state.options["login_user_on_signup"]:
                    login_user(user, provider=user.signup_provider, skip_session=_is_programmatic_login() or _is_login_flow(LOGIN_FLOW_WEB_ACCESS_TOKEN))

            clear_oauth_signup_session()
            return _login_success('redirect_after_signup', False)
        except (UserValidationFailedError, PasswordValidationFailedError):
            db.session.rollback()

    return render_template('users/signup.html',
        form=form, must_provide_password=must_provide_password, is_oauth=is_oauth)


@users_blueprint.route('/signup/oauth')
def oauth_signup():
    state = get_extension_state('frasco_users')
    if "oauth_signup" not in session or state.options["oauth_must_signup"]:
        oauth = 1 if state.options["oauth_must_signup"] else 0
        return redirect(url_for(".signup", oauth=oauth, flow=request.args.get('flow'), next=request.args.get("next")))

    try:
        with transaction():
            user = state.Model()
            populate_obj(user, session.get("oauth_user_defaults", {}))
            signup_user(user, flash_messages=False, send_signal=False)
            _save_oauth(user)
            db.session.flush()
            user_signed_up.send(user=user)
            login_user(user, provider=session['oauth_signup'])
    except UserValidationFailedError:
        return redirect(url_for(".signup", oauth=1, flow=request.args.get('flow'), next=request.args.get("next")))

    clear_oauth_signup_session()
    return _login_success()


def _save_oauth(user):
    user.save_oauth_token_data(session['oauth_signup'], session['oauth_data'])
    if session.get("oauth_validate_email") and user.email == session.get("oauth_user_defaults", {}).get('email') and hasattr(user, 'email_validated'):
        validate_user_email(user)


@users_blueprint.route('/login/reset-password', methods=['GET', 'POST'])
def send_reset_password():
    state = get_extension_state('frasco_users')

    if state.options['reset_password_redirect']:
        return redirect(state.options['reset_password_redirect'])

    if not state.options['allow_reset_password']:
        if state.options["reset_password_disallowed_message"]:
            flash(state.options["reset_password_disallowed_message"], "error")
        return redirect(url_for(state.options.get("redirect_after_reset_password_disallowed") or\
            "users.login", next=request.args.get("next")))

    success_msg = state.options["reset_password_token_success_message"]
    error_msg = state.options["reset_password_token_error_message"]
    redirect_to = state.options["redirect_after_reset_password_token"]

    form = state.import_option('send_reset_password_form_class')()
    if form.validate_on_submit():
        user = state.Model.query_by_email(form.email.data).first()
        if user:
            send_reset_password_token(user)
            if success_msg:
                flash(success_msg, "success")
            if redirect_to:
                return redirect(_make_redirect_url(redirect_to))
        elif error_msg:
            flash(error_msg, 'error')

    return render_template("users/send_reset_password.html", form=form)


@users_blueprint.route('/login/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    state = get_extension_state('frasco_users')

    if not state.options['allow_reset_password']:
        if state.options["reset_password_disallowed_message"]:
            flash(state.options["reset_password_disallowed_message"], "error")
        return redirect(url_for(state.options.get("redirect_after_reset_password_disallowed") or\
            "users.login", next=request.args.get("next")))

    msg = state.options["reset_password_success_message"]
    redirect_to = state.options["redirect_after_reset_password"]

    user = read_user_token(token, TOKEN_NS_PASSWORD_RESET, state.options['reset_password_ttl'])
    if not user:
        abort(404)

    form = state.import_option('reset_password_form_class')()
    if form.validate_on_submit() and validate_password(user, form.password.data, raise_error=False):
        with transaction():
            update_password(user, form.password.data, skip_validation=True)
            if state.options['login_user_on_reset_password']:
                login_user(user)
            send_mail(user.email, "users/reset_password_done", locale=getattr(user, 'locale', None))
            if msg:
                flash(msg, "success")
            if redirect_to:
                return redirect(_make_redirect_url(redirect_to))

    return render_template("users/reset_password.html", form=form)


@users_blueprint.route('/validate-email/send', methods=['POST'])
def send_email_validation_email():
    state = get_extension_state('frasco_users')
    user = state.Model.query.filter_by(email=request.form['email'].lower()).first_or_404()
    if user.email_validated:
        abort(403)

    send_user_validation_email(user)

    if request.values.get('next'):
        return redirect(request.values['next'])

    return render_template("users/non_email_validated_users_block_page.html", email=user.email)


@users_blueprint.route('/validate-email/<token>', methods=['GET'])
def validate_email(token):
    state = get_extension_state('frasco_users')
    msg = state.options["email_validation_success_message"]
    redirect_to = state.options["redirect_after_email_validated"]

    user = read_user_token(token, TOKEN_NS_VALIDATE_EMAIL, state.options['email_validation_ttl'])
    if not user:
        abort(404)

    send_welcome_email = state.options['block_non_email_validated_users'] and user.must_validate_email

    with transaction():
        validate_user_email(user)

    if send_welcome_email:
        send_user_welcome_email(user)

    if not current_user.is_authenticated and state.options["login_after_email_validation"]:
        login_user(user)

    if msg:
        flash(msg, "success")
    return redirect(_make_redirect_url(redirect_to))


def _make_redirect_url(value):
    if value.startswith('http://') or value.startswith('https://'):
        return value
    return url_for(value)
