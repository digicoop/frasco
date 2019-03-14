from flask import json
from apispec import APISpec
from frasco.utils import join_url_rule
import re


__all__ = ('build_swagger_spec',)


def build_swagger_spec(api_version):
    spec = APISpec(title="API %s" % api_version.version,
                    version=api_version.version,
                    openapi_version="3.0.2",
                    basePath=api_version.url_prefix)
    for service in api_version.iter_services():
        paths = {}
        tag = {"name": service.name}
        if hasattr(service, 'description'):
            tag["description"] = service.description
        spec.tag(tag)
        for rule, endpoint, func, options in service.iter_endpoints():
            rule = join_url_rule(service.url_prefix, rule)
            path = paths.setdefault(convert_url_args(rule), {})
            for method in options.get('methods', ['GET']):
                op = build_spec_operation(rule, service.name + '_' + endpoint, func, options)
                op['tags'] = [service.name]
                path[method.lower()] = op
        for path, operations in paths.iteritems():
            spec.path(path=path, operations=operations)

    return spec


def build_spec_operation(rule, endpoint, func, options):
    o = {"operationId": endpoint, "parameters": build_spec_params(rule, endpoint, func, options)}
    if func.__doc__:
        o['description'] = func.__doc__
    return o


def build_spec_params(rule, endpoint, func, options):
    method = options.get('methods', ['GET'])[0]
    params = []
    if hasattr(func, 'request_params'):
        url = convert_url_args(rule)
        for p in reversed(func.request_params):
            for pname in p.names:
                loc = "query"
                if ("{%s}" % pname) in url:
                    loc = "path"
                elif method.upper() in ("POST", "PUT"):
                    loc = "formData"
                o = {"name": pname,
                        "type": convert_type_to_spec(p.type),
                        "required": bool(p.required),
                        "in": loc}
                if p.help:
                    o['description'] = p.help
                params.append(o)
    return params


_url_arg_re = re.compile(r"<([a-z]+:)?([a-z0-9_]+)>")
def convert_url_args(url):
    return _url_arg_re.sub(r"{\2}", url)


def convert_type_to_spec(type):
    if type is int:
        return "integer"
    if type is float:
        return "number"
    if type is bool:
        return "boolean"
    return "string"


def build_swagger_client(spec, spec_url, var_name='API', class_name = 'SwaggerClient'):
    return "function %s(options) { options['spec'] = %s; %s.call(this, '%s', options); } %s.prototype = new %s();" % (
            var_name,
            json.dumps(spec),
            class_name,
            spec_url,
            var_name,
            class_name
        )
