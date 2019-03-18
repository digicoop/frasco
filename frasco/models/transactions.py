from flask import after_this_request, _request_ctx_stack
from frasco.ctx import ContextStack, DelayedCallsContext
from contextlib import contextmanager
import functools
from .ext import db
import logging


__all__ = ('transaction', 'as_transaction', 'is_transaction', 'delayed_tx_calls')


_transaction_ctx = ContextStack(default_item=True)
delayed_tx_calls = DelayedCallsContext()
logger = logging.getLogger('frasco.models')


@contextmanager
def transaction():
    if not _transaction_ctx.top:
        logger.debug('BEGIN TRANSACTION')
    _transaction_ctx.push()
    delayed_tx_calls.push()
    try:
        yield
        _transaction_ctx.pop()
        if not _transaction_ctx.top:
            logger.debug('COMMIT TRANSACTION')
            db.session.commit()
        else:
            db.session.flush()
        delayed_tx_calls.pop()
    except:
        _transaction_ctx.pop()
        if not _transaction_ctx.top:
            logger.debug('ROLLBACK TRANSACTION')
            db.session.rollback()
        delayed_tx_calls.pop(drop_calls=True)
        raise


def is_transaction():
    return bool(_transaction_ctx.top)


def as_transaction(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with transaction():
            return func(*args, **kwargs)
    return wrapper
