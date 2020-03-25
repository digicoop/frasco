from frasco import current_app
from frasco.ext import get_extension_state
from suds.client import Client as SudsClient
from suds import WebFault
import xml.etree.ElementTree as ET
import requests
import datetime


EU_COUNTRIES = {
    "AT": "EUR", # Austria
    "BE": "EUR", # Belgium
    "BG": "BGN", # Bulgaria
    "DE": "EUR", # Germany
    "CY": "EUR", # Cyprus
    "CZ": "CZK", # Czech Republic
    "DK": "DKK", # Denmark
    "EE": "EUR", # Estonia
    "ES": "EUR", # Spain
    "FI": "EUR", # Finland
    "FR": "EUR", # France,
    "GB": "GBP", # Great Britain
    "GR": "EUR", # Greece
    "HR": "HRK", # Croatia
    "HU": "HUF", # Hungary
    "IE": "EUR", # Ireland
    "IT": "EUR", # Italy
    "LT": "EUR", # Lithuania
    "LV": "EUR", # Latvia
    "LU": "EUR", # Luxembourg
    "MT": "EUR", # Malta
    "NL": "EUR", # Netherlands
    "PL": "PLN", # Poland
    "PT": "EUR", # Portugal
    "RO": "RON", # Romania
    "SE": "SEK", # Sweden
    "SI": "EUR", # Slovenia
    "SK": "EUR"  # Slovakia
}


KNOWN_VAT_RATES = {
    "AT": 20.0, # Austria
    "BE": 21.0, # Belgium
    "BG": 20.0, # Bulgaria
    "DE": 19.0, # Germany
    "CY": 19.0, # Cyprus
    "CZ": 21.0, # Czech Republic
    "DK": 25.0, # Denmark
    "EE": 20.0, # Estonia
    "ES": 21.0, # Spain
    "FI": 24.0, # Finland
    "FR": 20.0, # France,
    "GB": 20.0, # Great Britain
    "GR": 23.0, # Greece
    "HR": 25.0, # Croatia
    "HU": 27.0, # Hungary
    "IE": 23.0, # Ireland
    "IT": 22.0, # Italy
    "LT": 21.0, # Lithuania
    "LV": 21.0, # Latvia
    "LU": 15.0, # Luxembourg
    "MT": 18.0, # Malta
    "NL": 21.0, # Netherlands
    "PL": 23.0, # Poland
    "PT": 23.0, # Portugal
    "RO": 24.0, # Romania
    "SE": 25.0, # Sweden
    "SI": 22.0, # Slovenia
    "SK": 20.0  # Slovakia
}


ECB_EUROFXREF_URL = 'http://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml'
ECB_EUROFXREF_XML_NS = 'http://www.ecb.int/vocabulary/2002-08-01/eurofxref'
VIES_SOAP_WSDL_URL = 'http://ec.europa.eu/taxation_customs/vies/checkVatService.wsdl'
TIC_SOAP_WSDL_URL = 'http://ec.europa.eu/taxation_customs/tic/VatRateWebService.wsdl'


def is_eu_country(country_code):
    return country_code and country_code.upper() in EU_COUNTRIES


def should_charge_vat(country_code, eu_vat_number=None):
    return is_eu_country(country_code) and (
        get_extension_state('frasco_eu_vat').options['own_country'] == country_code or not eu_vat_number)


_exchange_rates_cache = {}
_vat_rates_cache = {}


VIESClient = None
def get_vies_soap_client():
    global VIESClient
    if not VIESClient:
        VIESClient = SudsClient(VIES_SOAP_WSDL_URL)
    return VIESClient


TICClient = None
def get_ticc_soap_client():
    global TICClient
    if not TICClient:
        TICClient = SudsClient(TIC_SOAP_WSDL_URL)
    return TICClient


class EUVATError(Exception):
    pass


def get_vat_rate(country_code, rate_type='standard'):
    country_code = country_code.upper()
    if not is_eu_country(country_code):
        raise EUVATError('Not an EU country')
    if country_code not in _vat_rates_cache:
        _vat_rates_cache[country_code] = {}
        try:
            r = get_ticc_soap_client().service.getRates(dict(memberState=country_code,
                requestDate=datetime.date.today().isoformat()))
            for rate in r.ratesResponse.rate:
                _vat_rates_cache[country_code][rate.type.lower()] = float(rate.value)
        except Exception as e:
            current_app.logger.debug(e)
            _vat_rates_cache.pop(country_code)
            return KNOWN_VAT_RATES.get(country_code)
    return _vat_rates_cache[country_code].get(rate_type.lower())


def validate_vat_number(vat_number, invalid_format_raise_error=False):
    if len(vat_number) < 3:
        if invalid_format_raise_error:
            raise EUVATError('VAT number too short')
        return False
    try:
        r = get_vies_soap_client().service.checkVat(vat_number[0:2].upper(), vat_number[2:])
        return r.valid
    except WebFault:
        pass
    return False


def fetch_exchange_rates():
    today = datetime.date.today()
    if today in _exchange_rates_cache:
        return _exchange_rates_cache[today]
    rates = {'EUR': 1.0}
    try:
        r = requests.get(ECB_EUROFXREF_URL)
        root = ET.fromstring(r.text)
        for cube in root.findall('eu:Cube/eu:Cube/eu:Cube', {'eu': ECB_EUROFXREF_XML_NS}):
            rates[cube.attrib['currency']] = float(cube.attrib['rate'])
        _exchange_rates_cache[today] = rates
    except Exception as e:
        current_app.logger.debug(e)
    return rates


def get_exchange_rate(country_code, src_currency='EUR'):
    if not is_eu_country(country_code):
        raise EUVATError('Not an EU country')
    dest_currency = EU_COUNTRIES[country_code]
    rates = fetch_exchange_rates()
    if src_currency == dest_currency:
        return 1.0
    if src_currency == 'EUR':
        return rates.get(dest_currency, 1.0)
    if src_currency not in rates:
        raise EUVATError('Can only use a currency listed in the ECB rates')
    return round(1.0 / rates[src_currency] * rates.get(dest_currency, 1.0), 5)
