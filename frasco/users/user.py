from flask import has_request_context, _request_ctx_stack, flash, request, current_app
import flask_login
from flask_login.utils import _get_user
from frasco.ext import get_extension_state, has_extension
from frasco.ctx import ContextStack
from frasco.utils import match_email_domain, populate_obj
from frasco.models import db
from frasco.geoip import geolocate_country
from contextlib import contextmanager
from werkzeug.local import LocalProxy
import datetime
from .signals import user_signed_up
from .password import update_password
import logging


# this allows to set a current user without a request context
_no_req_ctx_user_stack = ContextStack()
logger = logging.getLogger('frasco.users')


@contextmanager
def user_login_context(user):
    stack = _no_req_ctx_user_stack
    if has_request_context():
        if not hasattr(_request_ctx_stack.top, 'user_stack'):
            _request_ctx_stack.top.user_stack = ContextStack()
        stack = _request_ctx_stack.top.user_stack
    stack.push(user)
    try:
        yield user
    finally:
        stack.pop()


def get_current_user(user=None):
    if user:
        return user
    if user is False:
        return None
    if not has_request_context():
        return _no_req_ctx_user_stack.top
    user_stack = getattr(_request_ctx_stack.top, 'user_stack', None)
    if user_stack and user_stack.top:
        return user_stack.top
    return _get_user()


def get_current_user_if_logged_in(user=None):
    user = get_current_user(user)
    if not user or not user.is_authenticated:
        return
    return user
    

current_user = LocalProxy(get_current_user)


def is_user_logged_in():
    """Checks if the user is logged in
    """
    return current_user and current_user.is_authenticated


def login_user(user, *args, **kwargs):
    state = get_extension_state('frasco_users')
    provider = kwargs.pop('provider', state.options['default_auth_provider_name'])

    for validator in state.login_validators:
        if not validator(user):
            return False

    if not flask_login.login_user(user, *args, **kwargs):
        return False

    user.last_login_at = datetime.datetime.utcnow()
    user.last_login_from = request.remote_addr
    user.last_login_provider = provider
    if not user.auth_providers:
        user.auth_providers = []
    if provider not in user.auth_providers:
        user.auth_providers.append(provider)

    if state.LoginModel:
        login = state.LoginModel()
        login.user = user
        login.login_at = datetime.datetime.utcnow()
        login.login_from = request.remote_addr
        login.login_user_agent = request.user_agent.string
        login.login_provider = provider
        if has_extension('frasco_geoip'):
            try:
                login.login_country = geolocate_country(use_session_cache=False)
            except:
                pass
        db.session.add(login)

    logger.info('User #%s logged in' % user.id)
    return True
    

def signup_user(email_or_user, password=None, provider=None, flash_messages=True, send_signal=True, **kwargs):
    state = get_extension_state('frasco_users')
    if isinstance(email_or_user, state.Model):
        user = email_or_user
    else:
        user = state.Model()
        user.email = email_or_user
    populate_obj(user, kwargs)

    user.signup_provider = provider or state.options['default_auth_provider_name']
    user.auth_providers = [user.signup_provider]
    if has_request_context():
        user.signup_from = request.remote_addr
        if has_extension('frasco_geoip'):
            try:
                user.signup_country = geolocate_country(use_session_cache=False)
            except:
                pass

    validate_user(user, flash_messages=flash_messages)
    if password:
        update_password(user, password, flash_messages=flash_messages)

    db.session.add(user)
    db.session.flush()

    if state.options["send_welcome_email"]:
        from frasco.mail import send_mail
        template = "users/welcome.txt" if state.options["send_welcome_email"] == True else state.options["send_welcome_email"]
        send_mail(user.email, template, user=user, locale=getattr(user, 'locale', None))

    logger.info('New signup as #%s' % user.id)
    if send_signal:
        user_signed_up.send(user=user)
    return user


class UserValidationFailedError(Exception):
    def __init__(self, reason=None):
        super(UserValidationFailedError, self).__init__()
        self.reason = reason


def validate_user(user, ignore_self=True, flash_messages=True, raise_error=True, is_signup=False):
    """Validates a new user object before saving it in the database.
    Checks if a password is present unless must_provide_password is False.
    Checks if the username is unique unless the option username_is_unique is set to False.
    If the email column exists on the user object and the option email_is_unique is set to True,
    also checks if the email is unique.
    """
    state = get_extension_state('frasco_users')
    email = user.email.strip().lower()
    has_username = hasattr(user, 'username')
    username = getattr(user, 'username', None)
    if username:
        username = username.strip()

    if state.user_validators and state.override_builtin_user_validation:
        for validator in state.user_validators:
            if not validator(username, email, is_signup):
                if raise_error:
                    raise UserValidationFailedError()
                return False
        return True

    if has_username:
        if not username and state.options["must_provide_username"]:
            if flash_messages and state.options["must_provide_username_message"]:
                flash(state.options["must_provide_username_message"], "error")
            if raise_error:
                raise UserValidationFailedError("username_missing")
            return False
        if username.lower() in state.options['forbidden_usernames']:
            if flash_messages and state.options["username_taken_message"]:
                flash(state.options["username_taken_message"], "error")
            if raise_error:
                raise UserValidationFailedError("username_forbidden")
            return False
        if len(username) < state.options['min_username_length']:
            if flash_messages and state.options["username_too_short_message"]:
                flash(state.options["username_too_short_message"], "error")
            if raise_error:
                raise UserValidationFailedError("username_too_short")
            return False
        if not state.options['allow_spaces_in_username'] and " " in username:
            if flash_messages and state.options["username_has_spaces_message"]:
                flash(state.options["username_has_spaces_message"], "error")
            if raise_error:
                raise UserValidationFailedError("username_has_spaces")
            return False
        if state.options["username_is_unique"]:
            col = state.Model.username if state.options["username_case_sensitive"] else db.func.lower(state.Model.username)
            uname = username if state.options["username_case_sensitive"] else username.lower()
            q = state.Model.query.filter(col == uname)
            if ignore_self and user.id:
                q = q.filter(state.Model.id != user.id)
            if q.count() > 0:
                if flash_messages and state.options["username_taken_message"]:
                    flash(state.options["username_taken_message"], "error")
                if raise_error:
                    raise UserValidationFailedError("username_taken")
                return False

    if not email and state.options["must_provide_email"]:
        if flash_messages and state.options["must_provide_email_message"]:
            flash(state.options["must_provide_email_message"], "error")
        if raise_error:
            raise UserValidationFailedError("email_missing")
        return False

    if email and state.options["email_is_unique"]:
        q = state.Model.query.filter(state.Model.email == email)
        if ignore_self and user.id:
            q = q.filter(state.Model.id != user.id)
        if q.count() > 0:
            if flash_messages and state.options["email_taken_message"]:
                flash(state.options["email_taken_message"], "error")
            if raise_error:
                raise UserValidationFailedError("email_taken")
            return False

    if email and state.options['email_allowed_domains'] is not None:
        if not match_email_domain(email, state.options['email_allowed_domains']):
            if flash_messages and state.options['email_domain_not_allowed_message']:
                flash(state.options['email_domain_not_allowed_message'], 'error')
            if raise_error:
                raise UserValidationFailedError('email_domain_not_allowed')
            return False

    for validator in state.user_validators:
        if not validator(username, email, is_signup):
            if raise_error:
                raise UserValidationFailedError()
            return False

    return True


def check_rate_limit(ip, remote_addr_prop, date_prop, flash_message=True):
    state = get_extension_state('frasco_users')
    since = datetime.datetime.now() - datetime.timedelta(seconds=state.options['rate_limit_period'])
    count = state.Model.query.filter(getattr(state.Model, remote_addr_prop) == ip, getattr(state.Model, date_prop) >= since).count()
    if count >= state.options['rate_limit_count']:
        if flash_message and state.options["rate_limit_reached_message"]:
            flash(state.options["rate_limit_reached_message"], "error")
        return False
    return True
