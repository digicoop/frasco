from frasco.ext import *
from flask_cors import CORS
from .service import *


class FrascoApi(Extension):
    name = 'frasco_api'

    def _init_app(self, app, state):
        state.cors = CORS(app, resources={r"/api/*": {"origins": "*"}})
