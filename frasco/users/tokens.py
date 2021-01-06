from flask import current_app, abort
from frasco.ext import get_extension_state
from itsdangerous import URLSafeTimedSerializer, BadSignature
from werkzeug.local import LocalProxy


__all__ = ('user_token_serializer', 'generate_user_token', 'read_user_token', 'read_user_token_or_404')


TOKEN_NS_ACCESS_TOKEN = 'access-token'
TOKEN_NS_2FA = '2fa'
TOKEN_NS_PASSWORD_RESET = 'password-reset'
TOKEN_NS_VALIDATE_EMAIL = 'validate-email'


def get_user_token_serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'])


user_token_serializer = LocalProxy(get_user_token_serializer)


def get_token_identifier_property():
    return getattr(get_extension_state('frasco_users').Model, '__token_identifier_property__', 'id')


def generate_user_token(user, salt=None):
    return user_token_serializer.dumps(getattr(user, get_token_identifier_property()), salt=salt)


def read_user_token(token, salt=None, max_age=None):
    try:
        user_id = user_token_serializer.loads(token, salt=salt, max_age=max_age)
        model = get_extension_state('frasco_users').Model
        return model.query.filter(getattr(model, get_token_identifier_property()) == user_id).first()
    except BadSignature:
        return None


def read_user_token_or_404(*args, **kwargs):
    user = read_user_token(*args, **kwargs)
    if not user:
        abort(404)
    return user
