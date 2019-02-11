from frasco.ext import *
from frasco.mail import send_mail
from frasco.models import db, transaction
from flask.signals import Namespace as SignalNamespace
import datetime
import click
from contextlib import contextmanager
from .model import *


_signals = SignalNamespace()
invoice_issued = _signals.signal('invoice_issued')


class FrascoInvoicing(Extension):
    name = "frasco_invoicing"
    defaults = {"send_email": None}

    def _init_app(self, app, state):
        state.Model = state.import_option('model')
        state.ItemModel = state.import_option('item_model')
        state.ref_creator_func = create_invoice_ref

        if has_extension("frasco_mail", app):
            app.extensions.frasco_mail.add_templates_from_package(__name__)
            if state.options['send_email'] is None:
                state.options['send_email'] = True

        @app.cli.command('send-invoice-email')
        @click.argument('invoice_id')
        @click.option('--email')
        def send_email_command(invoice_id, email=None):
            invoice = state.Model.query.get(invoice_id)
            send_invoice_mail(email or invoice.email, invoice)

    @ext_stateful_method
    def ref_creator(self, state, func):
        state.ref_creator_func = func
        return func


@contextmanager
def create_invoice(**create_invoice_ref_kwargs):
    state = get_extension_state('frasco_invoicing')
    with transaction():
        invoice = state.Model()
        invoice.ref = create_invoice_ref(**create_invoice_ref_kwargs)
        yield (invoice, state.ItemModel)
        db.session.add(invoice)
        invoice_issued.send(invoice)
    if state.options['send_email'] and invoice.email:
        send_invoice_mail(invoice.email, invoice)


def create_invoice_ref(category=None, counter=None, separator='-', merge_date=True):
    today = datetime.date.today()
    parts = [today.year, today.month, today.day]
    if merge_date:
        parts = ["".join(map(str, parts))]
    if category:
        parts.append(category)
    if counter is None:
        counter = get_extension_state('frasco_invoicing').Model.query.count() + 1
    parts.append(counter)
    return separator.join(map(str, parts))


def send_invoice_mail(email, invoice, **kwargs):
    items = []
    for item in invoice.items:
        items.append((item.description, item.quantity, item.amount))
    send_mail(email, 'invoice.html',
        invoice=invoice,
        invoice_date=invoice.issued_at,
        invoice_items=items,
        invoice_currency=invoice.currency.upper(),
        invoice_total=invoice.total,
        invoice_tax=invoice.tax_amount,
        invoice_tax_rate=invoice.tax_rate,
        **kwargs)


def send_failed_invoice_mail(email, invoice, **kwargs):
    items = []
    for line in invoice.lines.data:
        items.append((line.description or '', line.quantity, line.amount / 100.0))
    send_mail(email, 'failed_invoice.html',
        invoice_date=datetime.datetime.fromtimestamp(invoice.date),
        invoice_items=items,
        invoice_currency=invoice.currency.upper(),
        invoice_total=invoice.total / 100.0, **kwargs)
