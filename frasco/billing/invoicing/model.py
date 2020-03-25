from frasco.models import db


class InvoiceModelMixin(object):
    ref = db.Column(db.String, index=True)
    currency = db.Column(db.String)
    subtotal = db.Column(db.Float)
    total = db.Column(db.Float)
    tax_amount = db.Column(db.Float)
    description = db.Column(db.String)
    name = db.Column(db.String)
    email = db.Column(db.String)
    address_line1 = db.Column(db.String)
    address_line2 = db.Column(db.String)
    address_city = db.Column(db.String)
    address_state = db.Column(db.String)
    address_zip = db.Column(db.String)
    address_country = db.Column(db.String)
    country = db.Column(db.String)
    customer_special_mention = db.Column(db.String)
    issued_at = db.Column(db.DateTime)
    charge_id = db.Column(db.String)
    external_id = db.Column(db.String)


class InvoiceItemModelMixin(object):
    amount = db.Column(db.Float)
    tax_amount = db.Column(db.Float)
    tax_rate = db.Column(db.Float)
    description = db.Column(db.String)
    quantity = db.Column(db.Integer)
    subtotal = db.Column(db.Float)
    currency = db.Column(db.String)
    external_id = db.Column(db.String)
