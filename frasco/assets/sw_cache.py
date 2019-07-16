from frasco.ext import require_extension, get_extension_state
from flask import current_app
import os
import json


def generate_cache_service_worker(cache_name, assets, dynamic_urls=None, template_filename=None,
                            offline_fallback=None, offline_fallback_ignore_paths=None):
    if not template_filename:
        template_filename = os.path.join(os.path.dirname(__file__), 'service-worker.js')

    files = []
    for asset_name in assets:
        if asset_name.startswith('@'):
            files.extend(current_app.extensions.frasco_assets.env[asset_name[1:]].urls())
        else:
            files.append(asset_name)

    sw = "\n".join([
        'const CACHE_NAME = "%s";' % cache_name,
        'const CACHE_DOMAIN = "%s";' % current_app.config['SERVER_NAME'],
        'const CACHE_FILES = %s;' % json.dumps(files),
        'const CACHE_DYNAMIC_URLS = %s' % json.dumps(dynamic_urls or []),
        'const CACHE_OFFLINE_FALLBACK = "%s";' % offline_fallback,
        'const CACHE_OFFLINE_FALLBACK_IGNORE_PATHS = %s;' % json.dumps(offline_fallback_ignore_paths or [])
    ])
    
    with open(template_filename) as f:
        sw += f.read()

    return sw


def generate_cache_service_worker_response(*args, **kwargs):
    headers = {'Content-type': 'text/javascript', 'Cache-control': 'no-cache', 'Expires': '0'}
    return generate_cache_service_worker(*args, **kwargs), headers


def create_cache_service_worker_route(app, *args, **kwargs):
    require_extension('frasco_assets', app)

    @app.route(app.config.get('CACHE_SERVICE_WORKER_URL', '/cache-sw.js'))
    def cache_worker():
        state = get_extension_state('frasco_assets')
        sw = getattr(state, 'cache_service_worker', None)
        if not sw:
            sw = generate_cache_service_worker_response(*args, **kwargs)
            setattr(state, 'cache_service_worker', sw)
        return sw
