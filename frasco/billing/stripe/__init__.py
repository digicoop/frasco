from frasco import lazy_translate, request, flash, redirect
from frasco.ext import *
from frasco.utils import unknown_value
from frasco.models import as_transaction
from frasco.mail import send_mail
import stripe
import datetime
import time
import os
import json

from frasco.billing.eu_vat import get_exchange_rate, is_eu_country, model_rate_updated
from frasco.billing.invoicing import send_failed_invoice_mail

from .signals import *
from .webhook import webhook_blueprint
from .invoice import *
from .model import *


class FrascoStripe(Extension):
    name = "frasco_stripe"
    defaults = {"default_currency": None,
                "default_plan": None,
                "no_payment_redirect_to": None,
                "no_payment_message": None,
                "subscription_past_due_message": lazy_translate(
                    u"We attempted to charge your credit card for your subscription but it failed."
                    "Please check your credit card details"),
                "debug_trial_period": None,
                "send_trial_will_end_email": True,
                "send_failed_invoice_mail": True,
                "invoice_ref_kwargs": {},
                "webhook_validate_event": False,
                "default_subscription_tax_percent": None}

    def _init_app(self, app, state):
        stripe.api_key = state.require_option('api_key')
        state.Model = state.import_option('model')
        state.subscription_enabled = hasattr(state.Model, 'stripe_subscription_id')

        app.register_blueprint(webhook_blueprint)

        if has_extension("frasco_mail", app):
            app.extensions.frasco_mail.add_templates_from_package(__name__)

        if has_extension('frasco_eu_vat', app):
            def on_model_rate_updated(sender):
                if sender.stripe_subscription:
                    sender.stripe_subscription.tax_percent = sender.eu_vat_rate
                    sender.stripe_subscription.save()
            model_rate_updated.connect(on_model_rate_updated, weak=True)

        stripe_event_signal('customer_source_updated').connect(on_source_event)
        stripe_event_signal('customer_source_deleted').connect(on_source_event)
        stripe_event_signal('invoice_payment_succeeded').connect(on_invoice_payment)
        stripe_event_signal('invoice_payment_failed').connect(on_invoice_payment)
        if state.subscription_enabled:
            stripe_event_signal('customer_subscription_updated').connect(on_subscription_event)
            stripe_event_signal('customer_subscription_deleted').connect(on_subscription_event)
            stripe_event_signal('customer_subscription_trial_will_end').connect(on_trial_will_end)


def check_stripe_subscription_is_valid(obj):
    state = get_extension_state('frasco_stripe')
    if obj.is_stripe_subscription_valid():
        if state.options['no_payment_message']:
            flash(state.options['no_payment_message'], 'error')
        if state.options['no_payment_redirect_to']:
            return redirect(state.options['no_payment_redirect_to'])
    if obj.plan_status == 'past_due' and state.options['subscription_past_due_message']:
        flash(state.options['subscription_past_due_message'], 'error')


@as_transaction
def on_source_event(sender, stripe_event):
    state = get_extension_state('frasco_stripe')
    source = stripe_event.data.object
    obj = state.Model.query_by_stripe_customer(source.customer).first()
    if not obj:
        return
    obj._update_stripe_source()


@as_transaction
def on_subscription_event(sender, stripe_event):
    state = get_extension_state('frasco_stripe')
    subscription = stripe_event.data.object
    obj = state.Model.query_by_stripe_customer(subscription.customer).first()
    if not obj:
        return
    obj._update_stripe_subscription(subscription)


@as_transaction
def on_trial_will_end(sender, stripe_event):
    state = get_extension_state('frasco_stripe')
    subscription = stripe_event.data.object
    obj = state.Model.query_by_stripe_subscription(subscription.id).first()
    if not obj:
        return
    if state.options['send_trial_will_end_email']:
        send_mail(getattr(obj, obj.__stripe_email_property__), 'stripe/trial_will_end.txt', obj=obj)


@as_transaction
def on_invoice_payment(sender, stripe_event):
    state = get_extension_state('frasco_stripe')
    invoice = stripe_event.data.object
    if not invoice.customer:
        return

    obj = state.Model.query_by_stripe_customer(invoice.customer).first()
    if not obj or invoice.total == 0:
        return

    if invoice.subscription:
        sub_obj = None
        if obj.stripe_subscription_id == invoice.subscription:
            sub_obj = obj
        else:
            sub_obj = state.Model.query_by_stripe_subscription(invoice.subscription).first()
        if sub_obj:
            sub_obj.update_last_stripe_subscription_charge(invoice)

    if getattr(obj, '__stripe_has_eu_vat__', False) and getattr(obj, '__stripe_has_billing_fields__', False) and is_eu_country(obj.billing_country):
        invoice.metadata['eu_vat_exchange_rate'] = get_exchange_rate(obj.billing_country, invoice.currency.upper())
        if invoice.tax:
            invoice.metadata['eu_vat_amount'] = round(invoice.tax * invoice.metadata['eu_vat_exchange_rate'])
        if obj.eu_vat_number:
            invoice.metadata['eu_vat_number'] = obj.eu_vat_number
        invoice.save()

    invoice_payment.send(invoice)

    if has_extension('frasco_invoicing'):
        if invoice.paid:
            create_invoice_from_stripe(obj, invoice)
        elif not invoice.paid and state.options['send_failed_invoice_mail']:
            send_failed_invoice_mail(getattr(obj, obj.__stripe_email_property__), invoice)
