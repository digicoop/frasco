from flask import g
from frasco.ext import *
from frasco.i18n import set_translation_callbacks
from flask_babel import (Babel, gettext, ngettext, lazy_gettext, format_datetime, format_date,
                         format_time, format_currency as babel_format_currency)
from babel import Locale

from .cli import babel_cli
from .ctx import *
from .user import update_user_with_locale


class FrascoBabelState(ExtensionState):
    def __init__(self, *args):
        super(FrascoBabelState, self).__init__(*args)
        self.extract_dirs = []
        self.babel = None
    
    def add_extract_dir(self, path, jinja_dirs=None, jinja_exts=None, extractors=None):
        jinja_exts = jinja_exts or []
        jinja_exts.extend(self.options["extract_with_jinja_exts"])
        self.extract_dirs.append((path, jinja_dirs, jinja_exts, extractors))


class FrascoBabel(Extension):
    name = "frasco_babel"
    state_class = FrascoBabelState
    prefix_extra_options = "BABEL_"
    defaults = {"locales": ["en"],
                "default_locale": "en",
                "currencies": ["USD"],
                "default_currency": "USD",
                "currency_name_format": u"{name} ({symbol})",
                "store_locale_in_session": True,
                "store_locale_in_user": False,
                "user_locale_column": "locale",
                "user_timezone_column": "timezone",
                "user_currency_column": "currency",
                "extract_locale_from_headers": True,
                "extract_locale_from_request": False,
                "always_add_locale_to_urls": True,
                "store_request_locale_in_session": False,
                "request_arg": "locale",
                "extractors": [],
                "extract_keywords": [],
                "extract_jinja_dirs": ["templates", "emails"],
                "extract_with_jinja_exts": ["jinja2.ext.autoescape", "jinja2.ext.with_",
                    "jinja2.ext.do", "jinja_layout.LayoutExtension", "jinja_macro_tags.LoadMacroExtension",
                    "jinja_macro_tags.CallMacroTagExtension", "jinja_macro_tags.JinjaMacroTagsExtension",
                    "jinja_macro_tags.HtmlMacroTagsExtension", "frasco.templating.FlashMessagesExtension"],
                "request_locale_arg_ignore_endpoints": ["static", "static_upload"],
                "compile_to_json": False,
                "compile_to_js": False,
                "js_catalog_varname": "LOCALE_%s_CATALOG",
                "babel_bin": "pybabel"}


    def _init_app(self, app, state):
        state.options.locales = set(state.options.locales)
        
        state.babel = Babel(app)
        state.babel.default_currency = state.options["default_currency"]
        state.babel.localeselector(detect_locale)
        state.babel.timezoneselector(detect_timezone)
        state.babel.currency_selector_func = detect_currency

        app.cli.add_command(babel_cli)

        set_translation_callbacks(translate=gettext,
                                  ntranslate=ngettext,
                                  lazy_translate=lazy_gettext,
                                  format_datetime=format_datetime,
                                  format_date=format_date,
                                  format_time=format_time)

        from frasco.users.signals import user_signed_up
        user_signed_up.connect(lambda _, user: update_user_with_locale(user), weak=False)

        @app.url_value_preprocessor
        def extract_locale_from_values(endpoint, values):
            if state.options["extract_locale_from_request"] and values:
                values.pop(state.options["request_arg"], None)
        
        @app.url_defaults
        def add_locale_to_url_params(endpoint, values):
            if endpoint not in state.options["request_locale_arg_ignore_endpoints"] and \
              state.options["extract_locale_from_request"] and state.options['always_add_locale_to_urls'] and \
              state.options["request_arg"] not in values:
                values[state.options["request_arg"]] = get_locale().language

        @app.before_request
        def before_request():
            locale = get_locale()
            currency = get_currency()
            g.current_locale = locale.language
            g.current_timezone = get_timezone().zone
            g.current_currency = currency
            g.current_language = locale.display_name
            g.current_currency_name = state.options["currency_name_format"].format(
                code=currency,
                name=locale.currencies[currency],
                symbol=locale.currency_symbols[currency])

        app.jinja_env.globals.update(translate=gettext, ntranslate=ngettext, _=gettext,
            available_currencies=available_currencies, available_locales=available_locales)
        app.jinja_env.filters.update(datetimeformat=format_datetime, dateformat=format_date,
            timeformat=format_time, currencyformat=format_currency)


def format_currency(number, format=None):
    return babel_format_currency(number, get_currency(), format)


def available_locales(english_name=False):
    locales = []
    for language in get_extension_state('frasco_babel').options["locales"]:
        locale = Locale(language)
        name = locale.english_name if english_name else locale.display_name
        locales.append((language, name))
    return locales


def available_currencies():
    currencies = []
    locale = get_locale()
    for currency in get_extension_state('frasco_babel').options["currencies"]:
        currencies.append((currency, locale.currencies[currency], locale.currency_symbols[currency]))
    return currencies
