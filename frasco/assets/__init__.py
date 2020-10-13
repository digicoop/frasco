from frasco.ext import *
from flask_assets import Environment, _webassets_cmd
from flask import Blueprint, current_app
from flask.cli import with_appcontext, cli
from flask.signals import Namespace as SignalNamespace
import logging
import click
import os
import shutil


_signals = SignalNamespace()
before_build_assets = _signals.signal('before_build_assets')
after_clean_assets = _signals.signal('before_clean_assets')
auto_build_assets = _signals.signal('auto_build_assets')


class FrascoAssetsState(ExtensionState):
    def register(self, *args, **kwargs):
        return self.env.register(*args, **kwargs)


class FrascoAssets(Extension):
    name = 'frasco_assets'
    state_class = FrascoAssetsState
    prefix_extra_options = 'ASSETS_'
    defaults = {'js_packages_path': {},
                'copy_files_from_js_packages': {}}

    def _init_app(self, app, state):
        state.env = Environment(app)
        state.env.debug = app.debug
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
