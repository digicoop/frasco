from flask.signals import Namespace


__all__ = ('user_signed_up', 'password_updated', 'reset_password_sent')


_signals = Namespace()
user_signed_up = _signals.signal('user_signed_up')
password_updated = _signals.signal('user_password_updated')
reset_password_sent = _signals.signal('user_reset_password_sent')

