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


_current_transaction_ctx = ContextStack()
current_transaction = _current_transaction_ctx.make_proxy()


def after_transaction_commit(func):
    delayed_tx_calls.call(func, [], {})


@event.listens_for(SignallingSession, 'after_begin')
def on_after_begin(session, transaction, connection):
    _current_transaction_ctx.push(AttrDict())

@event.listens_for(SignallingSession, 'after_commit')
def on_after_commit(session):
    _current_transaction_ctx.pop()

@event.listens_for(SignallingSession, 'after_rollback')
def on_after_rollback(session):
    _current_transaction_ctx.pop()
