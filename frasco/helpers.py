from flask import current_app, url_for as flask_url_for, Markup, request
import functools


def url_for(*args, **kwargs):
    if kwargs.get('_external') and current_app.config.get('FORCE_URL_SCHEME'):
        kwargs.setdefault('_scheme', current_app.config['FORCE_URL_SCHEME'])
    return flask_url_for(*args, **kwargs)


def url_for_static(filename, **kwargs):
    """Shortcut function for url_for('static', filename=filename)
    """
    return url_for('static', filename=filename, **kwargs)


def url_for_same(**overrides):
    return url_for(request.endpoint, **dict(dict(request.args,
        **request.view_args), **overrides))


def get_remote_addr():
    if current_app.debug and "__remoteaddr" in request.values:
        return request.values["__remoteaddr"]
    return request.remote_addr


def wrap_in_markup(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        return Markup(f(*args, **kwargs))
    return wrapper


def inject_app_config(app, config, prefix=None):
    for k, v in config.items():
        if prefix:
            k = "%s%s" % (prefix, k)
        app.config[k.upper()] = v
