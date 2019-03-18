from flask import request
from frasco.ext import *
from frasco.models import db
from frasco.users import get_current_user, is_user_logged_in
import base64
import datetime
import hashlib
import uuid
import functools
import psycopg2
from .service import ApiAuthentificationRequiredError


class ApiKeyModelMixin(object):
    value = db.Column(db.String, index=True)
    last_accessed_at = db.Column(db.DateTime)
    last_accessed_from = db.Column(db.String)
    expires_at = db.Column(db.DateTime)


class FrascoApiKeyAuthentification(Extension):
    name = 'frasco_api_key_auth'

    def _init_app(self, app, state):
        require_extension('frasco_users', app)
        state.Model = state.import_option('model')

        @app.extensions.frasco_users.manager.request_loader
        def load_user_from_request(request):
            api_key = request.headers.get('Authorization')
            if not api_key:
                return
            header_val = api_key.replace('Basic ', '', 1)
            try:
                header_val = base64.b64decode(header_val)
                key_value = header_val.split(':')[0]
            except:
                return
            try:
                key = state.Model.query.filter_by(value=key_value).first()
            except psycopg2.DataError:
                return
            if key:
                now = datetime.datetime.utcnow()
                if key.expires_at and key.expires_at < now:
                    return None
                key.last_accessed_at = now
                key.last_accessed_from = request.remote_addr
                db.session.commit()
                return key.user


def create_api_key(user=None, expires_at=None):
    state = get_extension_state('frasco_api_key_auth')
    if not expires_at and state.options.get('default_key_duration'):
        expires_at = datetime.datetime.now() + datetime.timedelta(
            seconds=state.options['default_key_duration'])
    key = state.Model()
    key.user = get_current_user(user)
    key.value = hashlib.sha1(str(uuid.uuid4)).hexdigest()
    key.expires_at = expires_at
    return key


def auth_required(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not is_user_logged_in():
            raise ApiAuthentificationRequiredError()
        return func(*args, **kwargs)
    return wrapper


def authenticated_service(service):
    service.decorators.append(auth_required)
    return service
