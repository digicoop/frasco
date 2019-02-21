from flask import current_app, has_request_context, request, session, _request_ctx_stack
from frasco.ext import get_extension_state, has_extension
from frasco.users import is_user_logged_in, current_user
from flask_babel import get_locale, get_timezone, refresh as refresh_babel


__all__ = ('get_locale', 'get_timezone', 'get_currency',
           'detect_locale', 'detect_timezone', 'detect_currency',
           'set_locale', 'set_timezone', 'set_currency')


_DEFAULT_CURRENCY = "USD"


def get_currency():
    """Returns the timezone that should be used for this request as
    `pytz.timezone` object.  This returns `None` if used outside of
    a request. If flask-babel was not attached to application, will
    return UTC timezone object.
    """
    ctx = _request_ctx_stack.top if has_request_context() else None
    currency = None
    babel = None
    if ctx:
        currency = getattr(ctx, 'babel_currency', None)
        babel = ctx.app.extensions.get('babel')

    if currency is None:
        if babel is None:
            currency = _DEFAULT_CURRENCY
        else:
            if getattr(babel, "currency_selector_func") is None:
                currency = babel.default_currency
            else:
                currency = babel.currency_selector_func()
                if currency is None:
                    currency = babel.default_currency
        if ctx:
            ctx.babel_currency = currency

    return currency


def _user_has_locale():
    return get_extension_state('frasco_babel').options["store_locale_in_user"] \
        and has_extension('frasco_users') and is_user_logged_in()


def detect_locale():
    state = get_extension_state('frasco_babel')
    if has_request_context() and state.options["extract_locale_from_request"]:
        if state.options["request_arg"] in request.args:
            locale = request.args[state.options["request_arg"]]
            if locale not in state.options["locales"]:
                return
            if state.options["store_request_locale_in_session"]:
                session["locale"] = locale
            return locale
    if _user_has_locale():
        locale = getattr(current_user, state.options["user_locale_column"], None)
        if locale:
            return locale
    if not has_request_context():
        return
    if state.options["store_locale_in_session"] and "locale" in session:
        return session["locale"]
    if state.options['extract_locale_from_headers']:
        return request.accept_languages.best_match(state.options["locales"])


def detect_timezone():
    state = get_extension_state('frasco_babel')
    if _user_has_locale():
        tz = getattr(current_user, state.options["user_timezone_column"], None)
        if tz:
            return tz
    if not has_request_context():
        return
    if state.options["store_locale_in_session"] and "timezone" in session:
        return session["timezone"]


def detect_currency():
    state = get_extension_state('frasco_babel')
    if _user_has_locale():
        currency = getattr(current_user, state.options["user_currency_column"], None)
        if currency:
            return currency
    if not has_request_context():
        return
    if state.options["store_locale_in_session"] and "currency" in session:
        return session["currency"]
    

def set_locale(locale, refresh=False):
    state = get_extension_state('frasco_babel')
    if _user_has_locale():
        setattr(current_user, state.options["user_locale_column"], locale)
        return
    if state.options["store_locale_in_session"]:
        session["locale"] = locale
    if refresh:
        refresh_babel()


def set_timezone(tz):
    state = get_extension_state('frasco_babel')
    if _user_has_locale():
        setattr(current_user, state.options["user_timezone_column"], tz)
        return
    if state.options["store_locale_in_session"]:
        session["timezone"] = tz


def set_currency(currency):
    state = get_extension_state('frasco_babel')
    if _user_has_locale():
        setattr(current_user, state.options["user_currency_column"], currency)
        return
    if state.options["store_locale_in_session"]:
        session["currency"] = currency
