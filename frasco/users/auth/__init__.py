from frasco.ext import get_extension_state
from frasco.models import db
from ..password import check_password


AUTH_HANDLERS = []


def register_authentification_handler(func=None, only=False):
    def decorator(f):
        if only:
            AUTH_HANDLERS[:] = []
        AUTH_HANDLERS.append(f)
        return f
    if func:
        return decorator(func)
    return decorator


def authenticate(identifier, password):
    state = get_extension_state('frasco_users')
    for func in AUTH_HANDLERS:
        user = func(identifier, password)
        if user:
            return user

    if not state.options["disable_password_authentication"]:
        if state.options['allow_email_or_username_login'] and hasattr(state.Model, 'username'):
            q = state.Model.query.filter(db.or_(state.Model.username == identifier, state.Model.email == identifier))
        else:
            q = state.Model.query_by_identifier(identifier)
        user = q.first()
        if user and check_password(user, password):
            return user
