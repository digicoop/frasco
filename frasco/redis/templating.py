from flask import current_app
from frasco.templating import jinja_fragment_extension
from frasco.ext import get_extension_state


@jinja_fragment_extension("cache")
def CacheFragmentExtension(caller=None, key=None, timeout=None):
    state = get_extension_state('frasco_redis')
    rv = state.connection.get(key)
    if rv is None:
        timeout = timeout or state.options["fragment_cache_timeout"]
        rv = caller()
        state.connection.setex(key, timeout, rv)
    return rv
