from flask import Blueprint, current_app, request
from .signals import stripe_event_signal
import stripe


webhook_blueprint = Blueprint('stripe_webhook', __name__)


@webhook_blueprint.route('/stripe-webhook', methods=['POST'])
def webhook():
    if current_app.extensions.frasco_stripe.options['webhook_validate_event']:
        event = stripe.Event.retrieve(request.json['id'])
    else:
        event = stripe.Event.construct_from(request.json,
            current_app.extensions.frasco_stripe.options['api_key'])
    stripe_event_signal(event.type.replace(".", "_")).send(stripe, stripe_event=event)
    return 'ok'
