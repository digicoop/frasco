from frasco.ext import *
from flask_assets import Environment, _webassets_cmd
from flask import Blueprint
from flask.cli import with_appcontext, cli
from flask.signals import Namespace as SignalNamespace
import logging
import click


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

    def _init_app(self, app, state):
        if app.debug:
            app.config.setdefault('ASSETS_AUTO_BUILD', True)
        state.env = Environment(app)
        state.env.debug = app.debug

        @app.cli.command()
        @with_appcontext
        def build_all_assets():
            """Build assets from all extensions."""
            before_build_assets.send()
            _webassets_cmd('build')

        if state.env.config["auto_build"]:
            @app.before_first_request
            def before_request():
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
    app.register_blueprint(AssetsBlueprint(name, import_name))


def register_assets_builder(func=None):
    def decorator(func):
        before_build_assets.connect(lambda sender: func(), weak=False)
        auto_build_assets.connect(lambda sender: func(), weak=False)
    if func:
        return decorator(func)
    return decorator
