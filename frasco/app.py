from flask import Flask
from flask.ctx import has_request_context
from frasco.config import Config
from frasco.utils import JSONEncoder, AttrDict
from frasco.templating import configure_environment
from werkzeug.contrib.fixers import ProxyFix
import os
import sys


class Frasco(Flask):
    config_class = Config
    json_encoder = JSONEncoder

    def __init__(self, import_name, **kwargs):
        super(Frasco, self).__init__(import_name, **kwargs)
        self.extensions = AttrDict()
        self.wsgi_app = ProxyFix(self.wsgi_app)

    def log_exception(self, exc_info):
        if not isinstance(exc_info, tuple):
            exc_info = sys.exc_info()
        if has_request_context():
            super(Frasco, self).log_exception(exc_info)
        else:
            self.logger.error('Exception [outside of request context]', exc_info=exc_info)

    def create_jinja_environment(self):
        env = super(Frasco, self).create_jinja_environment()
        env.globals.update(app=self)
        configure_environment(env)
        macro_file = os.path.join(self.root_path, "macros.html")
        if os.path.exists(macro_file):
            env.macros.register_file(macro_file)
        macro_dir = os.path.join(self.root_path, "macros")
        if os.path.exists(macro_dir):
            env.macros.register_directory(macro_dir)
        return env
