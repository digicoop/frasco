from flask import request, flash, redirect, session, current_app, Blueprint
from frasco.helpers import url_for
from frasco.ext import get_extension_state
from frasco.users.user import login_user, is_user_logged_in, current_user
from frasco.models import db
from frasco.utils import populate_obj
from frasco.tasks import get_current_job
from frasco.redis.objects import JSONRedisHash
from authlib.flask.client import OAuth
from sqlalchemy.dialects import postgresql
import datetime
import uuid
import hashlib


class OAuth1RequestTokenCache(object):
    def __init__(self):
        self._data = {}

    def get(self, k):
        return self._data.get(k)

    def set(self, k, v, timeout=None):
        self._data[k] = v

    def delete(self, k):
        if k in self._data:
            del self._data[k]


class OAuth1RequestTokenRedisCache(OAuth1RequestTokenCache):
    def __init__(self, *args, **kwargs):
        self._data = JSONRedisHash(*args, **kwargs)


class UserOAuthTokenModelMixin(object):
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    provider = db.Column(db.String)
    token_type = db.Column(db.String)
    access_token = db.Column(db.String)
    access_token_secret = db.Column(db.String)
    refresh_token = db.Column(db.String)
    token_expires_at = db.Column(db.DateTime)
    scope = db.Column(db.String)
    data = db.Column(postgresql.JSONB)

    def to_oauth1_token(self):
        return dict(
            oauth_token=self.access_token,
            oauth_token_secret=self.access_token_secret,
        )

    def to_oauth2_token(self):
        o = dict(
            access_token=self.access_token,
            token_type=self.token_type,
            refresh_token=self.refresh_token,
        )
        if self.token_expires_at:
            o['expires_at'] = self.token_expires_at
        return o


class OAuthUserModelMixin(object):
    @classmethod
    def query_by_oauth_token(cls, provider, id_property, id_value):
        return cls.query.join(cls.__oauth_token_model__).filter(
            cls.__oauth_token_model__.data[id_property].astext == unicode(id_value)).first()

    def get_oauth_token(self, provider):
        return self.oauth_tokens.filter(self.__oauth_token_model__.provider == provider).first()

    def save_oauth_token_data(self, provider, data):
        oauth_token = self.get_oauth_token(provider)
        props = {
            'token_type': data.pop('token_type', None),
            'access_token': data.pop('access_token', None),
            'refresh_token': data.pop('refresh_token', None),
            'token_expires_at': data.pop('expires_at', None),
            'scope': data.pop('scope', None),
            'data': data
        }
        if not oauth_token:
            self.oauth_tokens.append(self.__oauth_token_model__(provider=provider, **props))
        else:
            populate_obj(oauth_token, props)

    def remove_oauth_token(self, provider):
        token = self.get_oauth_token(provider)
        if token:
            self.oauth_tokens.remove(token)


oauth = OAuth()


def create_token_user_fetcher(name):
    def fetch_token():
        if is_user_logged_in():
            return current_user.get_oauth_token(name).to_oauth2_token()
    return fetch_token


def create_token_session_fetcher(name):
    def fetch_token():
        job = get_current_job()
        if job:
            return job.meta['session']['%s_oauth_token' % name]
        return session['%s_oauth_token' % name]
    return fetch_token


def create_login_blueprint(name, authorize_handler):
    login_blueprint = Blueprint('%s_login' % name, __name__)

    @login_blueprint.route('/login/%s' % name)
    def login():
        session['oauth_redirect_next'] = request.args.get('next')
        callback_url = url_for('.callback', _external=True)
        return getattr(oauth, name).authorize_redirect(callback_url)

    @login_blueprint.route('/login/%s/callback' % name)
    def callback():
        redirect_url = session.pop('oauth_redirect_next', None)
        token = getattr(oauth, name).authorize_access_token()
        if token is None:
            flash(current_app.extensions.frasco_users.options["oauth_user_denied_login"], "error")
            return redirect(url_for("users.login"))
        try:
            return authorize_handler(token, redirect_url)
        except Exception as e:
            current_app.log_exception(e)
            flash(current_app.extensions.frasco_users.options["oauth_error"], "error")
            return redirect(url_for("users.login"))

    return login_blueprint


def create_session_login_blueprint(name):
    def authorize_handler(token, redirect_url):
        return oauth_session_login(name, token, redirect_url=redirect_url)
    return create_login_blueprint(name, authorize_handler)


def oauth_session_login(provider, token, redirect_url=None):
    state = get_extension_state('frasco_users')
    session['%s_oauth_token' % provider] = token
    if not redirect_url:
        redirect_url = request.args.get('next') or url_for(state.options["redirect_after_login"])
    return redirect(redirect_url)


def oauth_login(provider, id_property, id_value, data, defaults, redirect_url=None):
    """Execute a login via oauth. If no user exists, oauth_signup() will be called
    """
    state = get_extension_state('frasco_users')
    user = state.Model.query_by_oauth_token(provider, id_property, id_value)
    if not redirect_url:
        redirect_url = request.args.get('next') or url_for(state.options["redirect_after_login"])
    if is_user_logged_in():
        if user and user != current_user:
            if state.options["oauth_user_already_exists_message"]:
                flash(state.options["oauth_user_already_exists_message"].format(provider=provider), "error")
            return redirect(redirect_url)
        user = current_user
        if provider not in user.auth_providers:
            user.auth_providers.append(provider)
    elif not user:
        return oauth_signup(provider, data, defaults, redirect_url=redirect_url)
    else:
        login_user(user, provider=provider)
    user.save_oauth_token_data(provider, data)
    return redirect(redirect_url)


def oauth_signup(provider, data, defaults, redirect_url=None):
    """Start the signup process after having logged in via oauth
    """
    session["oauth_signup"] = provider
    session["oauth_data"] = data
    session["oauth_user_defaults"] = defaults
    if not redirect_url:
        redirect_url = request.args.get("next")
    return redirect(url_for('users.oauth_signup', next=redirect_url))


def clear_oauth_signup_session():
    session.pop("oauth_signup", None)
    session.pop("oauth_data", None)
    session.pop("oauth_user_defaults", None)
