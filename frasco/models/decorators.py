from sqlalchemy import event
from sqlalchemy.orm.session import object_session
from .transactions import current_transaction
import datetime
import functools
import inspect
from flask import current_app


def listens_for_modified_object_before_update(cls, func=None, include_collections=False):
    def decorator(func):
        @event.listens_for(cls, "before_update")
        def before_update(mapper, connection, target):
            if object_session(target).is_modified(target, include_collections=include_collections):
                func(target)
    if func:
        decorator(func)
        return
    return decorator


def auto_updated_at(cls):
    @listens_for_modified_object_before_update(cls)
    def on_update(target):
        target.updated_at = datetime.datetime.utcnow()
    return cls


def call_once_per_transaction(func):
    @functools.wraps(func)
    def wrapper(self):
        already_called = current_transaction.setdefault('call_once', {}).setdefault(func, set())
        if self not in already_called:
            already_called.add(self)
            func(self)
    return wrapper


def always_call_once_per_transaction_when_update(funcname):
    def decorator(cls):
        setattr(cls, funcname, call_once_per_transaction(getattr(cls, funcname)))

        @listens_for_modified_object_before_update(cls)
        def before_update(target):
            getattr(target, funcname)()

        return cls
    return decorator


def auto_clear_cache(cls):
    return always_call_once_per_transaction_when_update('clear_cache')(cls)
