from flask import current_app
from frasco.ext import get_extension_state
from frasco.mail import send_mail
import pyotp

from .password import hash_password, generate_random_password


def generate_otp_code(user):
    user.otp_code = pyotp.random_base32()
    return generate_otpauth_url(user)


def enable_2fa(user, code):
    if not verify_2fa(user, code):
        return False
    user.two_factor_auth_enabled = True
    recovery_code = generate_otp_recovery_code(user)
    send_mail(user.email, 'users/2fa_enabled', recovery_code=recovery_code)
    return recovery_code


def disable_2fa(user):
    if not user.two_factor_auth_enabled:
        return
    user.two_factor_auth_enabled = False
    user.otp_code = None
    user.otp_recovery_code = None
    send_mail(user.email, 'users/2fa_disabled')


def verify_2fa(user, code):
    if not user.otp_code:
        return False
    totp = pyotp.TOTP(user.otp_code)
    return totp.verify(code)


def generate_otp_recovery_code(user):
    recovery_code = generate_random_password()
    user.otp_recovery_code = hash_password(recovery_code)
    return recovery_code


def generate_otpauth_url(user):
    return pyotp.totp.TOTP(user.otp_code).provisioning_uri(user.email,
        issuer_name=get_extension_state('frasco_users').options['2fa_issuer_name'] or current_app.config.get('TITLE'))
