from flask import current_app, json
from frasco.utils import unknown_value
import re
import functools
import inspect
import logging


__all__ = ('redis_get_set', 'redis_get_set_as_json', 'build_object_key', 'redis_cached_function', 'redis_cached_function_as_json')


logger = logging.getLogger('frasco.redis')


def redis_get_set(key, callback, ttl=None, coerce=None, serializer=None, redis=None, logging=False):
    if not redis:
        redis = current_app.extensions.frasco_redis.connection
    value = redis.get(key)
    if value is not None:
        if logging or (logging is None and current_app.debug):
            logger.debug('CACHE HIT: %s' % key)
        if value == 'None':
            return None
        if coerce:
            return coerce(value)
        return value
    if logging or (logging is None and current_app.debug):
        logger.debug('CACHE MISS: %s' % key)
    _value = value = callback()
    if serializer:
        _value = serializer(value)
    if _value is None:
        _value = 'None'
    if ttl:
        redis.setex(key, ttl, _value)
    else:
        redis.set(key, _value)
    return value


def redis_get_set_as_json(key, callback, **kwargs):
    kwargs['serializer'] = json.dumps
    kwargs['coerce'] = json.loads
    return redis_get_set(key, callback, **kwargs)


def build_object_key(obj=None, name=None, key=None, at_values=None, values=None, super_key=None):
    cls = None
    if obj:
        super_key = getattr(obj, '__redis_cache_key__', None)
        if inspect.isclass(obj):
            cls = obj
        else:
            cls = obj.__class__
    elif not key:
        raise ValueError('obj or key is needed for build_object_key()')

    if key and '{__super__}' in key and super_key is not None:
        key = key.replace('{__super__}', super_key)
    elif not key and super_key:
        key = super_key
    elif not key:
        key = '%s:{__name__}' % cls.__name__
    if name is None and cls:
        name = cls.__name__
    if values is None:
        values = {}
    else:
        values = dict(**values)

    for attr in re.findall(r'\{(@?[a-z0-9_]+)[^}]*\}', key, re.I):
        value = unknown_value
        if attr == '__name__' and name is not None:
            value = name
        elif attr.startswith('@') and at_values:
            value = at_values.get(attr[1:], '')
        elif obj:
            value = getattr(obj, attr)
        if value is not unknown_value:
            cache_id = getattr(value, '__redis_cache_id__', None)
            if cache_id:
                value = cache_id()
            values[attr] = value
    return key.format(**values)


def redis_cached_function(key, **opts):
    opts.setdefault('logging', None)
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if callable(key):
                k = key(*args, **kwargs)
            else:
                k = build_object_key(None, func.__name__, key, values=inspect.getcallargs(func, *args, **kwargs))
            return redis_get_set(k, lambda: func(*args, **kwargs), **opts)
        return wrapper
    return decorator


def redis_cached_function_as_json(key, **opts):
    opts['serializer'] = json.dumps
    opts['coerce'] = json.loads
    return redis_cached_function(key, **opts)
