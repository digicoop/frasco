from flask import after_this_request, _request_ctx_stack
from flask_sqlalchemy import SignallingSession
from frasco.ctx import ContextStack, DelayedCallsContext
from frasco.utils import AttrDict
from contextlib import contextmanager
from sqlalchemy import event
import functools
from .ext import db
import logging


__all__ = ('transaction', 'as_transaction', 'current_transaction', 'is_transaction', 'delayed_tx_calls', 'after_transaction_commit')


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


def after_transaction_commit(func):
    delayed_tx_calls.call(func, [], {})


_current_transaction_ctx = ContextStack()
current_transaction = _current_transaction_ctx.make_proxy()


@event.listens_for(SignallingSession, 'after_transaction_create')
def on_after_transaction_create(session, transaction):
    if transaction.parent is None:
        _current_transaction_ctx.push(AttrDict())


@event.listens_for(SignallingSession, 'after_transaction_end')
def on_after_transaction_end(session, transaction):
    if transaction.parent is None:
        _current_transaction_ctx.pop()
