from frasco.mail.provider import MailProvider
from flask_mail import _Mail, Connection


class SMTPProvider(MailProvider):
    def __init__(self, state, options):
        super().__init__(state, options)
        self.mail_state = _Mail(
            options.get('server', '127.0.0.1'),
            options.get('username'),
            options.get('password'),
            options.get('port', 25),
            options.get('use_tls', False),
            options.get('use_ssl', False),
            options.get('default_sender'),
            False, # debug
            options.get('max_emails'),
            False, # suppress
            options.get('ascii_attachments', False)
        )

    def connect(self):
        return Connection(self.mail_state)

    def send(self, msg):
        with self.connect() as conn:
            conn.send(msg)

    def start_bulk_connection(self):
        conn = self.connect()
        # simulate entering a with context
        # (flask-mail does not provide a way to connect otherwise)
        conn.__enter__()
        return conn

    def stop_bulk_connection(self, conn):
        conn.__exit__(None, None, None)
