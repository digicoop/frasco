from frasco import lazy_translate, current_app
from frasco.ext import *
from frasco.models import transaction
from flask.signals import Namespace as SignalNamespace

from .data import *
from .model import *
from .service import eu_vat_service


_signals = SignalNamespace()
model_rate_updated = _signals.signal('vat_model_rate_updated')
rates_updated = _signals.signal('vat_rates_updated')


class FrascoEUVAT(Extension):
    name = "frasco_eu_vat"
    defaults = {"own_country": None,
                "model": None,
                "invoice_customer_mention_message": lazy_translate("VAT Number: {number}")}

    def _init_app(self, app, state):
        if state.options['model']:
            state.Model = state.import_option('model')

        if has_extension('frasco_invoicing', app):
            from frasco.billing.invoicing import invoice_issued
            invoice_issued.connect(lambda sender: update_invoice_with_eu_vat_info(sender), weak=True)

        @app.cli.command('update-eu-vat-rates')
        def update_model_vat_rates():
            with transaction():
                for country_code in EU_COUNTRIES:
                    rate = get_vat_rate(country_code)
                    for obj in state.Model.query.filter(state.Model._eu_vat_country == country_code, state.Model.eu_vat_rate != rate).all():
                        obj.eu_vat_rate = rate
                        model_rate_updated.send(obj)
                rates_updated.send()


def update_invoice_with_eu_vat_info(invoice):
    state = get_extension_state('frasco_eu_vat')
    if is_eu_country(invoice.country):
        invoice.is_eu_country = True
        if invoice.customer:
            invoice.eu_vat_number = invoice.customer.eu_vat_number
        try:
            invoice.eu_exchange_rate = get_exchange_rate(invoice.country, invoice.currency)
            if invoice.tax_amount:
                invoice.eu_vat_amount = invoice.tax_amount * invoice.eu_exchange_rate
        except Exception as e:
            current_app.log_exception(e)
            invoice.eu_exchange_rate = None
        if invoice.eu_vat_number and state.options['invoice_customer_mention_message']:
            invoice.customer_special_mention = state.options['invoice_customer_mention_message'].format(
                number=invoice.eu_vat_number)
    else:
        invoice.is_eu_country = False
