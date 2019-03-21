from frasco.upload.backend import StorageBackend
from frasco.helpers import url_for
from flask import safe_join, current_app
from contextlib import contextmanager
import os


class LocalStorageBackend(StorageBackend):
    def _filename(self, filename):
        return safe_join(os.path.abspath(self.options["upload_dir"]), filename)

    def save(self, file, filename):
        filename = self._filename(filename)
        dirname = os.path.dirname(filename)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        file.save(filename)

    def url_for(self, filename, **kwargs):
        kwargs.setdefault('_external', True)
        return url_for("static_upload", filename=filename, **kwargs)

    def delete(self, filename):
        filename = self._filename(filename)
        if os.path.exists(filename):
            os.unlink(filename)

    @contextmanager
    def open(self, filename):
        with open(self._filename(filename), 'rb') as f:
            yield f
