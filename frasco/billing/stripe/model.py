from flask import has_request_context, request, current_app
from frasco.models import db
from frasco.ext import get_extension_state
from frasco.utils import cached_property
from sqlalchemy.ext.declarative import declared_attr
import stripe
from . import signals
import datetime
import time
import logging


logger = logging.getLogger('frasco.billing.stripe')


class StripeModelMixin(object):
    __stripe_auto_create_customer__ = True
    __stripe_email_property__ = 'email'
    __stripe_customer_expand__ = None

    stripe_customer_id = db.Column(db.String, index=True)
    has_stripe_payment_method = db.Column(db.Boolean, default=False)

    @classmethod
    def query_by_stripe_customer(cls, customer_id):
        return cls.query.filter(cls.stripe_customer_id == customer_id)

    @classmethod
    def create_stripe_payment_method(cls, type, **kwargs):
        return stripe.PaymentMethod.create(type=type, **kwargs)

    @cached_property
    def stripe_customer(self):
        try:
            return stripe.Customer.retrieve(self.stripe_customer_id, expand=self.__stripe_customer_expand__)
        except stripe.error.InvalidRequestError:
            if self.__stripe_auto_create_customer__:
                return self.create_stripe_customer()
            return

    @cached_property
    def default_stripe_invoice_payment_method(self):
        if self.stripe_customer.invoice_settings.default_payment_method:
            return stripe.PaymentMethod.retrieve(self.stripe_customer.invoice_settings.default_payment_method)

    def create_stripe_customer(self, **kwargs):
        kwargs.setdefault('email', getattr(self, self.__stripe_email_property__, None))
        kwargs.setdefault('expand', self.__stripe_customer_expand__)
        if kwargs.get('default_payment_method'):
            kwargs['payment_method'] = kwargs.pop('default_payment_method')
            kwargs.setdefault('invoice_settings', {})['default_payment_method'] = kwargs['payment_method']
        customer = stripe.Customer.create(**kwargs)
        self._update_stripe_customer(customer)
        logger.info('Customer %s for model #%s created' % (customer.id, self.id))
        return customer

    def update_stripe_customer(self, **kwargs):
        customer = self.stripe_customer
        for k, v in kwargs.items():
            setattr(customer, k, v)
        customer.save()
        self._update_stripe_customer(customer)
        logger.info('Customer %s updated' % self.stripe_customer_id)

    def delete_stripe_customer(self):
        if self.stripe_customer_id:
            try:
                self.stripe_customer.delete()
                logger.info('Customer %s deleted' % self.stripe_customer_id)
            except stripe.error.InvalidRequestError as e:
                if 'No such customer' not in str(e):
                    logger.warning("Customer %s that was to be deleted didn't exist anymore in Stripe" % self.stripe_customer_id)
                    raise
        self._update_stripe_customer(False)

    def _update_stripe_customer(self, customer=None):
        if customer is None:
            customer = self.stripe_customer

        if customer:
            self.stripe_customer_id = customer.id
            self.has_stripe_payment_method = bool(customer.invoice_settings['default_payment_method'])
            self.__dict__['stripe_customer'] = customer
        else:
            self.stripe_customer_id = None
            self.has_stripe_payment_method = False
            self.__dict__.pop('stripe_customer', None)

    def add_stripe_payment_method(self, type, make_default=True, **kwargs):
        pm = self.create_stripe_payment_method(type, **kwargs)
        self.attach_stripe_payment_method(pm.id, make_default)
        return pm

    def attach_stripe_payment_method(self, payment_method_id, make_default=True):
        stripe.PaymentMethod.attach(payment_method_id, customer=self.stripe_customer_id)
        if make_default:
            self.update_stripe_customer(invoice_settings=dict(self.stripe_customer.invoice_settings, default_payment_method=payment_method_id))

    def start_stripe_payment_intent(self, amount, currency, **kwargs):
        return stripe.PaymentIntent.create(amount=amount, currency=currency, customer=self.stripe_customer_id, **kwargs)


class StripeSubscriptionModelMixin(StripeModelMixin):
    __stripe_subscription_expand__ = None
    stripe_subscription_id = db.Column(db.String, index=True)
    
    @declared_attr
    def plan_name(cls):
        return db.Column(db.String, index=True)
    
    @declared_attr        
    def plan_status(cls):
        return db.Column(db.String, default='trialing', index=True)
    
    @declared_attr        
    def plan_last_invoice_at(cls):
        return db.Column(db.DateTime)
    
    @declared_attr        
    def plan_last_invoice_amount(cls):
        return db.Column(db.Float)
    
    @declared_attr        
    def plan_current_period_start(cls):
        return db.Column(db.DateTime)
    
    @declared_attr        
    def plan_current_period_end(cls):
        return db.Column(db.DateTime)
    
    @declared_attr        
    def plan_next_charge_at(cls):
        return db.Column(db.DateTime)
    
    @declared_attr        
    def plan_cancel_at_period_end(cls):
        return db.Column(db.Boolean, default=False)
    
    @declared_attr        
    def plan_cancelled_at(cls):
        return db.Column(db.DateTime)
    
    @declared_attr        
    def plan_has_invoice_items(cls):
        return db.Column(db.Boolean, index=True, default=False)
    
    @declared_attr        
    def plan_last_invoice_item_added_at(cls):
        return db.Column(db.DateTime, index=True)

    @classmethod
    def query_by_stripe_subscription(cls, subscription_id):
        return cls.query.filter(cls.stripe_subscription_id == subscription_id)

    @classmethod
    def query_has_stripe_invoice_items(cls, added_days_ago=None):
        q = cls.query.filter(cls.plan_has_invoice_items==True)
        if added_days_ago:
            q = q.filter(cls.plan_last_invoice_item_added_at<=datetime.date.today() - datetime.timedelta(days=added_days_ago))
        return q

    @cached_property
    def stripe_subscription(self):
        if not self.stripe_customer_id or not self.stripe_subscription_id:
            return
        expand = ['latest_invoice.payment_intent']
        if self.__stripe_subscription_expand__:
            expand.extend(self.__stripe_subscription_expand__)
        try:
            return self.stripe_customer.subscriptions.retrieve(self.stripe_subscription_id, expand=expand)
        except stripe.error.InvalidRequestError:
            return

    @property
    def stripe_subscription_item(self):
        sub = self.stripe_subscription
        if sub:
            return sub['items']['data'][0]

    def create_stripe_customer(self, plan=None, quantity=1, trial_end=None, coupon=None, **kwargs):
        state = get_extension_state('frasco_stripe')
        customer = super(StripeSubscriptionModelMixin, self).create_stripe_customer(**kwargs)

        if plan:
            self.subscribe_stripe_plan(plan, quantity, trial_end=trial_end, coupon=coupon)
        elif state.options['default_plan']:
            self.subscribe_stripe_plan(state.options['default_plan'], quantity, trial_end=trial_end, coupon=coupon)
                
        return customer

    def delete_stripe_customer(self):
        super(StripeSubscriptionModelMixin, self).delete_stripe_customer()
        if self.stripe_subscription_id:
            self._update_stripe_subscription(False)

    def subscribe_stripe_plan(self, plan=None, quantity=1, item_options=None, trial_end=None, **kwargs):
        state = get_extension_state('frasco_stripe')
        if not plan:
            plan = state.options['default_plan']
        if self.stripe_subscription_id and self.plan_name == plan:
            return

        item = dict(plan=plan, quantity=quantity)
        if item_options:
            item.update(item_options)

        kwargs.setdefault('expand', []).append('latest_invoice.payment_intent')
        if self.__stripe_subscription_expand__:
            kwargs['expand'].extend(self.__stripe_subscription_expand__)

        subscription = stripe.Subscription.create(customer=self.stripe_customer_id, items=[item],
            trial_end=_format_trial_end(trial_end), **kwargs)
        self._update_stripe_subscription(subscription)
        logger.info('Subscribed customer %s to plan %s' % (self.stripe_customer_id, plan))
        return subscription

    def update_stripe_subscription(self, **kwargs):
        kwargs.setdefault('expand', []).append('latest_invoice.payment_intent')
        if self.__stripe_subscription_expand__:
            kwargs['expand'].extend(self.__stripe_subscription_expand__)
        if 'trial_end' in kwargs:
            kwargs['trial_end'] = _format_trial_end(kwargs['trial_end'])
        subscription = stripe.Subscription.modify(self.stripe_subscription_id, **kwargs)
        self._update_stripe_subscription(subscription)
        logger.info('Subscription %s updated for %s' % (self.stripe_subscription_id, self.stripe_customer_id))

    def update_stripe_subscription_item(self, subscription_options=None, **kwargs):
        if not subscription_options:
            subscription_options = {}
        item = dict(id=self.stripe_subscription['items']['data'][0].id, **kwargs)
        self.update_stripe_subscription(items=[item], **subscription_options)

    def change_stripe_subscription_plan(self, plan, quantity=None, cancel_at_period_end=False, proration_behavior='create_prorations'):
        kwargs = {'plan': plan,
                  'quantity': quantity if quantity is not None else self.stripe_subscription_item['quantity']}
        self.update_stripe_subscription_item(subscription_options={
            'cancel_at_period_end': cancel_at_period_end,
            'proration_behavior': proration_behavior
        }, **kwargs)

    def cancel_stripe_subscription(self, at_period_end=True):
        if at_period_end:
            self.update_stripe_subscription(cancel_at_period_end=True)
        else:
            self.stripe_subscription.delete()
            self._update_stripe_subscription(False)
        logger.info('Subscription %s cancelled for %s' % (self.stripe_subscription_id, self.stripe_customer_id))

    def revert_stripe_subscription_period_end_cancellation(self):
        self.update_stripe_subscription(cancel_at_period_end=False)
        logger.info('Subscription %s reverted cancellation for %s' % (self.stripe_subscription_id, self.stripe_customer_id))

    def _update_stripe_customer(self, customer=None):
        super(StripeSubscriptionModelMixin, self)._update_stripe_customer(customer)
        if not self.stripe_customer:
            self._update_stripe_subscription(False)

    def _update_stripe_subscription(self, subscription=None):
        if subscription is None:
            if self.stripe_subscription_id:
                self.__dict__.pop('stripe_subscription', None)
                subscription = self.stripe_subscription
            elif self.stripe_customer.subscriptions.total_count > 0:
                subscription = self.stripe_customer.subscriptions.data[0]

        prev_plan = self.plan_name
        prev_status = self.plan_status

        if subscription:
            self.stripe_subscription_id = subscription.id
            self.__dict__['stripe_subscription'] = subscription
            self.plan_name = subscription.plan.id
            self.plan_status = subscription.status
            self.plan_current_period_start = datetime.datetime.fromtimestamp(subscription.current_period_start)
            self.plan_current_period_end = datetime.datetime.fromtimestamp(subscription.current_period_end)
            self.plan_cancel_at_period_end = subscription.cancel_at_period_end
            if self.plan_status == 'trialing':
                self.plan_next_charge_at = datetime.datetime.fromtimestamp(subscription.trial_end)
            elif subscription.current_period_end:
                self.plan_next_charge_at = self.plan_current_period_end
            else:
                self.plan_next_charge_at = None
            if self.plan_status == 'canceled' and prev_status != 'canceled':
                self.plan_cancelled_at = datetime.datetime.utcnow()
        else:
            if self.stripe_subscription_id:
                self.plan_cancelled_at = datetime.datetime.utcnow()
            self.stripe_subscription_id = None
            self.__dict__.pop('stripe_subscription', None)
            self.plan_name = None
            self.plan_status = 'canceled'
            self.plan_current_period_start = None
            self.plan_current_period_end = None
            self.plan_next_charge_at = None
            self.plan_cancel_at_period_end = None

        signals.model_subscription_updated.send(self, prev_plan=prev_plan, prev_status=prev_status)

    def is_stripe_subscription_payment_method_missing(self):
        return self.plan_status in ('incomplete', 'past_due') and self.stripe_subscription.latest_invoice.payment_intent.status == 'requires_payment_method'

    def does_stripe_subscription_payment_method_requires_action(self):
        return self.plan_status in ('incomplete', 'past_due') and self.stripe_subscription.latest_invoice.payment_intent.status == 'requires_action'

    @property
    def stripe_subscription_payment_intent_secret(self):
        return self.stripe_subscription.latest_invoice.payment_intent.client_secret

    def reattempt_stripe_subscription_last_invoice_payment(self):
        return stripe.Invoice.pay(self.stripe_subscription.latest_invoice, expand=['payment_intent'])

    def update_last_stripe_subscription_invoice(self, invoice):
        self.plan_last_invoice_at = datetime.datetime.fromtimestamp(invoice.created)
        self.plan_last_invoice_amount = invoice.total / 100
        self._update_stripe_subscription()
        if invoice.next_payment_attempt:
            self.plan_next_charge_at = datetime.datetime.fromtimestamp(invoice.next_payment_attempt)
        signals.model_last_invoice_updated.send(self)

    def add_item_to_next_stripe_subscription_invoice(self, amount, currency, description=None, **kwargs):
        if description:
            kwargs['description'] = description
        item = stripe.InvoiceItem.create(customer=self.stripe_customer_id, amount=amount, currency=currency, **kwargs)
        if not self.plan_has_invoice_items:
            self.plan_has_invoice_items = True
            self.plan_last_invoice_item_added_at = datetime.datetime.utcnow()
        return item

    def charge_now_items_from_upcoming_stripe_subscription_invoice(self, charge=True, **kwargs):
        invoice = stripe.Invoice.create(customer=self.stripe_customer_id, **kwargs)
        self.plan_has_invoice_items = False
        if charge:
            return stripe.Invoice.pay(invoice.id)
        return stripe.Invoice.finalize_invoice(invoice.id)


class StripeBillingDetailsModelMixin(object):
    __stripe_has_billing_fields__ = True
    __stripe_email_property__ = 'billing_email'

    @declared_attr
    def billing_name(cls):
        return db.Column(db.String)

    @declared_attr
    def billing_email(cls):
        return db.Column(db.String)

    @declared_attr
    def billing_phone(cls):
        return db.Column(db.String)

    @declared_attr
    def billing_address_line1(cls):
        return db.Column(db.String)

    @declared_attr
    def billing_address_line2(cls):
        return db.Column(db.String)

    @declared_attr
    def billing_address_city(cls):
        return db.Column(db.String)

    @declared_attr
    def billing_address_state(cls):
        return db.Column(db.String)

    @declared_attr
    def billing_address_zip(cls):
        return db.Column(db.String)

    @declared_attr
    def billing_address_country(cls):
        return db.Column(db.String)

    @declared_attr
    def billing_country(cls):
        return db.Column(db.String)

    @declared_attr
    def billing_type(cls):
        return db.Column(db.String)

    @declared_attr
    def billing_brand(cls):
        return db.Column(db.String)

    @declared_attr
    def billing_exp_month(cls):
        return db.Column(db.String)

    @declared_attr
    def billing_exp_year(cls):
        return db.Column(db.String)

    @declared_attr
    def billing_last4(cls):
        return db.Column(db.String)

    def create_stripe_customer(self, **kwargs):
        kwargs.update(self._get_billing_details_stripe_params())
        return super(StripeBillingDetailsModelMixin, self).create_stripe_customer(**kwargs)

    def _update_stripe_customer(self, customer=None):
        super(StripeBillingDetailsModelMixin, self)._update_stripe_customer(customer)
        if self.stripe_customer:
            self.update_payment_method_details_from_stripe()
        
    def update_from_stripe_billing_details(self):
        self.billing_name = self.stripe_customer.name
        self.billing_email = self.stripe_customer.email
        self.billing_phone = self.stripe_customer.phone
        addr = self.stripe_customer.address
        if addr:
            self.billing_address_line1 = addr['line1']
            self.billing_address_line2 = addr['line2']
            self.billing_address_zip = addr['postal_code']
            self.billing_address_city = addr['city']
            self.billing_address_state = addr['state']
            self.billing_address_country = addr['country']

    def update_stripe_billing_details(self, **kwargs):
        kwargs.update(self._get_billing_details_stripe_params())
        stripe.Customer.modify(self.stripe_customer_id, **kwargs)

    def _get_billing_details_stripe_params(self):
        o = {
            'name': self.billing_name,
            'email': self.billing_email,
            'phone': self.billing_phone
        }
        if self.billing_address_line1:
            o['address'] = {
                'line1': self.billing_address_line1,
                'line2': self.billing_address_line2,
                'postal_code': self.billing_address_zip,
                'city': self.billing_address_city,
                'state': self.billing_address_state,
                'country': self.billing_address_country
            }
        return o

    def update_payment_method_details_from_stripe(self, payment_method=None):
        if not payment_method:
            if not self.stripe_customer.invoice_settings.default_payment_method:
                return
            payment_method = stripe.PaymentMethod.retrieve(self.stripe_customer.invoice_settings.default_payment_method)

        self.billing_type = payment_method.type
        if payment_method.type == 'card':
            self.billing_last4 = payment_method.card['last4']
            self.billing_brand = payment_method.card['brand']
            self.billing_exp_month = payment_method.card['exp_month']
            self.billing_exp_year = payment_method.card['exp_year']
            self.billing_country = payment_method.card['country']
        elif payment_method.type == 'sepa_debit':
            self.billing_last4 = payment_method.sepa_debit['last4']
            self.billing_country = payment_method.sepa_debit['country']


class StripeEUVATModelMixin(object):
    __stripe_has_eu_vat__ = True
    __stripe_eu_auto_vat_country__ = True
    __stripe_eu_auto_vat_rate__ = True
    __stripe_eu_vat_use_address_country__ = False
    __stripe_eu_vat_exempt_reverse_charge__ = 'exempt'

    def create_stripe_customer(self, **kwargs):
        eu_vat_number = kwargs.pop('eu_vat_number', self.eu_vat_number)
        if eu_vat_number:
            kwargs['tax_id_data'] = [{'type': 'eu_vat', 'value': eu_vat_number}]
            kwargs['tax_exempt'] = 'none' if self.should_charge_eu_vat() else self.__stripe_eu_vat_exempt_reverse_charge__
        return super(StripeEUVATModelMixin, self).create_stripe_customer(**kwargs)

    def _update_stripe_customer(self, customer=None):
        super(StripeEUVATModelMixin, self)._update_stripe_customer(customer)
        if self.stripe_customer and self.__stripe_eu_auto_vat_country__:
            country = self.billing_address_country if self.__stripe_eu_vat_use_address_country__ else self.billing_country
            if country:
                self.eu_vat_country = country

    def update_from_stripe_eu_vat_number(self, customer=None):
        if not customer:
            customer = self.stripe_customer
        for tax_id in customer.tax_ids.data:
            if tax_id['type'] == 'eu_vat':
                self.eu_vat_number = tax_id['value']
                return

    def update_stripe_customer_eu_vat_number(self, eu_vat_number=None, tax_exempt=False, clear_existing=True):
        if clear_existing:
            self.remove_all_stripe_customer_tax_ids()
        if not eu_vat_number:
            eu_vat_number = self.eu_vat_number
            if eu_vat_number:
                tax_exempt = not self.should_charge_eu_vat()
        if eu_vat_number:
            stripe.Customer.create_tax_id(self.stripe_customer_id, type='eu_vat', value=eu_vat_number or self.eu_vat_number)
            stripe.Customer.modify(self.stripe_customer_id, tax_exempt=self.__stripe_eu_vat_exempt_reverse_charge__ if tax_exempt else 'none')
        else:
            stripe.Customer.modify(self.stripe_customer_id, tax_exempt='none')

    def remove_all_stripe_customer_tax_ids(self):
        for tax_id in stripe.Customer.list_tax_ids(self.stripe_customer_id):
            stripe.Customer.delete_tax_id(self.stripe_customer_id, tax_id.id)

    @property
    def stripe_default_tax_rates(self):
        if self.eu_vat_country:
            return [self._get_or_create_stripe_tax_rate(self.eu_vat_country, self.eu_vat_rate).id]

    def subscribe_stripe_plan(self, *args, **kwargs):
        if 'default_tax_rates' not in kwargs and self.__stripe_eu_auto_vat_rate__:
            kwargs['default_tax_rates'] = self.stripe_default_tax_rates
        return super(StripeEUVATModelMixin, self).subscribe_stripe_plan(*args, **kwargs)

    def update_stripe_subscription_tax_rates(self):
        stripe.Subscription.modify(self.stripe_subscription_id, default_tax_rates=self.stripe_default_tax_rates or '')

    def charge_now_items_from_upcoming_stripe_subscription_invoice(self, *args, **kwargs):
        if 'default_tax_rates' not in kwargs and self.__stripe_eu_auto_vat_rate__:
            kwargs['default_tax_rates'] = self.stripe_default_tax_rates
        return super(StripeEUVATModelMixin, self).charge_now_items_from_upcoming_stripe_subscription_invoice(*args, **kwargs)

    def _get_or_create_stripe_tax_rate(self, eu_country, tax_rate):
        for rate in stripe.TaxRate.list():
            if rate.jurisdiction == eu_country.upper():
                return rate
        return stripe.TaxRate.create(display_name="VAT", description="%s VAT" % eu_country.upper(),
            jurisdiction=eu_country.upper(), percentage=tax_rate, inclusive=False)


def _format_trial_end(trial_end=None):
    state = get_extension_state('frasco_stripe')
    if state.options['debug_trial_period'] and current_app.debug:
        if state.options['debug_trial_period'] == 'now':
            return 'now'
        else:
            trial_end = datetime.datetime.now() + \
                datetime.timedelta(days=state.options['debug_trial_period'])
    if isinstance(trial_end, datetime.datetime):
        if trial_end <= datetime.datetime.now():
            return 'now'
        return int(time.mktime(trial_end.timetuple()))
    return trial_end
