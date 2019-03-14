import socketio
import os
import urlparse
import uuid
import json
from itsdangerous import URLSafeTimedSerializer, BadSignature
from eventlet import wsgi
import eventlet
import logging


eventlet.sleep()
eventlet.monkey_patch()


logger = logging.getLogger('frasco.push.server')


class PresenceRedisManager(socketio.RedisManager):
    def __init__(self, *args, **kwargs):
        self.presence_session_id = kwargs.pop('presence_session_id', str(uuid.uuid4()).split('-')[-1])
        self.presence_key_prefix = "presence%s:" % self.presence_session_id
        super(PresenceRedisManager, self).__init__(*args, **kwargs)

    def enter_room(self, sid, namespace, room):
        super(PresenceRedisManager, self).enter_room(sid, namespace, room)
        if room and room != sid:
            self.redis.sadd("%s%s:%s" % (self.presence_key_prefix, namespace, room), sid)
            self.server.emit('%s:joined' % room, {"sid": sid, "info": self.get_member_info(sid, namespace)},
                room=room, skip_sid=sid)

    def leave_room(self, sid, namespace, room):
        super(PresenceRedisManager, self).leave_room(sid, namespace, room)
        if room and room != sid:
            self.redis.srem("%s%s:%s" % (self.presence_key_prefix, namespace, room), sid)
            self.server.emit('%s:left' % room, sid, room=room, skip_sid=sid)

    def get_room_members(self, namespace, room):
        return self.redis.smembers("%s%s:%s" % (self.presence_key_prefix, namespace, room))

    def set_member_info(self, sid, namespace, info):
        self.redis.set("%s%s@%s" % (self.presence_key_prefix, namespace, sid), json.dumps(info))
        for room in self.get_rooms(sid, namespace):
            if not room or room == sid:
                continue
            self.server.emit('%s:member_updated' % room, {"sid": sid, "info": info}, room=room, skip_sid=sid)

    def get_member_info(self, sid, namespace):
        data = self.redis.get("%s%s@%s" % (self.presence_key_prefix, namespace, sid))
        if data:
            try:
                return json.loads(data)
            except:
                pass
        return {}

    def disconnect(self, sid, namespace):
        super(PresenceRedisManager, self).disconnect(sid, namespace)
        self.redis.delete("%s%s@%s" % (self.presence_key_prefix, namespace, sid))

    def cleanup_presence_keys(self):
        keys = self.redis.keys('%s*' % self.presence_key_prefix)
        pipe = self.redis.pipeline()
        for key in keys:
            pipe.delete(key)
        pipe.execute()


def create_app(redis_url='redis://', channel='socketio', secret=None, token_max_age=None):
    mgr = PresenceRedisManager(redis_url, channel=channel)
    sio = socketio.Server(client_manager=mgr, async_mode='eventlet')
    token_serializer = URLSafeTimedSerializer(secret)
    default_ns = '/'

    @sio.on('connect')
    def connect(sid, env):
        if not secret:
            return
        try:
            qs = urlparse.parse_qs(env['QUERY_STRING'])
            if not 'token' in qs:
                return False
            user_info, allowed_rooms = token_serializer.loads(qs['token'][0], max_age=token_max_age)
            env['allowed_rooms'] = allowed_rooms
            if user_info:
                mgr.set_member_info(sid, default_ns, user_info)
            logger.debug('New client connection: %s ; %s' % (sid, user_info))
        except BadSignature:
            logger.debug('Client provided an invalid token')
            return False

    @sio.on('members')
    def get_room_members(sid, data):
        if not data.get('room') or data['room'] not in mgr.get_rooms(sid, default_ns):
            return []
        return {sid: mgr.get_member_info(sid, default_ns) for sid in mgr.get_room_members(default_ns, data['room'])}

    @sio.on('join')
    def join(sid, data):
        if sio.environ[sid].get('allowed_rooms') and data['room'] not in sio.environ[sid]['allowed_rooms']:
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


def _get_env_var(wsgi_env, name, default=None):
    return wsgi_env.get(name, os.environ.get(name, default))


_wsgi_app = None
def wsgi_app(environ, start_response):
    global _wsgi_app
    if not _wsgi_app:
        _wsgi_app = create_app(_get_env_var(environ, 'SIO_REDIS_URL', 'redis://'),
            _get_env_var(environ, 'SIO_CHANNEL', 'socketio'), _get_env_var(environ, 'SIO_SECRET'))
    return _wsgi_app(environ, start_response)


def cleanup_wsgi_app():
    if _wsgi_app:
        _wsgi_app.engineio_app.manager.cleanup_presence_keys()


def run_server(port=8888, debug=False, log_output=False, **kwargs):
    logger.addHandler(logging.StreamHandler())
    if debug:
        logger.setLevel(logging.DEBUG)
        logger.debug('Push server running in DEBUG')
    env = dict([("SIO_%s" % k.upper(), v) for k, v in kwargs.items()])
    wsgi.server(eventlet.listen(('', port)), wsgi_app, environ=env, debug=debug, log_output=debug or log_output)
    cleanup_wsgi_app()


if __name__ == '__main__':
    import argparse
    argparser = argparse.ArgumentParser(prog='frascopush',
        description='Start frasco.push.server')
    argparser.add_argument('-p', '--port', default=8888, type=int,
        help='Port number')
    argparser.add_argument('-r', '--redis-url', default=os.environ.get('SIO_REDIS_URL', 'redis://'), type=str,
        help='Redis URL')
    argparser.add_argument('-c', '--channel', default=os.environ.get('SIO_CHANNEL', 'socketio'), type=str,
        help='Channel')
    argparser.add_argument('-s', '--secret', default=os.environ.get('SIO_SECRET'), type=str,
        help='Secret')
    argparser.add_argument('--debug', action='store_true', help='Debug mode')
    argparser.add_argument('--access-logs', action='store_true', help='Show access logs in console')
    args = argparser.parse_args()
    run_server(args.port, debug=args.debug, log_output=args.access_logs,
        redis_url=args.redis_url, channel=args.channel, secret=args.secret)
