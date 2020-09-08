import socketio
from socketio.exceptions import ConnectionRefusedError
import os
import urllib.parse
import uuid
import json
from itsdangerous import URLSafeTimedSerializer, BadSignature
from eventlet import wsgi
import eventlet
import logging


eventlet.sleep()
eventlet.monkey_patch()


logger = logging.getLogger('frasco.push.server')


class PresenceEnabledRedisManager(socketio.RedisManager):
    def __init__(self, *args, **kwargs):
        self.presence_session_id = kwargs.pop('presence_session_id', None) or ''
        self.presence_key_prefix = "presence%s:" % self.presence_session_id
        super(PresenceEnabledRedisManager, self).__init__(*args, **kwargs)

    def _emit_joined(self, room, sid, info):
        self.server.emit('%s:joined' % room, {"sid": sid, "info": info}, room=room, skip_sid=sid)

    def enter_room(self, sid, namespace, room, skip_presence=False):
        super(PresenceEnabledRedisManager, self).enter_room(sid, namespace, room)
        if room and room != sid and not skip_presence:
            self.redis.sadd("%s%s:%s" % (self.presence_key_prefix, namespace, room), sid)
            self._emit_joined(room, sid, self.get_member_info(sid, namespace))

    def leave_room(self, sid, namespace, room):
        super(PresenceEnabledRedisManager, self).leave_room(sid, namespace, room)
        if room and room != sid:
            if self.redis.srem("%s%s:%s" % (self.presence_key_prefix, namespace, room), sid):
                self.server.emit('%s:left' % room, sid, room=room, skip_sid=sid)

    def get_room_members(self, namespace, room):
        return [sid.decode() for sid in self.redis.smembers("%s%s:%s" % (self.presence_key_prefix, namespace, room))]

    def set_member_info(self, sid, namespace, info):
        self.redis.set("%s%s@%s" % (self.presence_key_prefix, namespace, sid), json.dumps(info))
        for room in self.get_rooms(sid, namespace):
            if room != sid:
                self._emit_joined(room, sid, info)

    def get_member_info(self, sid, namespace):
        data = self.redis.get("%s%s@%s" % (self.presence_key_prefix, namespace, sid))
        if data:
            try:
                return json.loads(data)
            except:
                pass
        return {}

    def disconnect(self, sid, namespace):
        super(PresenceEnabledRedisManager, self).disconnect(sid, namespace)
        self.redis.delete("%s%s@%s" % (self.presence_key_prefix, namespace, sid))

    def cleanup_presence_keys(self):
        keys = self.redis.keys('%s*' % self.presence_key_prefix)
        pipe = self.redis.pipeline()
        for key in keys:
            pipe.delete(key)
        pipe.execute()


class PresenceEnabledServer(socketio.Server):
    def enter_room(self, sid, room, namespace=None, skip_presence=False):
        namespace = namespace or '/'
        self.logger.debug('%s is entering room %s [%s]', sid, room, namespace)
        self.manager.enter_room(sid, namespace, room, skip_presence)


def create_app(redis_url='redis://', channel='socketio', secret=None, presence_session_id=None, token_max_age=None, debug=False):
    mgr = PresenceEnabledRedisManager(redis_url, channel=channel, presence_session_id=presence_session_id)
    sio = PresenceEnabledServer(client_manager=mgr, async_mode='eventlet', logger=debug, cors_allowed_origins='*') # client must be identified via url token so cors to * is not a big risk
    token_serializer = URLSafeTimedSerializer(secret)
    default_ns = '/'

    @sio.on('connect')
    def connect(sid, env):
        if not secret:
            raise ConnectionRefusedError('no secret defined')

        qs = urllib.parse.parse_qs(env['QUERY_STRING'])
        if not 'token' in qs:
            raise ConnectionRefusedError('missing token')

        try:
            token_data = token_serializer.loads(qs['token'][0], max_age=token_max_age)
        except BadSignature:
            logger.debug('Client provided an invalid token')
            raise ConnectionRefusedError('invalid token')

        if len(token_data) == 3:
            user_info, user_room, allowed_rooms = token_data
        else:
            # old format
            user_info, allowed_rooms = token_data
            user_room = None

        env['allowed_rooms'] = allowed_rooms
        if user_info:
            mgr.set_member_info(sid, default_ns, user_info)
        if user_room:
            sio.enter_room(sid, user_room, skip_presence=True)

        logger.debug('New client connection: %s ; %s' % (sid, user_info))
        return True

    @sio.on('members')
    def get_room_members(sid, data):
        if not data.get('room') or data['room'] not in mgr.get_rooms(sid, default_ns):
            return []
        return {sid: mgr.get_member_info(sid, default_ns) for sid in mgr.get_room_members(default_ns, data['room'])}

    @sio.on('join')
    def join(sid, data):
        if sio.environ[sid].get('allowed_rooms') is not None and data['room'] not in sio.environ[sid]['allowed_rooms']:
            logger.debug('Client %s is not allowed to join room %s' % (sid, data['room']))
            return False
        sio.enter_room(sid, data['room'])
        logger.debug('Client %s has joined room %s' % (sid, data['room']))
        return get_room_members(sid, data)

    @sio.on('broadcast')
    def room_broadcast(sid, data):
        logger.debug('Client %s broadcasting %s to room %s' % (sid, data['event'], data['room']))
        sio.emit("%s:%s" % (data['room'], data['event']), data.get('data'), room=data['room'], skip_sid=sid)

    @sio.on('leave')
    def leave(sid, data):
        sio.leave_room(sid, data['room'])
        logger.debug('Client %s has left room %s' % (sid, data['room']))

    @sio.on('set')
    def set(sid, data):
        mgr.set_member_info(sid, default_ns, data)
        logger.debug('Client %s has updated its user info: %s' % (sid, data))

    @sio.on('get')
    def get(sid, data):
        return mgr.get_member_info(data['sid'], default_ns)

    return socketio.WSGIApp(sio)


_wsgi_app = None
def wsgi_app(environ, start_response):
    global _wsgi_app
    if not _wsgi_app:
        _wsgi_app = create_app(os.environ.get('SIO_REDIS_URL', 'redis://'),
            os.environ.get('SIO_CHANNEL', 'socketio'), os.environ.get('SIO_SECRET'),
            os.environ.get('SIO_PRESENCE_SESSION_ID'), os.environ.get('SIO_DEBUG', False))
    return _wsgi_app(environ, start_response)


def run_server(port=8888, access_logs=False, reuse_addr=False, presence_session_id=None, **kwargs):
    logger.addHandler(logging.StreamHandler())
    debug = kwargs.get('debug', False)
    if debug:
        logger.setLevel(logging.DEBUG)
        logger.debug('Push server running in DEBUG')

    cleanup_presence_keys = False
    if not presence_session_id:
        presence_session_id = str(uuid.uuid4()).split('-')[0]
        logger.info('Generated random presence session id: %s' % presence_session_id)
        cleanup_presence_keys = True

    kwargs['presence_session_id'] = presence_session_id
    app = create_app(**kwargs)
    socket = eventlet.listen(('', port), reuse_addr=reuse_addr)
    wsgi.server(socket, app, debug=debug, log_output=debug or access_logs)

    if cleanup_presence_keys:
        app.engineio_app.manager.cleanup_presence_keys()


if __name__ == '__main__':
    import argparse
    argparser = argparse.ArgumentParser(prog='frascopush',
        description='Start frasco.push.server')
    argparser.add_argument('-p', '--port', default=8888, type=int,
        help='Port number')
    argparser.add_argument('-r', '--redis-url', default=os.environ.get('SIO_REDIS_URL', 'redis://'), type=str,
        help='Redis URL')
    argparser.add_argument('-c', '--channel', default=os.environ.get('SIO_CHANNEL', 'socketio'), type=str,
        help='Redis channel')
    argparser.add_argument('-s', '--secret', default=os.environ.get('SIO_SECRET'), type=str,
        help='Secret')
    argparser.add_argument('--presence-session-id', default=os.environ.get('SIO_PRESENCE_SESSION_ID'), type=str,
        help='Presence session id (when using multiple servers, use the same presence session id on all instances)')
    argparser.add_argument('--debug', action='store_true', help='Debug mode')
    argparser.add_argument('--access-logs', action='store_true', help='Show access logs in console')
    argparser.add_argument('--reuse-addr', action='store_true', help='Reuse address and port if already bound')
    args = argparser.parse_args()
    run_server(args.port, debug=args.debug, access_logs=args.access_logs,
        redis_url=args.redis_url, channel=args.channel, secret=args.secret,
        presence_session_id=args.presence_session_id, reuse_addr=args.reuse_addr)
