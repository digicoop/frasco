from flask import json
from apispec import APISpec
from frasco.utils import join_url_rule
import re


__all__ = ('build_swagger_spec',)


def build_swagger_spec(api_version, with_security_scheme=False):
    spec = APISpec(title="API %s" % api_version.version,
                    version=api_version.version,
                    openapi_version="3.0.2",
                    basePath=api_version.url_prefix)

    if with_security_scheme:
        spec.components.security_scheme("api_key_bearer_token", {"type": "http", "scheme": "bearer"})
        spec.components.security_scheme("api_key_header", {"type": "apiKey", "in": "header", "name": "X-Api-Key"})
        spec.components.response("NotAuthenticatedError", {"description": "Authentification required"})
        spec.components.response("NotAuthorizedError", {"description": "Some permissions are missing to perform this request"})

    for service in api_version.iter_services():
        paths = {}
        tag = {"name": service.name}
        if service.description:
            tag["description"] = service.description
        spec.tag(tag)
        for rule, endpoint, func, options in service.iter_endpoints():
            rule = join_url_rule(service.url_prefix, rule)
            path = paths.setdefault(convert_url_args(rule), {})
            for method in options.get('methods', ['GET']):
                op = build_spec_operation(rule, service.name + '_' + endpoint, func, options, with_security_scheme)
                op['tags'] = [service.name]
                path[method.lower()] = op
        for path, operations in paths.items():
            spec.path(path=path, operations=operations)

    return spec


def build_spec_operation(rule, endpoint, func, options, with_security_scheme=False):
    responses = {
        "200": {"description": "Successful response"},
        "default": {"description": "Unexpected error"}
    }
    if with_security_scheme:
        responses["401"] = {"$ref": "#/components/responses/NotAuthenticatedError"}
        responses["403"] = {"$ref": "#/components/responses/NotAuthorizedError"}

    path_request_params = []
    query_request_params = []
    body_request_params = []
    file_request_params = []
    if hasattr(func, 'request_params'):
        url = convert_url_args(rule)
        method = options.get('methods', ['GET'])[0]
        for p in reversed(func.request_params):
            for pname in p.names:
                if p.location == 'files':
                    file_request_params.append((pname, p))
                elif ("{%s}" % pname) in url:
                    path_request_params.append((pname, p))
                elif method == 'GET':
                    query_request_params.append((pname, p))
                else:
                    body_request_params.append((pname, p))

    params = [build_spec_param(n, p, "path") for (n, p) in path_request_params] \
           + [build_spec_param(n, p) for (n, p) in query_request_params]

    schema = None
    if body_request_params:
        schema = {
            "type": "object",
            "required": [n for (n, p) in body_request_params if bool(p.required)],
            "properties": {n: {"type": convert_type_to_spec(p.type)} for (n, p) in body_request_params}
        }

    request_body = {}
    if schema:
        request_body["application/json"] = {"schema": schema}
        request_body["multipart/form-data"] = {"schema": schema}

    if file_request_params:
        file_properties = {}
        for pname, p in file_request_params:
            file_properties[pname] = {"type": "array", "items": {"type": "string", "format": "binary"}}
        request_body.setdefault("multipart/form-data", {}).setdefault("schema", {})\
            .setdefault("properties", {}).update(file_properties)

    o = {"operationId": endpoint,
         "parameters": params,
         "responses": responses}
    if func.__doc__:
        o['description'] = func.__doc__
    if request_body:
        o["requestBody"] = {"content": request_body}
    return o


def build_spec_param(name, request_param, loc="query"):
    o = {"name": name,
        "schema": {"type": convert_type_to_spec(request_param.type)},
        "required": loc == "path" or bool(request_param.required),
        "in": loc}
    if request_param.help:
        o['description'] = request_param.help
    return o


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
