from frasco.ext import *
from frasco.i18n import lazy_translate
from frasco.utils import populate_obj, extract_unmatched_items
from flask import render_template, abort, request
from flask_login import LoginManager, logout_user, login_required, login_url, login_fresh, confirm_login, fresh_login_required, user_logged_in
import datetime
import os

from .user import *
from .model import *
from .jinja_ext import *
from .forms import *
from .tokens import *
from .tokens import TOKEN_NS_ACCESS_TOKEN
from .signals import *
from .password import *
from .blueprint import users_blueprint
from . import captcha


class FrascoUsersState(ExtensionState):
    def __init__(self, *args, **kwargs):
        super(FrascoUsersState, self).__init__(*args, **kwargs)
        self.manager = LoginManager()
        self.user_validators = []
        self.override_builtin_user_validation = False
        self.login_validators = []
        self.password_validators = []
        self.captcha_validator = None
        self.user_request_loaders = []

    def user_request_loader(self, func):
        self.user_request_loaders.append(func)
        return func


class FrascoUsers(Extension):
    name = "frasco_users"
    state_class = FrascoUsersState
    defaults = {
        # email
        "must_provide_email": True,
        "email_is_unique": True,
        "email_allowed_domains": None,
        # username
        "must_provide_username": True,
        "username_is_unique": True,
        "forbidden_usernames": [],
        "min_username_length": 1,
        "allow_spaces_in_username": False,
        "username_case_sensitive": False,
        # password
        "validate_password_regexps": None,
        "prevent_password_reuse": False,
        "max_password_reuse_saved": None,
        "min_time_between_password_change": None,
        "expire_password_after": None,
        "max_password_length": 500, # used to prevent DOS attacks
        # login
        "allow_login": True,
        "enable_2fa": False,
        "login_view": "users.login",
        "login_redirect": None, # redirect to url instead of login page
        "login_form_class": LoginWithEmailForm,
        "login_2fa_form_class": Login2FAForm,
        "allow_email_or_username_login": True,
        "remember_days": 365,
        "redirect_after_login": "index",
        "redirect_after_login_disallowed": None,
        "2fa_issuer_name": None, # default is app.config['TITLE']
        "2fa_remember_days": 60,
        "2fa_remember_cookie_options": {},
        # signup
        "signup_redirect": None, # redirect to url instead of signup page
        "allow_signup": True,
        "signup_form_class": SignupForm,
        "send_welcome_email": False,
        "login_user_on_signup": True,
        "rate_limit_count": None,
        "rate_limit_period": 60,
        "redirect_after_signup": "index",
        "redirect_after_signup_disallowed": None, # go to login
        # captcha
        "debug_captcha": False,
        "recaptcha_key": None,
        "recaptcha_secret": None,
        "hcaptcha_key": None,
        "hcaptcha_secret": None,
        # reset password
        "reset_password_redirect": None, # redirect to url instead of reset password page
        "allow_reset_password": True,
        "send_reset_password_form_class": SendResetPasswordForm,
        "reset_password_form_class": ResetPasswordForm,
        "send_reset_password_email": True,
        "reset_password_ttl": 3600, # 1h
        "login_user_on_reset_password": True,
        "redirect_after_reset_password_token": False,
        "redirect_after_reset_password": "index",
        "redirect_after_reset_password_disallowed": "users.login",
        # email validation
        "redirect_after_email_validated": "index",
        "email_validation_ttl": None,
        "block_non_email_validated_users": False,
        "send_email_validation_email": False,
        "login_after_email_validation": True,
        "allow_non_email_validated_users_who_logged_in_before": True,
        # logout
        "redirect_after_logout": "index",
        # oauth
        "oauth_signup_only": False,
        "oauth_login_only": False,
        "oauth_must_signup": False,
        "oauth_must_provide_password": False,
        # auth
        "disable_password_authentication": False,
        "default_auth_provider_name": "app",
        # access tokens
        "enable_access_tokens": False,
        "access_tokens_ttl": None,
        "enable_access_tokens_web_flow": True,
        "access_tokens_web_flow_allowed_redirects": [],
        # messages
        "login_error_message": lazy_translate("Invalid email or password"),
        "login_disallowed_message": None,
        "login_2fa_error_message": lazy_translate("Invalid two factor authentification code"),
        "login_required_message": lazy_translate("Please log in to access this page"),
        "fresh_login_required_message": lazy_translate("Please reauthenticate to access this page"),
        "password_expired_message": lazy_translate("Your password has expired, please enter a new one"),
        "must_provide_username_message": lazy_translate("A username must be provided"),
        "password_reused_message": lazy_translate("You cannot use a password which you have previously used"),
        "min_time_between_password_change_message": lazy_translate("You have changed your password too recently"),
        "validate_password_regexps_message": lazy_translate("The password does not respect the following rule: {rule}"),
        "max_password_length_message": lazy_translate("The password is too long"),
        "must_provide_email_message": lazy_translate("An email address must be provided"),
        "signup_disallowed_message": None,
        "username_taken_message": lazy_translate("An account using the same username already exists"),
        "email_taken_message": lazy_translate("An account using the same email already exists"),
        "username_too_short_message": lazy_translate("The username is too short"),
        "username_has_spaces_message": lazy_translate("The username cannot contain spaces"),
        "password_confirm_failed_message": lazy_translate("The two passwords do not match"),
        "bad_signup_code_message": lazy_translate("The provided code is not valid"),
        "rate_limit_reached_message": lazy_translate("Too many accounts have been created from this location in a too short period. Please, try again later"),
        "reset_password_token_error_message": lazy_translate("This email does not exist in our database"),
        "reset_password_token_success_message": lazy_translate("An email has been sent to your email address with a link to reset your password"),
        "reset_password_error_message": lazy_translate("Invalid or expired link to reset your password"),
        "reset_password_success_message": lazy_translate("Password successfully resetted"),
        "reset_password_disallowed_message": lazy_translate("You are not allowed to reset your password"),
        "update_password_error_message": lazy_translate("Invalid current password"),
        "update_user_email_error_message": lazy_translate("An account using the same email already exists"),
        "oauth_user_denied_login": lazy_translate("Login was denied"),
        "oauth_user_already_exists_message": lazy_translate("This {provider} account has already been used on a different account"),
        "oauth_error": lazy_translate("An error occured while authentifying you with the remote provider"),
        "captcha_fail_message": lazy_translate("The captcha validation has failed"),
        "email_validation_success_message": None,
        "enable_admin": True
    }

    def _init_app(self, app, state):
        state.Model = state.import_option('model')
        state.LoginModel = state.import_option('login_model', required=False)
        
        app.config.setdefault("REMEMBER_COOKIE_DURATION", datetime.timedelta(days=state.options["remember_days"]))

        app.register_blueprint(users_blueprint)
        app.jinja_env.add_extension(LoginRequiredExtension)
        app.jinja_env.add_extension(AnonymousOnlyExtension)
        
        state.manager.init_app(app)
        state.manager.login_view = state.options['login_view']
        state.manager.login_message_category = "error"
        populate_obj(state.manager, extract_unmatched_items(state.options, self.defaults))

        if state.options['recaptcha_key']:
            state.captcha_validator = captcha.validate_recaptcha
        elif state.options['hcaptcha_key']:
            state.captcha_validator = captcha.validate_hcaptcha

        if has_extension("frasco_mail", app):
            app.extensions.frasco_mail.add_templates_from_package(__name__)
        if has_extension("frasco_babel", app):
            app.extensions.frasco_babel.add_extract_dir(os.path.dirname(__file__), ["templates"])

        @state.manager.user_loader
        def user_loader(id):
            return state.Model.query.filter(getattr(state.Model, getattr(state.Model, '__session_cookie_identifier__', 'id')) == id).first()

        @state.manager.request_loader
        def request_loaders(request):
            for loader in state.user_request_loaders:
                user = loader(request)
                if user:
                    return user
        
        if state.options['enable_access_tokens']:
            @state.user_request_loader
            def access_token_user_loader(request):
                access_token = request.args.get('access_token')
                if 'Authorization' in request.headers:
                    authz = request.headers['Authorization']
                    if authz.startswith('Bearer '):
                        access_token = authz[7:]
                if access_token:
                    return read_user_token(access_token, TOKEN_NS_ACCESS_TOKEN, state.options['access_tokens_ttl'])

        if state.options['block_non_email_validated_users']:
            @app.before_request
            def block_non_email_validated_users():
                if current_user.is_authenticated and current_user.must_validate_email and (not request.endpoint or \
                  (request.endpoint not in ('users.logout', 'users.send_email_validation_email', 'users.validate_email', 'static') and \
                  not request.endpoint.endswith('.static'))):
                    if request.is_json:
                        abort(403)
                    return render_template("users/non_email_validated_users_block_page.html", email=current_user.email)

    @ext_stateful_method
    def user_validator(self, state, func):
        state.user_validators.append(func)
        return func

    @ext_stateful_method
    def login_validator(self, state, func):
        state.login_validators.append(func)
        return func

    @ext_stateful_method
    def password_validator(self, state, func):
        state.password_validators.append(func)
        return func
