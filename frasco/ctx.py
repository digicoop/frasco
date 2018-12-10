from flask import has_request_context, _request_ctx_stack
from frasco.utils import unknown_value
from werkzeug.local import LocalProxy, LocalStack
from contextlib import contextmanager
import functools


class ContextStack(LocalStack):
    def __init__(self, top=None, default_item=None, allow_nested=True, ignore_nested=False):
        super(ContextStack, self).__init__()
        self.default_top = top
        self.default_item = default_item
        self.allow_nested = allow_nested
        self.ignore_nested = ignore_nested

    @property
    def stack(self):
        return getattr(self._local, 'stack', None) or []

    @property
    def is_stacked(self):
        return bool(self.stack)

    def push(self, item=unknown_value):
        if self.is_stacked and not self.allow_nested:
            raise RuntimeError('Context does not support nesting')
        if self.is_stacked and self.ignore_nested:
            item = self.top
        elif item is unknown_value:
            if callable(self.default_item):
                item = self.default_item()
            else:
                item = self.default_item
        super(ContextStack, self).push(item)
        return item

    def replace(self, item):
        stack = self.stack
        if stack:
            stack.pop()
            stack.append(item)
        return item

    @property
    def top(self):
        try:
            return self._local.stack[-1]
        except (AttributeError, IndexError):
            return self.default_top

    @contextmanager
    def ctx(self, item=unknown_value, **kwargs):
        item = self.push(item, **kwargs)
        try:
            yield item
        finally:
            self.pop()

    def __call__(self, *args, **kwargs):
        return self.ctx(*args, **kwargs)

    def make_proxy(self):
        return super(ContextStack, self).__call__()


def context_stack_on_request_context(name, cls=ContextStack):
    def _get_object():
        if has_request_context() and not hasattr(_request_ctx_stack.top, name):
            setattr(_request_ctx_stack.top, name, cls())
        return getattr(_request_ctx_stack.top, name, None)
    return LocalProxy(_get_object)


delayed_result = object()


class DelayedCallsContext(ContextStack):
    def __init__(self):
        super(DelayedCallsContext, self).__init__(default_item=list, ignore_nested=True)

    def call(self, func, args, kwargs):
        if self.top is not None:
            self.top.append((func, args, kwargs))
            return delayed_result
        return func(*args, **kwargs)

    def pop(self, drop_calls=False):
        top = super(DelayedCallsContext, self).pop()
        if not drop_calls and not self.is_stacked:
            for func, args, kwargs in top:
                func(*args, **kwargs)

    def proxy(self, func):
        @functools.wraps(func)
        def proxy(*args, **kwargs):
            return self.call(func, args, kwargs)
        return proxy


class FlagContextStack(ContextStack):
    def __init__(self, flag=False):
        super(FlagContextStack, self).__init__(flag, not flag)
        self.once_stack = ContextStack()

    def push(self, item=unknown_value, once=False):
        self.once_stack.push(once)
        return super(FlagContextStack, self).push(item)

    def pop(self):
        self.once_stack.pop()
        return super(FlagContextStack, self).pop()

    def once(self, value=unknown_value):
        return self.ctx(unknown_value, once=True)

    def consume_once(self):
        top = self.top
        if self.once_stack.top:
            self.once_stack.replace(False)
            self.replace(self.stack[-2] if len(self.stack) > 1 else self.default_top)
        return top

    def once_consumer(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            self.consume_once()
            return func(*args, **kwargs)
        return wrapper

    def active(self):
        if self.once_stack.top:
            return self.consume_once()
        return self.top
