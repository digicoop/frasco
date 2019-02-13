from flask import has_request_context, request, current_app
from frasco.models import db
from frasco.ext import get_extension_state
from frasco.utils import cached_property
from sqlalchemy.ext.declarative import declared_attr
import stripe
import signals
import datetime
import time
import logging


logger = logging.getLogger('frasco.billing.stripe')


class StripeModelMixin(object):
    __stripe_auto_create_customer__ = True
    __stripe_email_property__ = 'email'

    _stripe_customer_id = db.Column('stripe_customer_id', db.String, index=True)
    has_stripe_source = db.Column(db.Boolean, default=False, index=True)

    @classmethod
    def query_by_stripe_customer(cls, customer_id):
        return cls.query.filter(cls._stripe_customer_id == customer_id)

    @property
    def stripe_customer_id(self):
        return self._stripe_customer_id

    @stripe_customer_id.setter
    def stripe_customer_id(self, value):
        self._stripe_customer_id = value
        self._update_stripe_source()

    @cached_property
    def stripe_customer(self):
        try:
            return stripe.Customer.retrieve(self.stripe_customer_id)
        except stripe.error.InvalidRequestError:
            if self.__stripe_auto_create_customer__:
                return self.create_stripe_customer()
            return

    @cached_property
    def stripe_default_source(self):
        if not self.stripe_customer_id:
            return
        default_id = self.stripe_customer.default_source
        if default_id:
            return self.stripe_customer.sources.retrieve(default_id)

    def create_stripe_customer(self, **kwargs):
        kwargs.setdefault('email', getattr(self, self.__stripe_email_property__, None))
        customer = stripe.Customer.create(**kwargs)
        self.stripe_customer_id = customer.id if customer else None
        self._update_stripe_source()
        logger.info(u'Customer %s for model #%s created' % (customer.id, self.id))
        return customer

    def update_stripe_customer(self, **kwargs):
        customer = self.stripe_customer
        for k, v in kwargs.iteritems():
            setattr(customer, k, v)
        customer.save()
        self._update_stripe_source()
        logger.info(u'Customer %s updated' % self.stripe_customer_id)

    def _update_stripe_source(self):
        self.__dict__.pop('stripe_customer', None)
        customer = self.stripe_customer
        self.has_stripe_source = customer.default_source is not None \
            if customer and not getattr(customer, 'deleted', False) else False
        signals.model_source_updated.send(self)

    def delete_stripe_customer(self):
        if self.stripe_customer_id:
            try:
                self.stripe_customer.delete()
                logger.info(u'Customer %s deleted' % self.stripe_customer_id)
            except stripe.error.InvalidRequestError as e:
                if u'No such customer' not in unicode(e):
                    logger.warning(u"Customer %s that was to be deleted didn't exist anymore in Stripe" % self.stripe_customer_id)
                    raise
        self.stripe_customer_id = None

    def add_stripe_source(self, token=None, **source_details):
        self.stripe_customer.sources.create(source=token or source_details)
        self._update_stripe_source()
        logger.info(u'Added new stripe source to %s' % self.stripe_customer_id)

    def remove_stripe_source(self, source_id=None):
        if not source_id:
            source_id = self.stripe_customer.default_source
        try:
            source = self.stripe_customer.sources.retrieve(source_id)
        except stripe.error.InvalidRequestError:
            return
        source.delete()
        self._update_stripe_source()
        logger.info(u'Removed stripe source from %s' % self.stripe_customer_id)

    def charge_stripe_customer(self, amount, **kwargs):
        kwargs['customer'] = self.stripe_customer_id
        kwargs.setdefault('currency', get_extension_state('frasco_stripe').options['default_currency'])
        return stripe.Charge.create(amount=amount, **kwargs)


class StripeSubscriptionModelMixin(StripeModelMixin):
    stripe_subscription_id = db.Column(db.String, index=True)
    
    @declared_attr
    def plan_name(cls):
        return db.deferred(db.Column(db.String, index=True), group='stripe_plan')
    
    @declared_attr        
    def plan_status(cls):
        return db.deferred(db.Column(db.String, default='trialing', index=True), group='stripe_plan')
    
    @declared_attr        
    def plan_last_charged_at(cls):
        return db.deferred(db.Column(db.DateTime), group='stripe_plan')
    
    @declared_attr        
    def plan_last_charge_amount(cls):
        return db.deferred(db.Column(db.Float), group='stripe_plan')
    
    @declared_attr        
    def plan_last_charge_successful(cls):
        return db.deferred(db.Column(db.Boolean, default=True, index=True), group='stripe_plan')
    
    @declared_attr        
    def plan_next_charge_at(cls):
        return db.deferred(db.Column(db.DateTime, index=True), group='stripe_plan')

    @classmethod
    def query_by_stripe_subscription(cls, subscription_id):
        return cls.query.filter(cls.stripe_subscription_id == subscription_id)

    @cached_property
    def stripe_subscription(self):
        if not self.stripe_customer_id or not self.stripe_subscription_id:
            return
        try:
            return self.stripe_customer.subscriptions.retrieve(self.stripe_subscription_id)
        except stripe.error.InvalidRequestError:
            return

    def create_stripe_customer(self, trial_end=None, coupon=None, tax_percent=None, **kwargs):
        state = get_extension_state('frasco_stripe')
        if 'plan' in kwargs:
            kwargs.update(dict(trial_end=_format_trial_end(trial_end),
                coupon=coupon, tax_percent=tax_percent))

        customer = super(StripeSubscriptionModelMixin, self).create_stripe_customer(**kwargs)

        if 'plan' in kwargs:
            subscription = customer.subscriptions.data[0]
            self._update_stripe_subscription(subscription)
        elif state.options['default_plan']:
            self.subscribe_stripe_plan(state.options['default_plan'], trial_end=trial_end,
                coupon=coupon, tax_percent=tax_percent)
                
        return customer

    def delete_stripe_customer(self):
        super(StripeSubscriptionModelMixin, self).delete_stripe_customer()
        if self.stripe_subscription_id:
            self._update_stripe_subscription(False)

    def subscribe_stripe_plan(self, plan=None, quantity=1, **kwargs):
        state = get_extension_state('frasco_stripe')
        if not plan:
            plan = state.options['default_plan']
        if self.plan_name == plan:
            return

        params = dict(plan=plan, quantity=quantity,
            trial_end=_format_trial_end(kwargs.pop('trial_end', None)))
        params.update(kwargs)
        if 'tax_percent' not in kwargs and state.options['default_subscription_tax_percent']:
            params['tax_percent'] = state.options['default_subscription_tax_percent']

        subscription = self.stripe_customer.subscriptions.create(**params)
        self._update_stripe_subscription(subscription)
        logger.info(u'Subscribed customer %s to plan %s' % (self.stripe_customer_id, plan))
        return subscription

    def update_stripe_subscription(self, **kwargs):
        subscription = self.stripe_subscription
        for k, v in kwargs.iteritems():
            setattr(subscription, k, v)
        subscription.save()
        self._update_stripe_subscription(subscription)
        logger.info(u'Subscription %s updated for %s' % (self.stripe_subscription_id, self.stripe_customer_id))

    def cancel_stripe_subscription(self):
        self.stripe_subscription.delete()
        self._update_stripe_subscription(False)
        logger.info(u'Subscription %s cancelled for %s' % (self.stripe_subscription_id, self.stripe_customer_id))

    def _update_stripe_subscription(self, subscription=None):
        if subscription is None:
            if self.stripe_customer.subscriptions.total_count > 0:
                subscription = self.stripe_customer.subscriptions.data[0]
        prev_plan = self.plan_name
        prev_status = self.plan_status

        if subscription:
            self.stripe_subscription_id = subscription.id
            self.plan_name = subscription.plan.id
            self.plan_status = subscription.status
            if self.plan_status == 'trialing':
                self.plan_next_charge_at = datetime.datetime.fromtimestamp(subscription.trial_end)
            elif subscription.current_period_end:
                self.plan_next_charge_at = datetime.datetime.fromtimestamp(subscription.current_period_end)
            else:
                self.plan_next_charge_at = None
        else:
            self.stripe_subscription_id = None
            self.plan_name = None
            self.plan_status = 'canceled'
            self.plan_next_charge_at = None

        signals.model_subscription_updated.send(self, prev_plan=prev_plan, prev_status=prev_status)

    def update_last_stripe_subscription_charge(self, invoice):
        self.plan_last_charged_at = datetime.datetime.fromtimestamp(invoice.date)
        self.plan_last_charge_amount = invoice.total / 100
        self.plan_last_charge_successful = invoice.paid
        if invoice.paid:
            self.plan_next_charge_at = datetime.datetime.fromtimestamp(self.stripe_subscription.current_period_end)
        elif invoice.next_payment_attempt:
            self.plan_next_charge_at = datetime.datetime.fromtimestamp(invoice.next_payment_attempt)
        else:
            self.plan_next_charge_at = None
        signals.model_last_charge_updated.send(self)

    def is_stripe_subscription_valid(self):
        return self.plan_name and (\
            self.plan_status in ('trialing', 'past_due') or \
            (self.plan_status == 'active' and self.has_stripe_source))


class StripeBillingInfoModelMixin(object):
    __stripe_has_billing_fields__ = True
    __stripe_reset_billing_fields__ = True

    @declared_attr
    def billing_name(cls):
        return db.deferred(db.Column(db.String), group='billing')

    @declared_attr
    def billing_address_line1(cls):
        return db.deferred(db.Column(db.String), group='billing')

    @declared_attr
    def billing_address_line2(cls):
        return db.deferred(db.Column(db.String), group='billing')

    @declared_attr
    def billing_address_city(cls):
        return db.deferred(db.Column(db.String), group='billing')

    @declared_attr
    def billing_address_state(cls):
        return db.deferred(db.Column(db.String), group='billing')

    @declared_attr
    def billing_address_zip(cls):
        return db.deferred(db.Column(db.String), group='billing')

    @declared_attr
    def billing_address_country(cls):
        return db.deferred(db.Column(db.String), group='billing')

    @declared_attr
    def billing_country(cls):
        return db.deferred(db.Column(db.String), group='billing')

    @declared_attr
    def billing_ip_address(cls):
        return db.deferred(db.Column(db.String), group='billing')

    @declared_attr
    def billing_brand(cls):
        return db.deferred(db.Column(db.String), group='billing')

    @declared_attr
    def billing_exp_month(cls):
        return db.deferred(db.Column(db.String), group='billing')

    @declared_attr
    def billing_exp_year(cls):
        return db.deferred(db.Column(db.String), group='billing')

    @declared_attr
    def billing_last4(cls):
        return db.deferred(db.Column(db.String), group='billing')
        
    def _update_stripe_source(self):
        super(StripeBillingInfoModelMixin, self)._update_stripe_source()
        if self.has_stripe_source or self.__stripe_reset_billing_fields__:
            billing_fields = ('name', 'address_line1', 'address_line2', 'address_state', 'address_city',
                'address_zip', 'address_country', 'country', 'brand', 'exp_month', 'exp_year', 'last4')
            source = self.stripe_default_source if self.has_stripe_source else None
            for field in billing_fields:
                setattr(self, 'billing_%s' % field, getattr(source, field) if source else None)
            if has_request_context() and self.has_stripe_source:
                self.billing_ip_address = request.remote_addr


class StripeEUVATModelMixin(object):
    __stripe_has_eu_vat__ = True
    __stripe_eu_auto_vat_country__ = True
    __stripe_eu_auto_vat_rate__ = True
    __stripe_eu_vat_use_address_country__ = False

    def _update_stripe_source(self):
        super(StripeEUVATModelMixin, self)._update_stripe_source()
        if self.__stripe_eu_auto_vat_country__:
            country = None
            if self.has_stripe_source:
                if self.__stripe_eu_vat_use_address_country__:
                    country = self.stripe_default_source.address_country
                else:
                    country = self.stripe_default_source.country
            self.eu_vat_country = country
            
        if self.__stripe_eu_auto_vat_rate__ and self.stripe_subscription and self.should_charge_eu_vat():
            self.update_stripe_subscription(tax_percent=self.eu_vat_rate)

    def subscribe_stripe_plan(self, *args, **kwargs):
        if 'tax_percent' not in kwargs and self.__stripe_eu_auto_vat_rate__ and self.should_charge_eu_vat():
            kwargs['tax_percent'] = self.eu_vat_rate
        return super(StripeEUVATModelMixin, self).subscribe_stripe_plan(*args, **kwargs)


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
