from frasco import current_app
from frasco.ctx import ContextStack
from contextlib import contextmanager
import logging

bulk_connection_context = ContextStack()


class BulkConnection(object):
    def __init__(self, sender):
        self.sender = sender

    def send(self, msg):
        self.sender(msg)


class MailProvider(object):
    def __init__(self, app, state, options):
        self.app = app
        self.state = state
        self.options = options

    def send(self, msg):
        raise NotImplementedError()

    def start_bulk_connection(self):
        return BulkConnection(self.send)

    def stop_bulk_connection(self, bulk_connection):
        pass

    @contextmanager
    def bulk_connection(self):
        failed_establish = False
        try:
            conn = self.start_bulk_connection()
        except Exception as e:
            if not self.state.options['silent_failures']:
                raise e
            current_app.log_exception(e)
            logging.getLogger('frasco.mail').warning("Failed establishing bulk connection")
            conn = BulkConnection(self.send)
            failed_establish = True

        bulk_connection_context.push(conn)
        try:
            yield conn
        finally:
            if not failed_establish:
                self.stop_bulk_connection(conn)
            bulk_connection_context.pop()
