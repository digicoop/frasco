from frasco.models import db, transaction
from frasco.models.utils import MutableList
from frasco import current_app
from frasco.ext import get_extension_state
from frasco.redis import redis
from flask_login import UserMixin
from sqlalchemy.dialects import postgresql
import datetime
import uuid


__all__ = ('UserModelMixin', 'UserWithUsernameModelMixin', 'UserLastAccessAtModelMixin',
           'UserOTPCodeMixin', 'UserLoginModelMixin', 'UserEmailValidatedMixin', 'UserAuthTokenMixin')


class UserModelMixin(UserMixin):
    email = db.Column(db.String)
    password = db.Column(db.String, nullable=True)
    last_password_change_at = db.Column(db.DateTime)
    last_password_change_from = db.Column(db.String)
    previous_passwords = db.Column(MutableList.as_mutable(postgresql.ARRAY(db.String)))
    must_reset_password_at_login = db.Column(db.Boolean, default=False)
    signup_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    signup_from = db.Column(db.String)
    signup_provider = db.Column(db.String)
    signup_country = db.Column(db.String)
    last_login_at = db.Column(db.DateTime)
    last_login_from = db.Column(db.String)
    last_login_provider = db.Column(db.String)
    updated_at = db.Column(db.DateTime)
    auth_providers = db.Column(MutableList.as_mutable(postgresql.ARRAY(db.String)), default=list)

    @classmethod
    def query_by_email(cls, email):
        return cls.query.filter(cls.email == email.strip().lower())

    @classmethod
    def query_by_identifier(cls, identifier):
        return cls.query_by_email(identifier)


class UserWithUsernameModelMixin(UserModelMixin):
    username = db.Column(db.String, unique=True)

    @classmethod
    def query_by_username(cls, username):
        return cls.query.filter(db.func.lower(cls.username) == username.strip().lower())

    @classmethod
    def query_by_username_or_email(cls, identifier):
        return cls.query.filter(db.or_(db.func.lower(cls.username) == identifier.strip().lower(),
            cls.email == identifier.strip().lower()))

    @classmethod
    def query_by_identifier(cls, identifier):
        return cls.query_by_username(identifier)


class UserLastAccessAtModelMixin(object):
    last_access_at = db.Column(db.Date)

    def update_last_access_at(self):
        if not self.id:
            return
        today_key = "users-last-access-%s" % datetime.date.today().isoformat()
        if not redis.getbit(today_key, self.id):
            with transaction():
                self.last_access_at = datetime.date.today()
            redis.setbit(today_key, self.id, 1)
            redis.expire(today_key, 86500)


class UserOTPCodeMixin(object):
    two_factor_auth_enabled = db.Column(db.Boolean, default=False)
    otp_code = db.Column(db.String, unique=True)
    otp_recovery_code = db.Column(db.String)


class UserLoginModelMixin(object):
    login_at = db.Column(db.DateTime)
    login_from = db.Column(db.String)
    login_provider = db.Column(db.String)
    login_country = db.Column(db.String)
    login_user_agent = db.Column(db.String)


class UserEmailValidatedMixin(object):
    email_validated = db.Column(db.Boolean, default=False)
    email_validated_at = db.Column(db.DateTime)

    @property
    def must_validate_email(self):
        if get_extension_state('frasco_users').options['allow_non_email_validated_users_who_logged_in_before'] and self.last_login_at:
            return False
        return not self.email_validated


class UserAuthTokenMixin(object):
    __token_identifier_property__ = 'auth_token'
    __session_cookie_identifier__ = 'auth_token'

    auth_token = db.Column(db.String, default=lambda: str(uuid.uuid4()), unique=True)

    @classmethod
    def query_by_auth_token(cls, token):
        return cls.query.filter(cls.auth_token == token)

    @classmethod
    def get_by_auth_token(cls, token):
        return cls.query_by_auth_token(token).first()

    def get_id(self):
        # for Flask-Login
        return self.auth_token

    def invalidate_auth_token(self):
        self.auth_token = str(uuid.uuid4())
