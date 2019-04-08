from contextlib import contextmanager
import requests
import tempfile


def split_backend_from_filename(filename):
    if '://' in filename:
        return filename.split('://', 1)
    return None, filename


class StorageBackend(object):
    default_options = None

    def __init__(self, name, options):
        self.name = name
        self.options = dict(self.default_options or {})
        self.options.update(options)

    def save(self, file, filename):
        raise NotImplementedError()

    def url_for(self, filename, **kwargs):
        raise NotImplementedError()

    def delete(self, filename):
        raise NotImplementedError()

    def open(self, filename):
        raise NotImplementedError()


class RemoteOpenStorageBackendMixin(object):
    @contextmanager
    def open(self, filename):
        with tempfile.TemporaryFile() as f:
            r = requests.get(self.url_for(filename))
            f.write(r.content)
            f.seek(0)
            yield f
