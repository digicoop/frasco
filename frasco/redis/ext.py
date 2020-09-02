from frasco.ext import *
from redis import Redis
from werkzeug.local import LocalProxy
from .templating import CacheFragmentExtension


class FrascoRedis(Extension):
    name = "frasco_redis"
    defaults = {"url": "redis://localhost:6379/0",
                "fragment_cache_timeout": 3600,
                "decode_responses": True,
                "encoding": "utf-8"}

    def _init_app(self, app, state):
        state.connection = Redis.from_url(state.options["url"],
            decode_responses=state.options["decode_responses"],
            encoding=state.options["encoding"])
        app.jinja_env.add_extension(CacheFragmentExtension)


def get_current_redis():
    return get_extension_state('frasco_redis').connection

redis = LocalProxy(get_current_redis)
