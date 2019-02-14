from frasco.mail.provider import MailProvider
import requests
import logging


class MailgunProvider(MailProvider):
    def send(self, msg):
        r = requests.post("https://api.mailgun.net/v3/%s/messages.mime" % self.options['mailgun_domain'],
            auth=("api", self.options['mailgun_api_key']), data={'to': msg.recipients}, files={'message': msg.as_string()})
        r.raise_for_status()
