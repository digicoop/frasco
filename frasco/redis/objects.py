from flask import json
from frasco.ext import get_extension_state
from .ext import redis as current_app_redis


__all__ = ('PartialObject', 'RedisHash', 'JSONRedisHash', 'RedisList', 'JSONRedisList', 'RedisSet', 'JSONRedisSet')


class PartialObject(object):
    def __init__(self, loader, cached_attrs=None):
        object.__setattr__(self, '_loader', loader)
        object.__setattr__(self, "_obj", None)
        object.__setattr__(self, "_cached_attrs", dict(cached_attrs or {}))

    def _load(self):
        if not self._obj:
            object.__setattr__(self, "_obj", self.loader())
        return self._obj

    def __getattr__(self, name):
        if name in self._cached_attrs:
            return self._cached_attrs[name]
        return getattr(self._load(), name)

    def __setattr__(self, name, value):
        if name in self._cached_attrs:
            del self._cached_attrs[name]
        setattr(self._load(), name, value)


class RedisObject(object):
    def __init__(self, key, serializer=None, coerce=None, redis=None):
        self.key = key
        self.serializer = serializer
        self.coerce = coerce
        self.redis = redis or current_app_redis

    def _to_redis(self, value):
        if self.serializer:
            return self.serializer.dumps(value)
        return value

    def _from_redis(self, value):
        if value is None:
            return value
        if self.serializer:
            value = self.serializer.loads(value)
        if self.coerce:
            value = self.coerce(value)
        return value

    def clear(self):
        self.redis.delete(self.key)

    def expire(self, ttl):
        self.redis.expire(self.key, ttl)


class RedisHash(RedisObject):
    def __setitem__(self, key, value):
        self.redis.hset(self.key, key, self._to_redis(value))

    def __getitem__(self, key):
        return self.get(key)

    def __delitem__(self, key):
        return self.redis.hdel(self.key, key)

    def __contains__(self, key):
        return key in self.keys()

    def get(self, key):
        return self._from_redis(self.redis.hget(self.key, key))

    def keys(self):
        return self.redis.hkeys(self.key)

    def items(self):
        return {k: self._from_redis(v) for k, v in self.redis.hgetall(self.key).items()}

    def values(self):
        return list(self.items().values())

    def update(self, dct):
        pipe = self.redis.pipeline()
        for k, v in dct.items():
            pipe.hset(self.key, k, self._to_redis(v))
        pipe.execute()


class JSONRedisHash(RedisHash):
    def __init__(self, key, **kwargs):
        kwargs['serializer'] = json
        super(JSONRedisHash, self).__init__(key, **kwargs)


class RedisList(RedisObject):
    def __setitem__(self, index, value):
        self.redis.lset(self.key, index, self._to_redis(value))

    def __getitem__(self, index):
        if isinstance(index, slice):
            if slice.step is not None:
                return [self[i] for i in range(*index.indices(len(self)))]
            return [self._from_redis(v) for v in \
                self.redis.lrange(self.key, slice.start or 0, slice.stop or -1)]
        elif isinstance(index, int):
            return self._from_redis(self.redis.lindex(self.key, index))
        else:
            raise TypeError("Invalid argument type.")

    def __len__(self):
        return self.redis.llen(self.key)

    def __iter__(self):
        for value in self.redis.lrange(self.key, 0, -1):
            yield self._from_redis(value)

    def __contains__(self, value):
        return value in list(self)

    def append(self, value):
        self.redis.rpush(self.key, self._to_redis(value))

    def extend(self, lst):
        pipe = self.redis.pipeline()
        for v in lst:
            pipe.rpush(self.key, self._to_redis(v))
        pipe.execute()

    def remove(self, value):
        self.redis.lrem(self.key, 1, self._to_redis(value))


class JSONRedisList(RedisList):
    def __init__(self, key, **kwargs):
        kwargs['serializer'] = json
        super(JSONRedisList, self).__init__(key, **kwargs)


class RedisSet(RedisObject):
    def __iter__(self):
        for value in self.redis.smembers(self.key):
            yield self._from_redis(value)

    def __contains__(self, value):
        return self.redis.ismember(self.key, value)

    def add(self, value):
        self.redis.sadd(self.key, self._to_redis(value))

    def update(self, lst):
        pipe = self.redis.pipeline()
        for v in lst:
            pipe.sadd(self.key, self._to_redis(v))
        pipe.execute()

    def remove(self, value):
        self.redis.srem(self.key, self._to_redis(value))

    def pop(self):
        return self._from_redis(self.redis.spop(self.key))

    def move(self, destination, value):
        if isinstance(destination, RedisSet):
            destination = destination.key
        self.redis.smove(self.key, self.destination, self._to_redis(value))

    def diff(self, *other_keys):
        return self._cmp('sdiff', other_keys)

    def inter(self, *other_keys):
        return self._cmp('sinter', other_keys)

    def union(self, *other_keys):
        return self._cmp('union', other_keys)

    def _cmp(self, op, other_keys):
        keys = []
        for k in other_keys:
            if isinstance(k, RedisSet):
                keys.append(k.key)
            else:
                keys.append(k)
        for value in getattr(self.redis, op)(self.key, *keys):
            yield self._from_redis(value)


class JSONRedisSet(RedisSet):
    def __init__(self, key, **kwargs):
        kwargs['serializer'] = json
        super(JSONRedisSet, self).__init__(key, **kwargs)
