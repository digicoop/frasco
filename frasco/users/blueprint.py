from flask import Blueprint, request, redirect, current_app, flash, session, render_template, abort, make_response
from flask_login import logout_user
from frasco.helpers import url_for
from frasco.ext import get_extension_state, has_extension
from frasco.utils import populate_obj, AttrDict
from frasco.models import db, transaction
from frasco.mail import send_mail
from frasco.geoip import geolocate_country
import datetime
import requests
import logging

from .forms import *
from .auth import authenticate
from .auth.oauth import clear_oauth_signup_session
from .signals import user_signed_up
from .user import is_user_logged_in, login_user, signup_user, UserValidationFailedError, check_rate_limit
from .password import generate_reset_password_token, update_password, validate_password, send_reset_password_token, PasswordValidationFailedError
from .tokens import read_user_token, generate_user_token
from .otp import verify_2fa


users_blueprint = Blueprint("users", __name__, template_folder="templates")
logger = logging.getLogger('frasco.users')


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
    redirect_url = request.args.get("next") or _make_redirect_url(state.options["redirect_after_login"])

    if is_user_logged_in():
        return redirect(redirect_url)

    if not is_oauth and not request.args.get("no_redirect"):
        if state.options['login_redirect']:
            return redirect(state.options['login_redirect'])
        if state.manager.login_view != "users.login":
            return redirect(url_for(state.manager.login_view))

    if not state.options['allow_login']:
        if state.options["login_disallowed_message"]:
            flash(state.options["login_disallowed_message"], "error")
        return redirect(url_for(state.options.get("redirect_after_login_disallowed") or\
            "users.login", next=request.args.get("next")))

    form = state.import_option('login_form_class')()
    if form.validate_on_submit():
        user = authenticate(form.identifier.data, form.password.data)
        if user:
            if (state.options['expire_password_after'] and user.last_password_change_at and \
            (datetime.datetime.utcnow() - user.last_password_change_at).total_seconds() > state.options['expire_password_after']) \
            or user.must_reset_password_at_login:
                token = generate_reset_password_token(user)
                flash(state.options['password_expired_message'], 'error')
                return redirect(url_for('.reset_password', token=token))

            if state.options['enable_2fa'] and user.two_factor_auth_enabled:
                session['2fa'] = user.id
                session['login_remember'] = form.remember.data
                return redirect(url_for('.login_2fa'))

            with transaction():
                if is_oauth:
                    user.save_oauth_token_data(session['oauth_signup'], session['oauth_data'])
                login_user(user, remember=form.remember.data, provider=session.get('oauth_signup'))
                clear_oauth_signup_session()
            return redirect(redirect_url)

        flash(state.options['login_error_message'], 'error')

    return render_template('users/login.html', form=form, is_oauth=is_oauth)


@users_blueprint.route('/login/2fa', methods=['GET', 'POST'])
def login_2fa():
    state = get_extension_state('frasco_users')
    if not state.options['enable_2fa'] or not session.get('2fa'):
        return redirect(url_for('.login'))

    is_oauth = "oauth_signup" in session
    redirect_url = request.args.get("next") or _make_redirect_url(state.options["redirect_after_login"])

    if is_user_logged_in():
        return redirect(redirect_url)

    remember_2fa_max_age = state.options['2fa_remember_days']*3600*24

    if request.cookies.get('remember_2fa'):
        remember_user = read_user_token(request.cookies['remember_2fa'], '2fa', remember_2fa_max_age)
        user = state.Model.query.get(session.pop('2fa'))
        if remember_user == user:
            with transaction():
                login_user(user, remember=session.pop('login_remember'))
            return redirect(redirect_url)

    form = state.import_option('login_2fa_form_class')()
    if form.validate_on_submit():
        user = state.Model.query.get(session.pop('2fa'))
        remember = session.pop('login_remember')
        if verify_2fa(user, form.code.data):
            with transaction():
                if is_oauth:
                    user.save_oauth_token_data(session['oauth_signup'], session['oauth_data'])
                login_user(user, remember=remember, provider=session.get('oauth_signup'))
                clear_oauth_signup_session()
            r = make_response(redirect(redirect_url))
            if form.remember.data:
                r.set_cookie('remember_2fa', generate_user_token(user, '2fa'),
                    max_age=remember_2fa_max_age, **state.options['2fa_remember_cookie_options'])
            return r
        flash(state.options['login_2fa_error_message'], 'error')
        return redirect(url_for('.login'))

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

    redirect_url = request.args.get("next") or _make_redirect_url(state.options["redirect_after_signup"])
    if is_user_logged_in():
        return redirect(redirect_url)

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

            if state.options['recaptcha_secret'] and not current_app.debug and not current_app.testing:
                is_captcha_success = False
                if 'g-recaptcha-response' in request.form:
                    try:
                        r = requests.post('https://www.google.com/recaptcha/api/siteverify', data={
                            'secret': state.options['recaptcha_secret'],
                            'response': request.form['g-recaptcha-response'],
                            'remote_ip': request.remote_addr
                        })
                        is_captcha_success = r.ok and r.json().get('success')
                    except:
                        logger.exception("Error while checking recaptcha")
                        is_captcha_success = False
                if not is_captcha_success:
                    if state.options['recaptcha_fail_message']:
                        flash(state.options['recaptcha_fail_message'], 'error')
                    raise UserValidationFailedError()

            with transaction():
                user = state.Model()
                populate_obj(user, session.get("oauth_user_defaults", {}))
                signup_user(user, provider=session.get('oauth_signup'), send_signal=False, **form.data)

                if is_oauth:
                    user.save_oauth_token_data(session['oauth_signup'], session['oauth_data'])
                clear_oauth_signup_session()
                db.session.flush()
                user_signed_up.send(user=user)
                if state.options["login_user_on_signup"]:
                    login_user(user, provider=user.signup_provider)

            return redirect(redirect_url)
        except (UserValidationFailedError, PasswordValidationFailedError):
            db.session.rollback()

    return render_template('users/signup.html',
        form=form, must_provide_password=must_provide_password, is_oauth=is_oauth)


@users_blueprint.route('/signup/oauth')
def oauth_signup():
    state = get_extension_state('frasco_users')
    if "oauth_signup" not in session or state.options["oauth_must_signup"]:
        oauth = 1 if state.options["oauth_must_signup"] else 0
        return redirect(url_for(".signup", oauth=oauth, next=request.args.get("next")))

    try:
        with transaction():
            user = state.Model()
            populate_obj(user, session.get("oauth_user_defaults", {}))
            signup_user(user, flash_messages=False, send_signal=False)
            user.save_oauth_token_data(session['oauth_signup'], session['oauth_data'])
            db.session.flush()
            user_signed_up.send(user=user)
            login_user(user, provider=session['oauth_signup'])
    except UserValidationFailedError:
        return redirect(url_for(".signup", oauth=1, next=request.args.get("next")))

    clear_oauth_signup_session()
    return redirect(request.args.get("next") or _make_redirect_url(state.options["redirect_after_login"]))


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

    user = read_user_token(token, salt='password-reset')
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


def _make_redirect_url(value):
    if value.startswith('http://') or value.startswith('https://'):
        return value
    return url_for(value)
