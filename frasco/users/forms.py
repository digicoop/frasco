from flask_wtf import FlaskForm
from wtforms import validators, StringField, PasswordField, BooleanField
from wtforms.fields.html5 import EmailField
from frasco.i18n import lazy_translate


__all__ = ('LoginWithEmailForm', 'LoginWithUsernameForm', 'LoginWithIdentifierForm',
           'Login2FAForm', 'SignupForm', 'SignupWithUsernameForm', 'SignupFormWithTOSMixin',
           'SendResetPasswordForm', 'ResetPasswordForm')


class BaseLoginForm(FlaskForm):
    password = PasswordField(lazy_translate('Password'), validators=[validators.input_required()])
    remember = BooleanField(lazy_translate('Remember me'))


class LoginWithEmailForm(BaseLoginForm):
    identifier = EmailField(lazy_translate('Email'), validators=[validators.input_required()])


class LoginWithUsernameForm(BaseLoginForm):
    identifier = StringField(lazy_translate('Username'), validators=[validators.input_required()])
    

class LoginWithIdentifierForm(BaseLoginForm):
    identifier = StringField(lazy_translate('Username or email'), validators=[validators.input_required()])


class Login2FAForm(FlaskForm):
    code = StringField(lazy_translate('Two factor authentification code'), validators=[validators.input_required()])
    remember = BooleanField(lazy_translate("Dont't ask again on this computer"))
    

class SignupForm(FlaskForm):
    email = EmailField(lazy_translate('Email'), validators=[validators.input_required()])
    password = PasswordField(lazy_translate('Password'))
    

class SignupWithUsernameForm(SignupForm):
    username = StringField(lazy_translate('Username'), validators=[validators.input_required()])


class SignupFormWithTOSMixin(object):
    tos = BooleanField(lazy_translate('You agree to our Terms of Service'), validators=[validators.data_required()])


class SendResetPasswordForm(FlaskForm):
    email = EmailField(lazy_translate('Email'), validators=[validators.input_required()])
    

class ResetPasswordForm(FlaskForm):
    password = PasswordField(lazy_translate('Password'), validators=[validators.input_required()])
    confirm_password = PasswordField(lazy_translate('Confirm password'), validators=[validators.input_required()])
    
