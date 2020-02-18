from frasco.ext import *
from frasco.utils import import_class
from flask import send_from_directory
from flask.wrappers import Request
from werkzeug.datastructures import FileStorage
from io import BytesIO
from tempfile import TemporaryFile
import uuid
import os

from .backend import StorageBackend, split_backend_from_filename
from .utils import *


def _get_file_stream(self, total_content_length, content_type, filename=None, content_length=None):
    if total_content_length > 1024 * 500:
        return TemporaryFile('wb+', dir=os.environ.get('FRASCO_UPLOAD_TMP_DIR'))
    return BytesIO()

Request._get_file_stream = _get_file_stream


class FrascoUploadError(ExtensionError):
    pass


class FrascoUploadState(ExtensionState):
    def __init__(self, *args):
        super(FrascoUploadState, self).__init__(*args)
        self.backends = {}

    def _get_backend_options(self, name):
        options = dict(self.options)
        options.pop('backends', None)
        options.pop('backend', None) # make sure this key does not exists
        backend = name
        if name in self.options['backends']:
            if 'backend' in self.options['backends'][name]:
                options = self._get_backend_options(self.options['backends'][name]['backend'])
                backend = options['backend'] # make sure to keep the deepest level backend to resolve aliases properly
            options.update(self.options['backends'][name])
        options['backend'] = backend
        return options

    def get_backend(self, name=None):
        if isinstance(name, StorageBackend):
            return name
        if name is None:
            name = self.options['default_backend']
        if name not in self.backends:
            options = self._get_backend_options(name)
            backend_class = import_class(options['backend'], StorageBackend, "frasco.upload.backends")
            self.backends[name] = backend_class(name, options)
        return self.backends[name]


class FrascoUpload(Extension):
    name = 'frasco_upload'
    state_class = FrascoUploadState
    defaults = {"default_backend": "local",
                "backends": {},
                "upload_dir": "uploads",
                "upload_url": "/uploads",
                "upload_tmp_dir": None,
                "uuid_prefixes": True,
                "uuid_prefix_path_separator": False,
                "keep_filenames": True,
                "subfolders": False}

    def _init_app(self, app, state):
        app.add_template_global(url_for_upload)
        app.add_template_global(format_file_size)

        def send_uploaded_file(filename):
            return send_from_directory(os.path.abspath(state.options["upload_dir"]), filename)
        app.add_url_rule(state.options["upload_url"] + "/<path:filename>",
                         endpoint="static_upload",
                         view_func=send_uploaded_file)


def save_uploaded_file(file, filename=None, backend=None, **kwargs):
    state = get_extension_state('frasco_upload')
    return_filename_with_backend = kwargs.pop('return_filename_with_backend', False) or backend is True
    if not isinstance(file, FileStorage):
        file = FileStorage(file)
    if not filename:
        filename = generate_filename(file.filename, **kwargs)
    if not backend or backend is True:
        backend, filename = split_backend_from_filename(filename)
    state.get_backend(backend).save(file, filename)
    if return_filename_with_backend:
        return "%s://%s" % (backend or state.options['default_backend'], filename)
    return filename


def upload_stream(stream, filename, target_filename=None, **kwargs):
    return save_uploaded_file(FileStorage(stream, filename), target_filename, **kwargs)


def upload_file(pathname, filename=None, **kwargs):
    with open(pathname, 'rb') as f:
        return upload_stream(f, filename or pathname, **kwargs)


def delete_uploaded_file(filename, backend=None, **kwargs):
    if not backend:
        backend, filename = split_backend_from_filename(filename)
    get_extension_state('frasco_upload').get_backend(backend).delete(filename, **kwargs)


def url_for_upload(filename, backend=None, **kwargs):
    if not backend:
        backend, filename = split_backend_from_filename(filename)
    return get_extension_state('frasco_upload').get_backend(backend).url_for(filename, **kwargs)


def open_uploaded_file(filename, backend=None, **kwargs):
    if not backend:
        backend, filename = split_backend_from_filename(filename)
    return get_extension_state('frasco_upload').get_backend(backend).open(filename, **kwargs)
