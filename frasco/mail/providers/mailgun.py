from frasco.mail.provider import MailProvider
import requests
import logging


MAILGUN_API_URL = 'https://api.mailgun.net/v3'


class MailgunProvider(MailProvider):
    def send(self, msg):
        r = requests.post("%s/%s/messages.mime" % (self.options.get('mailgun_api_url', MAILGUN_API_URL), self.options['mailgun_domain']),
            auth=("api", self.options['mailgun_api_key']), data={'to': msg.send_to}, files={'message': msg.as_string()})
        r.raise_for_status()
