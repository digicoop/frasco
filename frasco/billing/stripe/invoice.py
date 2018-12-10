from frasco.ext import get_extension_state
from frasco.models import as_transaction
from frasco.billing.invoicing import create_invoice
from frasco.billing.eu_vat import is_eu_country, get_vat_rate, should_charge_vat
import datetime


def create_invoice_from_charge(charge, obj=None, lines=None, tax_rate=None):
    state = get_extension_state('frasco_stripe')
    with create_invoice(**state.options['invoice_ref_kwargs']) as (invoice, InvoiceItem):
        invoice.currency = charge.currency.upper()
        invoice.subtotal = charge.amount / 100.0
        invoice.total = charge.amount / 100.0
        invoice.description = charge.description
        invoice.issued_at = datetime.datetime.fromtimestamp(charge.created)
        invoice.charge_id = charge.id
        invoice.paid = charge.status == "succeeded"
        if obj is not None:
            _fill_invoice_from_obj(invoice, obj)

        if tax_rate and tax_rate == "eu_vat":
            if is_eu_country(invoice.country):
                tax_rate = get_vat_rate(invoice.country)
                if not should_charge_vat(invoice.country, obj.eu_vat_number):
                    tax_rate = None
            else:
                tax_rate = None
        if tax_rate:
            invoice.tax_rate = tax_rate
            invoice.subtotal = invoice.total * (100 / (100 + tax_rate));
            invoice.tax_amount = invoice.total - invoice.subtotal

        if lines:
            for line in lines:
                item = InvoiceItem()
                item.amount = line['amount']
                item.quantity = line.get('quantity', 1)
                item.currency = line.get('currency', charge.currency.upper())
                item.description = line['description']
                invoice.items.append(item)


def create_invoice_from_stripe(obj, stripe_invoice):
    state = get_extension_state('frasco_stripe')
    with create_invoice(**state.options['invoice_ref_kwargs']) as (invoice, InvoiceItem):
        _fill_invoice_from_obj(invoice, obj)

        invoice.external_id = stripe_invoice.id
        invoice.currency = stripe_invoice.currency.upper()
        invoice.subtotal = stripe_invoice.subtotal / 100.0
        invoice.total = stripe_invoice.total / 100.0
        invoice.tax_rate = stripe_invoice.tax_percent
        invoice.tax_amount = stripe_invoice.tax / 100.0 if stripe_invoice.tax else None
        invoice.description = stripe_invoice.description
        invoice.issued_at = datetime.datetime.fromtimestamp(stripe_invoice.date)
        invoice.paid = stripe_invoice.paid
        invoice.charge_id = stripe_invoice.charge

        for line in stripe_invoice.lines.data:
            item = InvoiceItem()
            item.external_id = line.id
            item.amount = line.amount / 100.0
            item.quantity = line.quantity
            item.currency = line.currency
            item.description = line.description or ''
            invoice.items.append(item)


def _fill_invoice_from_obj(invoice, obj):
    invoice.customer = obj
    invoice.email = getattr(obj, obj.__stripe_email_property__)
    if getattr(obj, '__has_stripe_billing_fields__', False):
        invoice.name = obj.billing_name
        invoice.address_line1 = obj.billing_address_line1
        invoice.address_line2 = obj.billing_address_line2
        invoice.address_city = obj.billing_address_city
        invoice.address_state = obj.billing_address_state
        invoice.address_zip = obj.billing_address_zip
        invoice.address_country = obj.billing_address_country
        if obj.billing_country:
            invoice.country = obj.billing_country.upper() 
        elif obj.billing_address_country:
            invoice.country = obj.billing_address_country.upper()
