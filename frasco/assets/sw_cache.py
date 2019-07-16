import os
import json


def create_cache_service_worker_route(app, cache_name, assets, template_filename=None,
                                      offline_fallback=None, offline_fallback_ignore_paths=None):
    if not template_filename:
        template_filename = os.path.join(os.path.dirname(__file__), 'service-worker.js')

    files = []
    for asset_name in assets:
        if asset_name.startswith('@'):
            files.extend(app.extensions.frasco_assets.env[asset_name[1:]].urls())
        else:
            files.append(asset_name)

    sw = "\n".join([
        'const CACHE_NAME = "%s";' % cache_name,
        'const CACHE_DOMAIN = "%s";' % app.config['SERVER_NAME'],
        'const CACHE_FILES = %s;' % json.dumps(files),
        'const CACHE_OFFLINE_FALLBACK = "%s";' % offline_fallback,
        'const CACHE_OFFLINE_FALLBACK_IGNORE_PATHS = %s;' % json.dumps(offline_fallback_ignore_paths or [])
    ])
    with open(template_filename) as f:
        sw += f.read()

    @app.route(app.config.get('CACHE_SERVICE_WORKER_URL', '/cache-sw.js'))
    def cache_worker():
        return sw, {'Content-type': 'text/javascript',
            'Cache-control': 'no-cache', 'Expires': '0'}
