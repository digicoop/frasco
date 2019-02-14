from frasco.mail.provider import MailProvider
from frasco.utils import inject_app_config


class SMTPProvider(MailProvider):
    def send(self, msg):
        return self.state.mail.send(msg)

    def start_bulk_connection(self):
        connection = self.state.mail.connect()
        # simulate entering a with context
        # (flask-mail does not provide a way to connect otherwise)
        connection.__enter__()
        return connection

    def stop_bulk_connection(self, conn):
        conn.__exit__(None, None, None)
