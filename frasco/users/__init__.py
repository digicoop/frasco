from frasco.ext import *
from frasco.i18n import lazy_translate
from frasco.utils import populate_obj, extract_unmatched_items
from flask_login import LoginManager, logout_user, login_required, login_url, login_fresh, confirm_login, fresh_login_required, user_logged_in
import datetime
import os

from .user import *
from .model import *
from .jinja_ext import *
from .forms import *
from .tokens import *
from .signals import *
from .password import *
from .blueprint import users_blueprint


class FrascoUsersState(ExtensionState):
    def __init__(self, *args, **kwargs):
        super(FrascoUsersState, self).__init__(*args, **kwargs)
        self.manager = LoginManager()
        self.user_validators = []
        self.override_builtin_user_validation = False
        self.login_validators = []
        self.password_validators = []


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
        # login
        "allow_login": True,
        "login_view": "users.login",
        "login_redirect": None, # redirect to url instead of login page
        "login_form_class": LoginWithEmailForm,
        "allow_email_or_username_login": True,
        "remember_days": 365,
        "redirect_after_login": "index",
        "redirect_after_login_disallowed": None,
        # signup
        "signup_redirect": None, # redirect to url instead of signup page
        "allow_signup": True,
        "signup_form_class": SignupForm,
        "send_welcome_email": False,
        "login_user_on_signup": True,
        "recaptcha_key": None,
        "recaptcha_secret": None,
        "rate_limit_count": None,
        "rate_limit_period": 60,
        "redirect_after_signup": "index",
        "redirect_after_signup_disallowed": None, # go to login
        # reset password
        "reset_password_redirect": None, # redirect to url instead of reset password page
        "allow_reset_password": True,
        "send_reset_password_form_class": SendResetPasswordForm,
        "reset_password_form_class": ResetPasswordForm,
        "send_reset_password_email": True,
        "reset_password_ttl": 86400,
        "login_user_on_reset_password": True,
        "redirect_after_reset_password_token": False,
        "redirect_after_reset_password": "index",
        "redirect_after_reset_password_disallowed": "users.login",
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
        # messages
        "login_error_message": lazy_translate(u"Invalid email or password"),
        "login_disallowed_message": None,
        "login_required_message": lazy_translate(u"Please log in to access this page"),
        "fresh_login_required_message": lazy_translate(u"Please reauthenticate to access this page"),
        "password_expired_message": lazy_translate(u"Your password has expired, please enter a new one"),
        "must_provide_username_message": lazy_translate(u"A username must be provided"),
        "password_reused_message": lazy_translate(u"You cannot use a password which you have previously used"),
        "min_time_between_password_change_message": lazy_translate(u"You have changed your password too recently"),
        "validate_password_regexps_message": lazy_translate(u"The password does not respect the following rule: {rule}"),
        "must_provide_email_message": lazy_translate(u"An email address must be provided"),
        "signup_disallowed_message": None,
        "username_taken_message": lazy_translate(u"An account using the same username already exists"),
        "email_taken_message": lazy_translate(u"An account using the same email already exists"),
        "username_too_short_message": lazy_translate(u"The username is too short"),
        "username_has_spaces_message": lazy_translate(u"The username cannot contain spaces"),
        "password_confirm_failed_message": lazy_translate(u"The two passwords do not match"),
        "bad_signup_code_message": lazy_translate(u"The provided code is not valid"),
        "rate_limit_reached_message": lazy_translate(u"Too many accounts have been created from this location in a too short period. Please, try again later"),
        "reset_password_token_error_message": lazy_translate(u"This email does not exist in our database"),
        "reset_password_token_success_message": lazy_translate(u"An email has been sent to your email address with a link to reset your password"),
        "reset_password_error_message": lazy_translate(u"Invalid or expired link to reset your password"),
        "reset_password_success_message": lazy_translate(u"Password successfully resetted"),
        "reset_password_disallowed_message": lazy_translate(u"You are not allowed to reset your password"),
        "update_password_error_message": lazy_translate(u"Invalid current password"),
        "update_user_email_error_message": lazy_translate(u"An account using the same email already exists"),
        "oauth_user_denied_login": lazy_translate("Login was denied"),
        "oauth_user_already_exists_message": lazy_translate(u"This {provider} account has already been used on a different account"),
        "oauth_error": lazy_translate("An error occured while authentifying you with the remote provider"),
        "recaptcha_fail_message": lazy_translate(u"The captcha validation has failed"),
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

        if has_extension("frasco_mail", app):
            app.extensions.frasco_mail.add_templates_from_package(__name__)
        if has_extension("frasco_babel", app):
            app.extensions.frasco_babel.add_extract_dir(os.path.dirname(__file__), ["templates"])

        @state.manager.user_loader
        def user_loader(id):
            return state.Model.query.get(id)

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
