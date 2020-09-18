from werkzeug.utils import import_string as wz_import_string, cached_property
from flask import abort
from slugify import slugify
import functools
import re
import yaml
import os
import subprocess
import click
import inspect


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
    for k, v in attrs.items():
        setattr(obj, k, v)


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


def extract_unmatched_items(items, allowed_keys, prefix=None, uppercase=False):
    unmatched = {}
    for k, v in items.items():
        if k not in allowed_keys:
            if prefix:
                k = "%s%s" % (prefix, k)
            if uppercase:
                k = k.upper()
            unmatched[k] = v
    return unmatched


def deep_update_dict(a, b):
    for k, v in b.items():
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
        if name not in self:
            raise AttributeError()
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


class ShellError(Exception):
    def __init__(self, returncode, stderr):
        super(ShellError, self).__init__(stderr)
        self.returncode = returncode
        self.stderr = stderr

    def __str__(self):
        return str(self.stderr)


def shell_exec(args, echo=True, fg="green", **kwargs):
    kwargs["stdout"] = subprocess.PIPE
    kwargs["stderr"] = subprocess.STDOUT
    p = subprocess.run(args, **kwargs)
    if p.returncode > 0:
        raise ShellError(p.returncode, p.stdout)
    if echo:
        click.secho(p.stdout.decode(), fg=fg)
    return p.stdout


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


def join_url_rule(rule1, rule2):
    if not rule1:
        return rule2
    if not rule2:
        return rule1
    return (rule1.rstrip('/') + '/' + rule2.lstrip('/')).rstrip('/')
