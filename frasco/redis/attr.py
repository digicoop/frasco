from flask import json, current_app
from frasco.ext import get_extension_state
from frasco.utils import unknown_value
from .utils import build_object_key
import inspect


__all__ = ('redis_cached_property', 'redis_cached_property_as_json', 'redis_cached_method', 'redis_cached_method_as_json')


class RedisCachedAttribute(object):
    def __init__(self, func, redis=None, key=None, ttl=None, coerce=None,\
                 serializer=None, name=None):
        self.func = func
        self.__name__ = func.__name__
        self.__doc__ = func.__doc__
        self._redis = redis
        self.key = key
        self.ttl = ttl
        self.coerce = coerce
        self.serializer = serializer
        self.name = name or self.__name__
        self.cached_property_name = self.__name__ + '_cached'
        self.cache_disabled = False
        self.cache_ignore_current = False
        self.cache_current_ttl = None

    @property
    def redis(self):
        return self._redis or get_extension_state('frasco_redis').connection

    def _set_cached_value(self, key, value, default_ttl=None):
        if self.serializer:
            value = self.serializer.dumps(value)
        ttl = self.cache_current_ttl
        if ttl is None:
            ttl = default_ttl
        if value is None:
            value = 'None'
        if ttl is not None:
            self.redis.setex(key, ttl, value)
        else:
            self.redis.set(key, value)

    def _get_cached_value(self, key):
        if not self.redis.exists(key):
            return unknown_value
        value = self.redis.get(key)
        if value is None or value == 'None':
            return None
        if self.serializer:
            value = self.serializer.loads(value)
        if self.coerce:
            value = self.coerce(value)
        return value

    def _call_func(self, obj, *args, **kwargs):
        self.cache_ignore_current = False
        self.cache_current_ttl = self.ttl
        return self.func(obj, *args, **kwargs)


class RedisCachedProperty(RedisCachedAttribute):
    def __init__(self, func, fset=None, fdel=None, **kwargs):
        super(RedisCachedProperty, self).__init__(func, **kwargs)
        self.fset = fset
        self.fdel = fdel

    def __get__(self, obj, cls):
        if obj is None:
            return self
        value = obj.__dict__.get(self.cached_property_name, unknown_value)
        if value is unknown_value:
            key = None
            if not self.cache_disabled:
                try:
                    key = self.build_key(obj)
                    value = self._get_cached_value(key)
                except Exception as e:
                    current_app.log_exception(e)
                    value = unknown_value
            if value is unknown_value:
                value = self.get_fresh(obj)
                if not self.cache_disabled and not self.cache_ignore_current and key:
                    self._set_cached_value(key, value,
                        getattr(obj, '__redis_cache_ttl__', None))
            obj.__dict__[self.cached_property_name] = value
        return value

    def __set__(self, obj, value):
        if self.fset is None:
            raise AttributeError("can't set attribute")
        self.fset(obj, value)
        self.invalidate(obj)

    def __delete__(self, obj):
        if self.fdel is None:
            raise AttributeError("can't delete attribute")
        self.fdel(obj)
        self.invalidate(obj)

    def build_key(self, obj):
        return build_object_key(obj, self.name, self.key)

    def get_cached(self, obj):
        try:
            key = self.build_key(obj)
        except Exception as e:
            current_app.log_exception(e)
            return unknown_value
        return self._get_cached_value(key)

    def get_fresh(self, obj):
        return self._call_func(obj)

    def require_fresh(self, obj):
        obj.__dict__.pop(self.cached_property_name, None)

    def invalidate(self, obj):
        try:
            key = self.build_key(obj)
        except Exception as e:
            current_app.log_exception(e)
            return
        self.redis.delete(key)

    def setter(self, fset):
        self.fset = fset
        return self

    def deleter(self, fdel):
        self.fdel = fdel
        return self


def redis_cached_property(fget=None, **kwargs):
    def decorator(f):
        return RedisCachedProperty(f, **kwargs)
    if fget:
        return decorator(fget)
    return decorator


def redis_cached_property_as_json(fget=None, **kwargs):
    kwargs['serializer'] = json
    return redis_cached_property(fget, **kwargs)


class RedisCachedMethod(RedisCachedAttribute):
    def __get__(self, obj, cls=None):
        self.obj = obj
        return self

    def __call__(self, *args, **kwargs):
        obj = kwargs.pop('__obj__', self.obj)
        value = unknown_value
        if not self.cache_disabled:
            key = None
            try:
                key = self.build_key(args, kwargs, obj)
                value = self._get_cached_value(key)
            except Exception as e:
                current_app.log_exception(e)
                value = unknown_value
        if value is unknown_value:
            value = self._call_func(obj, *args, **kwargs)
            if not self.cache_disabled and not self.cache_ignore_current and key:
                self._set_cached_value(key, value,
                    getattr(self.obj, '__redis_cache_ttl__', None))
        return value

    def cached(self, *args, **kwargs):
        obj = kwargs.pop('__obj__', self.obj)
        try:
            key = self.build_key(args, kwargs, obj)
        except Exception as e:
            current_app.log_exception(e)
            return unknown_value
        return self._get_cached_value(key)

    def fresh(self, *args, **kwargs):
        obj = kwargs.pop('__obj__', self.obj)
        return self._call_func(obj, *args, **kwargs)

    def invalidate(self, *args, **kwargs):
        obj = kwargs.pop('__obj__', self.obj)
        try:
            key = self.build_key(args, kwargs, obj)
        except Exception as e:
            current_app.log_exception(e)
            return
        self.redis.delete(key)

    def build_key(self, args=None, kwargs=None, obj=None):
        if not obj:
            obj = self.obj
        if not args:
            args = []
        if not kwargs:
            kwargs = {}
        at_values = inspect.getcallargs(self.func, obj, *args, **kwargs)
        return build_object_key(obj, self.name, self.key, at_values)


def redis_cached_method(func=None, **kwargs):
    def decorator(f):
        return RedisCachedMethod(f, **kwargs)
    if func:
        return decorator(func)
    return decorator


def redis_cached_method_as_json(func=None, **kwargs):
    kwargs['serializer'] = json
    return redis_cached_method(func, **kwargs)
