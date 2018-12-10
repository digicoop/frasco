from frasco.models import db
from sqlalchemy.ext.declarative import declared_attr
from .data import is_eu_country, should_charge_vat, get_vat_rate


class EUVATModelMixin(object):
    @declared_attr
    def _eu_vat_country(cls):
        return db.deferred(db.Column('eu_vat_country', db.String), group='eu_vat')

    @declared_attr
    def eu_vat_number(cls):
        return db.deferred(db.Column(db.String), group='eu_vat')

    @declared_attr
    def eu_vat_rate(cls):
        return db.deferred(db.Column(db.Float), group='eu_vat')

    def should_charge_eu_vat(self):
        return should_charge_vat(self.eu_vat_country, self.eu_vat_number)

    @property
    def eu_vat_country(self):
        return self._eu_vat_country

    @eu_vat_country.setter
    def eu_vat_country(self, value):
        if is_eu_country(value):
            self._eu_vat_country = value.upper()
            self.eu_vat_rate = get_vat_rate(self.eu_vat_country)
        else:
            self._eu_vat_country = None
            self.eu_vat_rate = None


class EUVATInvoiceModelMixin(object):
    is_eu_country = db.Column(db.Boolean, default=False)
    eu_vat_number = db.Column(db.String)
    eu_exchange_rate = db.Column(db.Float)
    eu_vat_amount = db.Column(db.Float, default=0)
