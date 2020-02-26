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


STRIPE_API_VERSION = "2020-03-02"
stripe.enable_telemetry = False


class FrascoStripe(Extension):
    name = "frasco_stripe"
    defaults = {"default_currency": None,
                "default_plan": None,
                "no_payment_redirect_to": None,
                "no_payment_message": None,
                "subscription_past_due_message": lazy_translate(
                    "We attempted to charge your credit card for your subscription but it failed."
                    "Please check your credit card details"),
                "debug_trial_period": None,
                "send_trial_will_end_email": True,
                "send_failed_invoice_mail": True,
                "invoice_ref_kwargs": {},
                "webhook_validate_event": False}

    def _init_app(self, app, state):
        stripe.api_key = state.require_option('api_key')
        stripe.api_version = STRIPE_API_VERSION
        state.Model = state.import_option('model')
        state.subscription_enabled = hasattr(state.Model, 'stripe_subscription_id')

        app.register_blueprint(webhook_blueprint)

        if has_extension("frasco_mail", app):
            app.extensions.frasco_mail.add_templates_from_package(__name__)

        if has_extension('frasco_eu_vat', app) and hasattr(state.Model, '__stripe_has_eu_vat__'):
            model_rate_updated.connect(lambda sender: sender.update_stripe_subscription_tax_rates(), weak=True)

        stripe_event_signal('customer_updated').connect(on_customer_updated_event)
        stripe_event_signal('customer_deleted').connect(on_customer_deleted_event)
        stripe_event_signal('payment_method_attached').connect(on_payment_method_event)
        stripe_event_signal('payment_method_detached').connect(on_payment_method_event)
        stripe_event_signal('payment_method_updated').connect(on_payment_method_event)
        stripe_event_signal('payment_method_card_automatically_updated').connect(on_payment_method_event)
        stripe_event_signal('invoice_payment_succeeded').connect(on_invoice_payment)
        stripe_event_signal('invoice_payment_failed').connect(on_invoice_payment)
        if state.subscription_enabled:
            stripe_event_signal('customer_subscription_created').connect(on_subscription_event)
            stripe_event_signal('customer_subscription_updated').connect(on_subscription_event)
            stripe_event_signal('customer_subscription_deleted').connect(on_subscription_event)
            stripe_event_signal('customer_subscription_trial_will_end').connect(on_trial_will_end)
            stripe_event_signal('invoice_created').connect(on_subscription_invoice_created)
        if hasattr(state.Model, '__stripe_has_eu_vat__'):
            stripe_event_signal('customer_tax_id_created').connect(on_tax_id_event)
            stripe_event_signal('customer_tax_id_updated').connect(on_tax_id_event)
            stripe_event_signal('customer_tax_id_deleted').connect(on_tax_id_event)


@as_transaction
def on_customer_updated_event(sender, stripe_event):
    state = get_extension_state('frasco_stripe')
    customer = stripe_event.data.object
    obj = state.Model.query_by_stripe_customer(customer.id).first()
    if obj:
        obj._update_stripe_customer(customer)


@as_transaction
def on_customer_deleted_event(sender, stripe_event):
    state = get_extension_state('frasco_stripe')
    customer = stripe_event.data.object
    obj = state.Model.query_by_stripe_customer(customer.id).first()
    if obj:
        obj._update_stripe_customer(False)


@as_transaction
def on_payment_method_event(sender, stripe_event):
    state = get_extension_state('frasco_stripe')
    source = stripe_event.data.object
    obj = state.Model.query_by_stripe_customer(source.customer).first()
    if obj:
        obj._update_stripe_customer()


@as_transaction
def on_tax_id_event(sender, stripe_event):
    state = get_extension_state('frasco_stripe')
    obj = state.Model.query_by_stripe_customer(stripe_event.data.object.customer).first()
    if obj:
        obj.update_from_stripe_eu_vat_number()


@as_transaction
def on_subscription_event(sender, stripe_event):
    state = get_extension_state('frasco_stripe')
    subscription = stripe_event.data.object
    obj = state.Model.query_by_stripe_customer(subscription.customer).first()
    if obj:
        obj._update_stripe_subscription()


@as_transaction
def on_subscription_invoice_created(sender, stripe_event):
    state = get_extension_state('frasco_stripe')
    invoice = stripe_event.data.object
    if not invoice.subscription:
        return
    obj = state.Model.query_by_stripe_customer(invoice.customer).first()
    if obj:
        obj.plan_has_invoice_items = False
        model_subscription_invoice_created.send(obj)


@as_transaction
def on_trial_will_end(sender, stripe_event):
    state = get_extension_state('frasco_stripe')
    subscription = stripe_event.data.object
    obj = state.Model.query_by_stripe_subscription(subscription.id).first()
    if obj and state.options['send_trial_will_end_email']:
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
            sub_obj.plan_status = sub_obj.stripe_subscription.status
            sub_obj.update_last_stripe_subscription_invoice(invoice)

    invoice_payment.send(invoice)

    if has_extension('frasco_invoicing'):
        if invoice.paid:
            create_invoice_from_stripe(obj, invoice)
        elif not invoice.paid and state.options['send_failed_invoice_mail']:
            send_failed_invoice_mail(getattr(obj, obj.__stripe_email_property__), invoice)
