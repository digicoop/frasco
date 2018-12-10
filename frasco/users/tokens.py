from flask import current_app, abort
from itsdangerous import URLSafeTimedSerializer, BadSignature
from werkzeug.local import LocalProxy


__all__ = ('user_token_serializer', 'generate_user_token', 'read_user_token', 'read_user_token_or_404')


def get_user_token_serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'])


user_token_serializer = LocalProxy(get_user_token_serializer)


def generate_user_token(user, salt=None):
    return user_token_serializer.dumps(str(user.id), salt=salt)


def read_user_token(token, salt=None, max_age=None):
    try:
        return user_token_serializer.loads(token, salt=salt, max_age=max_age)
    except BadSignature:
        return None


def read_user_token_or_404(*args, **kwargs):
    user = read_user_token(*args, **kwargs)
    if not user:
        abort(404)
    return user
