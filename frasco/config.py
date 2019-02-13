from flask import json
from flask.config import Config as FlaskConfig
from frasco.utils import deep_update_dict
import os
import yaml
import errno


class Config(FlaskConfig):
    """Subclass of Flask's Config class to add support to load from YAML file
    """

    def from_json(self, filename, silent=False, deep_update=False):
        filename = os.path.join(self.root_path, filename)

        try:
            with open(filename) as json_file:
                obj = json.loads(json_file.read())
        except IOError as e:
            if silent and e.errno in (errno.ENOENT, errno.EISDIR):
                return False
            e.strerror = 'Unable to load configuration file (%s)' % e.strerror
            raise
        return self.from_mapping(obj, _deep_update=deep_update)

    def from_yaml(self, filename, silent=False, deep_update=False):
        filename = os.path.join(self.root_path, filename)

        try:
            with open(filename) as yaml_file:
                obj = yaml.safe_load(yaml_file.read())
        except IOError as e:
            if silent and e.errno in (errno.ENOENT, errno.EISDIR):
                return False
            e.strerror = 'Unable to load configuration file (%s)' % e.strerror
            raise
        return self.from_mapping(obj, _deep_update=deep_update)

    def from_mapping(self, *mapping, **kwargs):
        mappings = []
        if len(mapping) == 1:
            if hasattr(mapping[0], 'items'):
                mappings.append(mapping[0].items())
            else:
                mappings.append(mapping[0])
        elif len(mapping) > 1:
            raise TypeError(
                'expected at most 1 positional argument, got %d' % len(mapping)
            )
        deep_update = kwargs.pop('_deep_update', False)
        mappings.append(kwargs.items())
        for mapping in mappings:
            if deep_update:
                deep_update_dict(self, dict((k.upper(), v) for (k, v) in mapping))
            else:
                for (key, value) in mapping:
                    self[key.upper()] = value
        return True

    def from_file(self, filename, silent=False, deep_update=False):
        if filename.endswith(".py"):
            self.from_pyfile(filename, silent=silent)
        elif filename.endswith(".js") or filename.endswith(".json"):
            self.from_json(filename, silent=silent, deep_update=deep_update)
        elif filename.endswith(".yml"):
            self.from_yaml(filename, silent=silent, deep_update=deep_update)
        else:
            raise RuntimeError("Unknown config file extension")

    def resolve_includes(self, relative_to=".", key="INCLUDE_FILES"):
        for spec in self.pop(key, []):
            if not isinstance(spec, dict):
                spec = {"filename": spec}
            filename = os.path.join(relative_to, spec["filename"])
            self.from_file(filename, silent=spec.get("silent", False),
                deep_update=spec.get("deep_update", False))


def load_config(app, config_filename='config.yml', env=None, root_path=None):
    if not root_path:
        root_path = app.root_path
    config_path = os.path.join(root_path, config_filename)
    app.config.from_yaml(config_path, silent=True)
    env = env or app.config['ENV']
    filename, ext = os.path.splitext(config_path)
    env_filename = filename + "-" + env + ext
    app.config.from_yaml(env_filename, silent=True, deep_update=True)
    app.config.resolve_includes(root_path)
