from flask import g
from frasco.ext import *


class FrascoSubdomains(Extension):
    name = "frasco_subdomains"
    defaults = {"param_name": "subdomain"}

    def _init_app(self, app, state):
        @app.url_value_preprocessor
        def extract_subdomain_from_values(endpoint, values):
            if values:
                g.subdomain = values.pop(state.options["param_name"], None)
        
        @app.url_defaults
        def add_subdomain_to_url_params(endpoint, values):
            if state.options["param_name"] not in values:
                values[state.options["param_name"]] = g.subdomain
