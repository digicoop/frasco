from flask import Response, abort
from .ctx import ContextStack, FlagContextStack
from .utils import AttrDict
import functools
import inspect


try:
    from marshmallow import Schema as MarshmallowSchema
    marshmallow_available = True
except ImportError:
    marshmallow_available = False


disable_marshaller = FlagContextStack()
marshalling_context_stack = ContextStack()
marshalling_context = marshalling_context_stack.make_proxy()


def marshal(rv, marshaller, func=None, args=None, kwargs=None, **marshaller_kwargs):
    with marshalling_context_stack(AttrDict(func=func, args=args, kwargs=kwargs, marshaller_kwargs=marshaller_kwargs)):
        if marshmallow_available:
            if inspect.isclass(marshaller) and issubclass(marshaller, MarshmallowSchema):
                schema = marshaller(**marshaller_kwargs)
                return schema.dump(rv)
            elif isinstance(marshaller, MarshmallowSchema):
                return marshaller.dump(rv, **marshaller_kwargs)
        if hasattr(marshaller, '__marshaller__'):
            marshaller = marshaller.__marshaller__
        return marshaller(rv, **marshaller_kwargs)


def marshal_with(marshaller, filter=None, filter_status_code=403, **marshaller_kwargs):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            rv = func(*args, **kwargs)
            if not disable_marshaller.top:
                rv = marshal(rv, marshaller, func=func, args=args, kwargs=kwargs, **marshaller_kwargs)
                if filter:
                    rv = filter(rv)
                    if rv is None and filter_status_code:
                        abort(filter_status_code)
            return rv
        wrapper.marshalled_with = marshaller
        return wrapper
    return decorator


def marshal_many_with(marshaller, filter=None, **marshaller_kwargs):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            items = func(*args, **kwargs)
            if not disable_marshaller.top:
                items = [marshal(i, marshaller, func=func, args=args, kwargs=kwargs, **marshaller_kwargs) for i in items]
                if filter:
                    items = [i for i in items if filter(i)]
            return items
        wrapper.marshalled_with = marshaller
        return wrapper
    return decorator


def marshal_dict_with(**mapping):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            data = func(*args, **kwargs)
            if disable_marshaller.top:
                return data
            out = {}
            for k, v in data.items():
                if k in mapping:
                    out[k] = marshal(v, mapping[k], func=func, args=args, kwargs=kwargs)
                else:
                    out[k] = v
            return out
        wrapper.marshalled_with = mapping
        return wrapper
    return decorator
