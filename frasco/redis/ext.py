from frasco.ext import *
from redis import StrictRedis
from werkzeug.local import LocalProxy
from .templating import CacheFragmentExtension


class FrascoRedis(Extension):
    name = "frasco_redis"
    defaults = {"url": "redis://localhost:6379/0",
                "fragment_cache_timeout": 3600}

    def _init_app(self, app, state):
        state.connection = StrictRedis.from_url(state.options["url"])
        app.jinja_env.add_extension(CacheFragmentExtension)


def get_current_redis():
    return get_extension_state('frasco_redis').connection

redis = LocalProxy(get_current_redis)
