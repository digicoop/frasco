from flask import g, has_request_context, request, current_app
from frasco.ext import *
from frasco.users import is_user_logged_in, current_user
from frasco.models import delayed_tx_calls
from frasco.ctx import ContextStack
from itsdangerous import URLSafeTimedSerializer
from redis import StrictRedis
import hashlib
import logging
import subprocess
import sys
import pickle
import uuid
import click


suppress_push_events = ContextStack(False, default_item=True, ignore_nested=True)
dont_skip_self_push_events = ContextStack(False, default_item=True, ignore_nested=True)
logger = logging.getLogger('frasco.push')


class FrascoPushState(ExtensionState):
    def __init__(self, *args, **kwargs):
        super(FrascoPushState, self).__init__(*args, **kwargs)
        self.current_user_loader = default_current_user_loader


class FrascoPush(Extension):
    name = 'frasco_push'
    state_class = FrascoPushState
    defaults = {"redis_url": None,
                "server_url": None,
                "server_port": 8888,
                "server_secured": False,
                "channel": "socketio",
                "secret": None,
                "prefix_event_with_room": True,
                "default_current_user_loader": True}

    def _init_app(self, app, state):
        if state.options['secret'] is None:
            state.options["secret"] = app.config['SECRET_KEY']
        
        if not state.options['redis_url'] and has_extension('frasco_redis', app):
            state.options['redis_url'] = app.extensions.frasco_redis.options['url']

        state.server_cli = ["python", "-m", "frasco.push.server",
            "--channel", state.options["channel"],
            "--redis", state.options["redis_url"],
            "--port", str(state.options["server_port"])]
        if state.options['secret']:
            state.server_cli.extend(["--secret", state.options["secret"]])
        if app.debug or app.testing:
            state.server_cli.append("--debug")

        if state.options["server_url"]:
            state.server_url = state.options['server_url']
        else:
            server_name = app.config.get('SERVER_NAME') or 'localhost'
            state.server_url = "%s://%s:%s" % (
                "https" if state.options['server_secured'] else "http",
                server_name.split(':')[0], state.options['server_port'])

        state.token_serializer = URLSafeTimedSerializer(state.options['secret'])
        state.redis = StrictRedis.from_url(state.options["redis_url"])
        state.host_id = uuid.uuid4().hex

        @app.cli.command('push-server')
        @click.option('--access-logs', is_flag=True)
        def cli_command(access_logs=False):
            args = list(state.server_cli)
            if access_logs:
                args.append("--access-logs")
            process = subprocess.Popen(args)
            process.wait()
            sys.exit(process.returncode)

        @app.cli.command('push-server-cli')
        def cli_command():
            click.echo(" ".join(state.server_cli))

        @app.before_request
        def before_request():
            if state.options['secret']:
                user_id, user_info, allowed_rooms = state.current_user_loader()
                g.socketio_token = create_push_token(user_info, allowed_rooms)
                if user_id:
                    g.socketio_user_event = get_user_push_event_name(user_id)

    @ext_stateful_method
    def current_user_loader(self, state, func):
        state.current_user_loader = func
        return func


def default_current_user_loader():
    if not is_user_logged_in():
        return None, {"guest": True}, None

    allowed_rooms = None
    if hasattr(current_user, 'get_allowed_push_rooms'):
        allowed_rooms = current_user.get_allowed_push_rooms()

    info = {"guest": False}
    info['username'] = getattr(current_user, 'username', current_user.email)
    if has_extension('frasco_users_avatar'):
        info['avatar_url'] = current_user.avatar_url

    return current_user.get_id(), info, allowed_rooms


def create_push_token(user_info=None, allowed_rooms=None):
    return get_extension_state('frasco_push').token_serializer.dumps([user_info, allowed_rooms])


@delayed_tx_calls.proxy
def emit_push_event(event, data=None, skip_self=None, room=None, namespace=None):
    if suppress_push_events.top:
        return
    state = get_extension_state('frasco_push')
    if state.options['prefix_event_with_room'] and room:
        event = "%s:%s" % (room, event)
    if skip_self is None:
        skip_self = not dont_skip_self_push_events.top
    skip_sid = None
    if skip_self and has_request_context() and 'x-socketio-sid' in request.headers:
        skip_sid = request.headers['x-socketio-sid']
    logger.debug("Push event '%s' to {namespace=%s, room=%s, skip_sid=%s}: %s" % (event, namespace, room, skip_sid, data))
    return state.redis.publish(state.options['channel'], format_emit_data(event, data, namespace, room, skip_sid))


def emit_user_push_event(user_id, data=None, **kwargs):
    return emit_push_event(get_user_push_event_name(user_id), data=data, **kwargs)


def get_user_push_event_name(user_id):
    state = get_extension_state('frasco_push')
    if not state.options['secret']:
        raise Exception('A secret must be set to use emit_direct()')
    return hashlib.sha1(str(user_id) + state.options['secret']).hexdigest()


def format_emit_data(event, data, namespace=None, room=None, skip_sid=None):
    # See https://github.com/miguelgrinberg/python-socketio/blob/master/socketio/pubsub_manager.py#L65
    return pickle.dumps({
        'method': 'emit',
        'event': event,
        'data': data,
        'namespace': namespace or '/',
        'room': room,
        'skip_sid': skip_sid,
        'callback': None,
        'host_id': get_extension_state('frasco_push').host_id
    })
