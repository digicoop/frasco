from frasco.ext import *
from flask_assets import Environment as BaseEnvironment, FlaskResolver, _webassets_cmd
from flask import Blueprint, current_app, _request_ctx_stack, has_request_context
from flask.cli import with_appcontext, cli
from flask.signals import Namespace as SignalNamespace
from ..helpers import url_for as frasco_url_for
import logging
import click
import os
import shutil


_signals = SignalNamespace()
before_build_assets = _signals.signal('before_build_assets')
after_clean_assets = _signals.signal('before_clean_assets')
auto_build_assets = _signals.signal('auto_build_assets')


class Resolver(FlaskResolver):
    """We override the convert_item_to_flask_url() to use our own url_for()"""
    def convert_item_to_flask_url(self, ctx, item, filepath=None):
        directory, rel_path, endpoint = self.split_prefix(ctx, item)

        if filepath is not None:
            filename = filepath[len(directory)+1:]
        else:
            filename = rel_path

        flask_ctx = None
        if not _request_ctx_stack.top:
            flask_ctx = ctx.environment._app.test_request_context()
            flask_ctx.push()
        try:
            url = cdn_url_for(endpoint, filename=filename)
            if url and url.startswith('http:'):
                url = url[5:]
            return url
        finally:
            if flask_ctx:
                flask_ctx.pop()


class Environment(BaseEnvironment):
    resolver_class = Resolver


class FrascoAssetsState(ExtensionState):
    def register(self, *args, **kwargs):
        return self.env.register(*args, **kwargs)


class FrascoAssets(Extension):
    name = 'frasco_assets'
    state_class = FrascoAssetsState
    prefix_extra_options = 'ASSETS_'
    defaults = {'js_packages_path': {},
                'copy_files_from_js_packages': {},
                'cdn_scheme': 'https',
                'cdn_endpoints': ['static']}

    def _init_app(self, app, state):
        state.env = Environment(app)
        state.env.debug = app.debug
        app.jinja_env.globals['url_for'] = cdn_url_for
        app.jinja_env.globals['url_for_static'] = cdn_url_for_static
        app.jinja_env.macros.register_file(os.path.join(os.path.dirname(__file__), "macros.html"), alias="frasco_assets.html")

        if state.options['copy_files_from_js_packages']:
            register_assets_builder(lambda: copy_files_from_js_packages(state.options['copy_files_from_js_packages']))

        @app.cli.command()
        @with_appcontext
        def build_all_assets():
            """Build assets from all extensions."""
            if state.options['js_packages_path']:
                register_js_packages_blueprint(app, state.options['js_packages_path'])
            before_build_assets.send()
            _webassets_cmd('build')

        if state.options['js_packages_path'] and (state.env.config["auto_build"] or app.debug):
            register_js_packages_blueprint(app, state.options['js_packages_path'])

        if state.env.config["auto_build"]:
            @app.before_first_request
            def before_first_request():
                auto_build_assets.send(self)

    @ext_stateful_method
    def register(self, state, *args, **kwargs):
        return state.register(*args, **kwargs)


class AssetsBlueprint(Blueprint):
    def __init__(self, name, import_name, **kwargs):
        kwargs.setdefault('static_url_path', '/static/vendor/%s' % name)
        kwargs.setdefault('static_folder', 'static')
        super(AssetsBlueprint, self).__init__(name, import_name, **kwargs)


def expose_package(app, name, import_name):
    bp = AssetsBlueprint(name, import_name)
    app.register_blueprint(bp)
    return bp


def register_assets_builder(func=None):
    def decorator(func):
        before_build_assets.connect(lambda sender: func(), weak=False)
        auto_build_assets.connect(lambda sender: func(), weak=False)
    if func:
        return decorator(func)
    return decorator


def register_js_packages_blueprint(app, js_packages_path):
    for name, path in js_packages_path.items():
        if name not in app.blueprints:
            bp = Blueprint(name, __name__, static_folder=os.path.abspath(path), static_url_path='/static/%s' % name)
            app.register_blueprint(bp)


def copy_files_from_js_packages(files):
    state = get_extension_state('frasco_assets')
    packages = state.options['js_packages_path']
    logger = logging.getLogger('frasco.assets')
    for src, dest in files.items():
        package, filename = src.split('/', 1)
        filename = os.path.join(packages.get(package, current_app.root_path), filename)
        if not os.path.exists(src):
            logger.warning("Cannot copy file from js packages: %s" % src)
            continue
        target = os.path.join(current_app.static_folder, dest)
        if os.path.isdir(filename) and os.path.exists(target):
            if dest.endswith('/'):
                target = os.path.join(target, os.path.basename(filename))
            else:
                logger.debug("Removing target of js package file copy: %s" % target)
                if os.path.isdir(target):
                    shutil.rmtree(target)
                else:
                    os.unlink(target)
        logger.debug("Copying js package file from '%s' to '%s'" % (filename, target))
        if os.path.isdir(filename):
            shutil.copytree(filename, target)
        else:
            if not os.path.exists(os.path.dirname(target)):
                os.makedirs(os.path.dirname(target))
            shutil.copyfile(filename, target)


def cdn_url_for(endpoint, **values):
    state = get_extension_state('frasco_assets', app=values.pop('_app', None))
    if state.options.get('cdn_domain') and is_cdn_endpoint(endpoint):
        try:
            scheme = values.pop('_scheme')
        except KeyError:
            scheme = state.options['cdn_scheme']
        urls = current_app.url_map.bind(state.options['cdn_domain'], url_scheme=scheme)
        return urls.build(endpoint, values=values, force_external=True)

    return frasco_url_for(endpoint, **values)


def cdn_url_for_static(filename, **kwargs):
    """Shortcut function for url_for('static', filename=filename)
    """
    return cdn_url_for('static', filename=filename, **kwargs)


def is_cdn_endpoint(endpoint):
    cdn_endpoints = get_extension_state('frasco_assets').options['cdn_endpoints']
    if endpoint in cdn_endpoints:
        return True
    for x in cdn_endpoints:
        if endpoint.endswith('.%s' % x):
            return True
    return False
