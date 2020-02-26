from flask import flash, has_request_context, request
from frasco.ext import get_extension_state
from flask_bcrypt import Bcrypt
import datetime
import re
import logging
import uuid

from .tokens import generate_user_token, read_user_token
from .signals import reset_password_sent, password_updated


__all__ = ('hash_password', 'PasswordValidationFailedError', 'validate_password', 'update_password',
            'check_password', 'generate_reset_password_token', 'send_reset_password_token')


bcrypt = Bcrypt()
logger = logging.getLogger('frasco.users')


def generate_random_password():
    return str(uuid.uuid4()).replace('-', '')


def hash_password(password):
    return bcrypt.generate_password_hash(password).decode('utf-8')


def check_password(user, password):
    state = get_extension_state('frasco_users')
    if state.options['enable_2fa'] and user.two_factor_auth_enabled and bcrypt.check_password_hash(user.otp_recovery_code, password):
        from .otp import disable_2fa
        disable_2fa(user)
        return True
    return user.password and bcrypt.check_password_hash(user.password, password)


class PasswordValidationFailedError(Exception):
    def __init__(self, reason=None, rule=None):
        super(PasswordValidationFailedError, self).__init__()
        self.reason = reason
        self.rule = rule

    def __str__(self):
        return self.reason


def validate_password(user, password, flash_messages=True, raise_error=True):
    state = get_extension_state('frasco_users')

    if state.options['min_time_between_password_change'] and user.last_password_change_at and not user.must_reset_password_at_login:
        if (datetime.datetime.utcnow() - user.last_password_change_at).total_seconds() < state.options['min_time_between_password_change']:
            if flash_messages and state.options['min_time_between_password_change_message']:
                flash(state.options['min_time_between_password_change_message'], 'error')
            if raise_error:
                raise PasswordValidationFailedError("password_change_too_soon")
            return False

    if state.options['validate_password_regexps']:
        for pattern, label in state.options['validate_password_regexps']:
            if not re.search(pattern, password):
                if flash_messages and state.options['validate_password_regexps_message']:
                    flash(state.options['validate_password_regexps_message'].format(rule=label), 'error')
                if raise_error:
                    raise PasswordValidationFailedError("invalid_password", label)
                return False

    if state.options['prevent_password_reuse'] and user.password:
        for oldhash in [user.password] + (user.previous_passwords or []):
            if oldhash and bcrypt.check_password_hash(oldhash, password):
                if flash_messages and state.options['password_reused_message']:
                    flash(state.options['password_reused_message'], 'error')
                if raise_error:
                    raise PasswordValidationFailedError("password_reused")
                return False

    for validator in state.password_validators:
        if not validator(password):
            if raise_error:
                raise PasswordValidationFailedError()
            return False

    return True


def update_password(user, password, skip_validation=False, **kwargs):
    """Updates the password of a user
    """
    state = get_extension_state('frasco_users')
    pwhash = hash_password(password)
    if not skip_validation and not validate_password(user, password, **kwargs):
        return False
    if state.options['prevent_password_reuse']:
        user.previous_passwords = [user.password] + (user.previous_passwords or [])
        if state.options['max_password_reuse_saved']:
            user.previous_passwords = user.previous_passwords[:state.options['max_password_reuse_saved']]
    user.password = pwhash
    user.last_password_change_at = datetime.datetime.utcnow()
    if has_request_context():
        user.last_password_change_from = request.remote_addr
    user.must_reset_password_at_login = False
    password_updated.send(user=user)
    if user.id:
        logger.info('Password changed for user #%s' % user.id)
    return True


def generate_reset_password_token(user):
    return generate_user_token(user, salt="password-reset")


def send_reset_password_token(user):
    """Generates a reset password token and optionnaly (default to yes) send the reset
    password email
    """
    from frasco.mail import send_mail
    token = generate_reset_password_token(user)
    send_mail(user.email, "users/reset_password", user=user, token=token, locale=getattr(user, 'locale', None))
    reset_password_sent.send(user=user, token=token)
    logger.info('Password reset token sent to user #%s' % user.id)
    return token
