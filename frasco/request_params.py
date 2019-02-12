from flask import request, abort, current_app, has_request_context
from .utils import unknown_value
from .ctx import FlagContextStack
import functools
import logging


logger = logging.getLogger('frasco')


def _value_from_multidict(v, aslist=False):
    if aslist:
        return v
    if len(v) == 0:
        return None
    if len(v) == 1:
        return v[0]
    return v


class MissingRequestParam(Exception):
    pass


def get_request_param_value(name, location=None, aslist=False):
    if (not location or location == 'view_args') and name in request.view_args:
        if aslist and not isinstance(request.view_args[name], list):
            return [] if request.view_args[name] is None else [request.view_args[name]]
        return request.view_args[name]

    if not request.is_json:
        if not location or location == 'values':
            if name in request.values:
                return _value_from_multidict(request.values.getlist(name), aslist)
        elif location == 'args' and name in request.args:
            return _value_from_multidict(request.args.getlist(name), aslist)
        elif location == 'form' and name in request.form:
            return _value_from_multidict(request.form.getlist(name), aslist)

    if (not location or location == 'json') and request.is_json:
        data = request.get_json(silent=True)
        if isinstance(data, dict) and name in data:
            if aslist and not isinstance(data[name], list):
                return [] if data[name] is None else [data[name]]
            return data[name]

    if (not location or location == 'files') and name in request.files:
        return _value_from_multidict(request.files.getlist(name), aslist)

    raise MissingRequestParam("Request parameter '%s' is missing" % name)


class RequestParam(object):
    def __init__(self, name, type=None, nullable=False, required=False, loader=None, validator=None,
                 dest=None, location=None, aslist=False, aslist_iter_loader=True, help=None,
                 default=unknown_value, **loader_kwargs):
        self.name = name
        self.type = type
        self.nullable = nullable
        self.required = required
        self.loader = loader
        self.loader_kwargs = loader_kwargs
        self.validator = validator
        self.dest = dest
        self.location = location
        self.aslist = aslist
        self.aslist_iter_loader = aslist_iter_loader
        self.help = help
        self.default = default

    @property
    def names(self):
        return self.name if isinstance(self.name, tuple) else (self.name,)

    @property
    def types(self):
        if not self.type:
            return
        return self.type if isinstance(self.type, tuple) else (self.type,)

    @property
    def names_types(self):
        names = self.names
        fallback_type = None
        types = []
        if self.type:
            types = self.types
            fallback_type = types[-1]
        return [(names[i], types[i] if i < len(types) else fallback_type) for i in range(len(names))]

    @property
    def dests(self):
        if self.dest is None:
            return self.names
        elif self.dest and not isinstance(self.dest, tuple):
            return (self.dest,)
        return self.dest

    def process(self, request_data=None):
        try:
            values = self.extract(request_data)
        except MissingRequestParam:
            if self.required and self.default is unknown_value:
                logger.debug('Missing required parameter: %s' % ", ".join(self.names))
                abort(400)
            elif not self.default is unknown_value:
                if not isinstance(self.name, tuple):
                    values = [self.default]
                else:
                    values = self.default
            else:
                return dict()

        values = self.load(*values)
        if not self.validate(*values):
            logger.debug('Invalid parameter: %s' % ", ".join(self.names))
            abort(400)
        if self.dests is False:
            return {}
        if len(self.dests) != len(values):
            raise Exception('Mismatch between length of dest and number of values')
        return dict(zip(self.dests, values))

    def extract(self, request_data=None):
        values = []
        for name, type in self.names_types:
            if request_data:
                if name not in request_data:
                    raise MissingRequestParam("Request parameter '%s' is missing" % name)
                value = request_data[name]
                if self.aslist and not isinstance(value, (tuple, list)):
                    value = [] if value is None else [value]
            else:
                value = get_request_param_value(name, self.location, self.aslist)
            if value is None and not self.nullable:
                raise MissingRequestParam("Request parameter '%s' is missing" % name)
            if type and value is not None:
                if self.aslist:
                    value = map(lambda v: self.coerce(v, type), value)
                else:
                    value = self.coerce(value, type)
            values.append(value)
        return values

    def coerce(self, value, type):
        try:
            if type is bool:
                if isinstance(value, (str, unicode)):
                    return value.lower() not in ('False', 'false', 'no', '0')
                return bool(value)
            return type(value)
        except:
            abort(400)

    def load(self, *values):
        if self.loader:
            if self.aslist and self.aslist_iter_loader:
                rv = []
                for t in zip(*values):
                    rv.append(self.loader(*t, **self.loader_kwargs))
                return (rv,)
            else:
                rv = self.loader(*values, **self.loader_kwargs)
                if not isinstance(rv, tuple):
                    return (rv,)
                return rv
        return values

    def validate(self, *values):
        return not self.validator or self.validator(*values)

    def update_kwargs(self, kwargs, request_data=None):
        for name in self.names:
            kwargs.pop(name, None)
        kwargs.update(self.process(request_data))
        return kwargs


disable_request_params = FlagContextStack()


def update_kwargs_with_request_params(kwargs, request_params, request_data=None):
    for param in request_params:
        param.update_kwargs(kwargs, request_data)
    return kwargs


def wrap_request_param_func(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if has_request_context() and not disable_request_params.top:
            update_kwargs_with_request_params(kwargs, wrapper.request_params)
        return func(*args, **kwargs)
    wrapper.request_params = []
    return wrapper


def request_param(name, cls=RequestParam, append=True, **kwargs):
    def decorator(func):
        if not append or not hasattr(func, 'request_params'):
            wrapper = wrap_request_param_func(func)
        else:
            wrapper = func
        if isinstance(name, RequestParam):
            wrapper.request_params.append(name)
        else:
            wrapper.request_params.append(cls(name, **kwargs))
        return wrapper
    return decorator


def partial_request_param(name=None, cls=RequestParam, **kwargs):
    def decorator(name_=None, **kw):
        return request_param(name_ or name, cls=cls, **dict(kwargs, **kw))
    decorator.request_param = cls(name, **kwargs)
    return decorator


def request_params(params):
    def decorator(func):
        if isinstance(params, list):
            for i, param in enumerate(params):
                func = request_param(param)(func)
        elif params:
            for name, kwargs in params.iteritems():
                func = request_param(name, **kwargs)(func)
        return func
    decorator.params = params
    return decorator


def request_param_loader(name, **kwargs):
    def decorator(loader_func):
        return request_param(name, loader=loader_func, **kwargs)
    return decorator


def partial_request_param_loader(name=None, **kwargs):
    def decorator(loader_func):
        return partial_request_param(name, loader=loader_func, **kwargs)
    return decorator
