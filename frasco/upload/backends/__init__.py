from frasco import current_app, url_for
from flask import safe_join
import os


__all__ = ('UPLOAD_BACKENDS', 'register_upload_backend', 'StorageBackend', 'split_backend_from_filename')


UPLOAD_BACKENDS = {}


def register_upload_backend(cls):
    UPLOAD_BACKENDS[cls.name] = cls
    return cls


def split_backend_from_filename(filename):
    if '://' in filename:
        return filename.split('://', 1)
    return None, filename


class StorageBackend(object):
    default_options = None

    def __init__(self, options):
        self.options = dict(self.default_options or {})
        self.options.update(options)

    def save(self, file, filename):
        raise NotImplementedError

    def url_for(self, filename, **kwargs):
        raise NotImplementedError

    def delete(self, filename):
        raise NotImplementedError


@register_upload_backend
class LocalStorageBackend(StorageBackend):
    name = 'local'

    def save(self, file, filename):
        filename = safe_join(self.options["upload_dir"], filename)
        if not os.path.isabs(filename):
            filename = os.path.join(current_app.root_path, filename)
        dirname = os.path.dirname(filename)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        file.save(filename)

    def url_for(self, filename, **kwargs):
        return url_for("static_upload", filename=filename, **kwargs)

    def delete(self, filename):
        filename = safe_join(self.options["upload_dir"], filename)
        if not os.path.isabs(filename):
            filename = os.path.join(current_app.root_path, filename)
        if os.path.exists(filename):
            os.unlink(filename)


@register_upload_backend
class HttpStorageBackend(StorageBackend):
    name = 'http'

    def url_for(self, filename, **kwargs):
        return 'http://' + filename


@register_upload_backend
class HttpsStorageBackend(StorageBackend):
    name = 'https'

    def url_for(self, filename, **kwargs):
        return 'https://' + filename
