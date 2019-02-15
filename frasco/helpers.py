from flask import current_app, url_for as flask_url_for


def url_for(*args, **kwargs):
    if kwargs.get('_external') and current_app.config.get('FORCE_URL_SCHEME'):
        kwargs.setdefault('_scheme', current_app.config['FORCE_URL_SCHEME'])
    return flask_url_for(*args, **kwargs)
