from flask import json
from flask.config import Config as FlaskConfig
from frasco.utils import deep_update_dict
import os
import yaml
import errno
import logging


logger = logging.getLogger('frasco')


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

    def from_file(self, filename, **kwargs):
        if filename.endswith(".py"):
            return self.from_pyfile(filename, **kwargs)
        if filename.endswith(".js") or filename.endswith(".json"):
            return self.from_json(filename, **kwargs)
        if filename.endswith(".yml") or filename.endswith(".yaml"):
            return self.from_yaml(filename, **kwargs)
        raise RuntimeError("Unknown config file extension")


def load_config(app, config_filename='config.yml', env=None, deep_update=False):
    if os.path.exists(config_filename):
        logger.info('Loading config from %s' % config_filename)
        app.config.from_file(config_filename, deep_update=deep_update)
    if env is False:
        return
    env = env or app.config['ENV']
    filename, ext = os.path.splitext(config_filename)
    env_filename = filename + "-" + env + ext
    if os.path.exists(env_filename):
        logger.info('Loading config from %s' % env_filename)
        app.config.from_file(env_filename, deep_update=True)


def update_config_with_env_vars(app, prefix):
    config = {}
    prefix = prefix.upper()
    for k, v in os.environ.iteritems():
        if k.startswith(prefix + "_"):
            config[k[len(prefix)+1:]] = v
    if config:
        logger.info('Using config from environment variables')
        app.config.update(config)
