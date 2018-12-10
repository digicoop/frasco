from frasco.ext import get_extension_state
import sqlalchemy as sqla

from .ctx import get_locale, get_timezone, get_currency


class BabelUserModelMixin(object):
    locale = sqla.Column(sqla.String)
    timezone = sqla.Column(sqla.String)
    currency = sqla.Column(sqla.String)


def update_user_with_locale(user):
    state = get_extension_state('frasco_babel')
    setattr(user, state.options["user_locale_column"], get_locale().language)
    setattr(user, state.options["user_timezone_column"], get_timezone().zone)
    setattr(user, state.options["user_currency_column"], get_currency())
