from frasco.upload.backend import StorageBackend
from frasco import current_app, url_for
from flask import safe_join
import os


class LocalStorageBackend(StorageBackend):
    def save(self, file, filename):
        filename = safe_join(os.path.abspath(self.options["upload_dir"]), filename)
        dirname = os.path.dirname(filename)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        file.save(filename)

    def url_for(self, filename, **kwargs):
        return url_for("static_upload", filename=filename, **kwargs)

    def delete(self, filename):
        filename = safe_join(os.path.abspath(self.options["upload_dir"]), filename)
        if os.path.exists(filename):
            os.unlink(filename)
