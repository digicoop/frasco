from frasco import request_param
from frasco.api import ApiService, ApiInputError, ApiNotFoundError
import data


eu_vat_service = ApiService('eu_vat', url_prefix='/eu-vat')


@eu_vat_service.route('/rates/<country_code>')
@request_param('country_code', type=str)
def get_vat_rate(country_code):
    try:
        return data.get_vat_rate(country_code)
    except data.EUVATError as e:
        raise ApiInputError(unicode(e))


@eu_vat_service.route('/validate-vat-number', methods=['POST'])
@request_param('vat_number', type=str)
def validate_vat_number(vat_number):
    try:
        return data.validate_vat_number(vat_number, invalid_format_raise_error=True)
    except data.EUVATError as e:
        raise ApiInputError(unicode(e))


@eu_vat_service.route('/exchange-rates/<country_code>', methods=['POST'])
@eu_vat_service.route('/exchange-rates/<country_code>/<src_currency>', methods=['POST'])
@request_param('country_code', type=str)
@request_param('src_currency', type=str)
def get_exchange_rate(country_code, src_currency='EUR'):
    try:
        return data.get_exchange_rate(country_code, src_currency)
    except data.EUVATError as e:
        raise ApiInputError(unicode(e))


@eu_vat_service.route('/check', methods=['POST'])
@request_param('country_code', type=str)
@request_param('vat_number', type=str)
@request_param('amount', type=float)
@request_param('src_currency', type=str)
def check(country_code, vat_number=None, amount=None, src_currency='EUR'):
    if not data.is_eu_country(country_code):
        raise ApiNotFoundError('Not an EU country')
    
    is_vat_number_valid = data.validate_vat_number(vat_number) if vat_number else False
    o = {
        "country": country_code,
        "currency": data.EU_COUNTRIES[country_code],
        "vat_rate": data.get_vat_rate(country_code),
        "vat_number": vat_number,
        "is_vat_number_valid": is_vat_number_valid,
        "should_charge_vat": data.should_charge_vat(country_code, vat_number and is_vat_number_valid),
        "exchange_rate": eu_vat_service.get_exchange_rate(country_code, src_currency),
        "src_currency": src_currency
    }

    if amount:
        rate = 0
        if o['should_charge_vat']:
            rate = o['vat_rate'] / 100
        o.update({"amount": amount,
                    "vat_amount": round(amount * rate, 2),
                    "amount_with_vat": amount + amount * rate,
                    "exchanged_amount_with_vat": round((amount + amount * rate) * o["exchange_rate"], 2)})
                    
    return o
