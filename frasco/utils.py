from werkzeug.utils import import_string as wz_import_string, cached_property
from werkzeug.local import LocalProxy, LocalStack
from flask import Markup, json, request, _request_ctx_stack, has_request_context, abort, current_app
import imp
import functools
import re
from slugify import slugify
import yaml
import speaklater
import os
from contextlib import contextmanager
import subprocess
import click
import inspect
import logging
from .helpers import url_for


def import_string(impstr, attr=None):
    """Imports a string. Can import an attribute of the imported
    class/module using a double colon as a separator
    """
    if inspect.isclass(impstr):
        return impstr
    if "::" in impstr:
        impstr, attr = impstr.split("::")
    imported = wz_import_string(impstr)
    if attr is not None:
        return getobjpath(imported, attr)
    return imported


def getobjpath(obj, path):
    """Returns an item or attribute of the object recursively.
    Item names are specified between brackets, eg: [item].
    Attribute names are prefixed with a dot (the first one is optional), eg: .attr
    Example: getobjpath(obj, "attr1.attr2[item].attr3")
    """
    if not path:
        return obj
    if path.startswith("["):
        item = path[1:path.index("]")]
        return getobjpath(obj[item], path[len(item) + 2:])
    if path.startswith("."):
        path = path[1:]
    if "." in path or "[" in path:
        dot_idx = path.find(".")
        bracket_idx = path.find("[")
        if dot_idx == -1 or bracket_idx < dot_idx:
            idx = bracket_idx
            next_idx = idx
        else:
            idx = dot_idx
            next_idx = idx + 1
        attr = path[:idx]
        return getobjpath(getattr(obj, attr), path[next_idx:])
    return getattr(obj, path)


def find_classes_in_module(module, clstypes):
    """Find classes of clstypes in module
    """
    classes = []
    for item in dir(module):
        item = getattr(module, item)
        try:
            for cls in clstypes:
                if issubclass(item, cls) and item != cls:
                    classes.append(item)
        except:
            pass
    return classes


class ImportClassError(ImportError):
    pass


def find_class_in_module(cls, clstypes):
    if not isinstance(clstypes, (tuple, list)):
        clstypes = (clstypes,)

    if inspect.ismodule(cls):
        classes = find_classes_in_module(cls, clstypes)
        if not classes:
            raise ImportClassError('No extension class found in module')
        if len(classes) > 1:
            raise ImportClassError('Too many extension classes in module')
        return classes[0]

    if not isinstance(cls, clstypes):
        raise ImportClassError("Wrong class type")
    return cls


def import_class(impstr, clstypes, fallback_package=None):
    try:
        return find_class_in_module(import_string(impstr), clstypes)
    except ImportError as e:
        if not fallback_package or ('No module named' not in str(e) and str(e) != 'No extension class found in module'):
            raise
        return find_class_in_module(import_string(fallback_package + "." + impstr), clstypes)



def remove_yaml_frontmatter(source, return_frontmatter=False):
    """If there's one, remove the YAML front-matter from the source
    """
    if source.startswith("---\n"):
        frontmatter_end = source.find("\n---\n", 4)
        if frontmatter_end == -1:
            frontmatter = source
            source = ""
        else:
            frontmatter = source[0:frontmatter_end]
            source = source[frontmatter_end + 5:]
        if return_frontmatter:
            return (source, frontmatter)
        return source
    if return_frontmatter:
        return (source, None)
    return source


def parse_yaml_frontmatter(source):
    source, frontmatter = remove_yaml_frontmatter(source, True)
    if frontmatter:
        return (yaml.safe_load(frontmatter), source)
    return (None, source)


def populate_obj(obj, attrs):
    """Populates an object's attributes using the provided dict
    """
    for k, v in attrs.iteritems():
        setattr(obj, k, v)


def url_for_static(filename, **kwargs):
    """Shortcut function for url_for('static', filename=filename)
    """
    return url_for('static', filename=filename, **kwargs)


def url_for_same(**overrides):
    return url_for(request.endpoint, **dict(dict(request.args,
        **request.view_args), **overrides))


def wrap_in_markup(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        return Markup(f(*args, **kwargs))
    return wrapper


def make_kwarg_validator(name, validator_func):
    if not isinstance(name, tuple):
        name = (name,)
    def decorator_gen(**kwargs):
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kw):
                values = {n: kw.get(n) for n in name}
                if not validator_func(**dict(kwargs, **values)):
                    abort(400)
                return func(*args, **kw)
            return wrapper
        return decorator
    return decorator_gen


def kwarg_validator(name):
    def decorator(validator_func):
        return make_kwarg_validator(name, validator_func)
    return decorator


def inject_app_config(app, config, prefix=None):
    for k, v in config.iteritems():
        if prefix:
            k = "%s%s" % (prefix, k)
        app.config[k.upper()] = v


def extract_unmatched_items(items, allowed_keys, prefix=None, uppercase=False):
    unmatched = {}
    for k, v in items.iteritems():
        if k not in allowed_keys:
            if prefix:
                k = "%s%s" % (prefix, k)
            if uppercase:
                k = k.upper()
            unmatched[k] = v
    return unmatched


def deep_update_dict(a, b):
    for k, v in b.iteritems():
        if k not in a:
            a[k] = v
        elif isinstance(a[k], dict) and isinstance(v, dict):
            deep_update_dict(a[k], v)
        elif isinstance(a[k], list) and isinstance(v, list):
            a[k].extend(v)
        elif isinstance(v, list) and not isinstance(a[k], list):
            a[k] = [a[k]] + v
        else:
            a[k] = v
    return a


class UnknownValue(object):
    pass

unknown_value = UnknownValue()


class AttrDict(dict):
    """Dict which keys are accessible as attributes
    """
    def __getattr__(self, name):
        return self[name]

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        del self[name]

    def get_or_raise(self, name, message):
        try:
            return self[name]
        except KeyError:
            raise KeyError(message)

    def for_json(self):
        return dict(self)


class JSONEncoder(json.JSONEncoder):
    """A JSONEncoder which always activates the for_json feature
    """
    def __init__(self, *args, **kwargs):
        kwargs["for_json"] = True
        super(JSONEncoder, self).__init__(*args, **kwargs)

    def default(self, o):
        if isinstance(o, speaklater._LazyString):
            return o.value
        if isinstance(o, set):
            return list(o)
        return json.JSONEncoder.default(self, o)


class ShellError(Exception):
    def __init__(self, returncode, stderr):
        super(ShellError, self).__init__(stderr)
        self.returncode = returncode
        self.stderr = stderr

    def __unicode__(self):
        return unicode(self.stderr)


def shell_exec(args, echo=True, fg="green", **kwargs):
    kwargs["stdout"] = subprocess.PIPE
    kwargs["stderr"] = subprocess.STDOUT
    p = subprocess.Popen(args, **kwargs)
    out, _ = p.communicate()
    if p.returncode > 0:
        raise ShellError(p.returncode, out)
    if echo:
        click.secho(out, fg=fg)
    return out


def get_remote_addr():
    if current_app.debug and "__remoteaddr" in request.values:
        return request.values["__remoteaddr"]
    return request.remote_addr



def match_domains(domain, allowed_domains):
    for allowed_domain in allowed_domains:
        if allowed_domain.startswith('^'):
            if re.search(allowed_domain, domain, re.I):
                return True
        elif allowed_domain.lower() == domain.lower():
            return True
    return False


def match_email_domain(email, allowed_domains):
    if not email or not '@' in email:
        return False
    _, domain = email.split('@')
    return match_domains(domain, allowed_domains)


def remove_all_handlers_from_logger(logger):
    for handler in logger.handlers:
        logger.removeHandler(handler)
    return logger


class ExcludeWerkzeugLogFilter(logging.Filter):
    def filter(self, record):
        return record.name != 'werkzeug'


def join_url_rule(rule1, rule2):
    if not rule1:
        return rule2
    if not rule2:
        return rule1
    return (rule1.rstrip('/') + '/' + rule2.lstrip('/')).rstrip('/')
