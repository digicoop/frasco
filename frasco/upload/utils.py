import mimetypes
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename as wz_secure_filename
from io import StringIO, BytesIO
from frasco.ext import get_extension_state
from tempfile import NamedTemporaryFile, gettempdir
import os
import uuid


__all__ = ('BytesFileStorage', 'StringFileStorage', 'generate_filename', 'save_uploaded_file_temporarly', 'file_size', 'format_file_size')


mimetypes.init()


class BytesFileStorage(FileStorage):
    def __init__(self, data, filename, mimetype=None, io_class=BytesIO, **kwargs):
        super().__init__(io_class(data), filename, **kwargs)
        if mimetype is None:
            try:
                mimetype = mimetypes.guess_type(filename)[0]
            except:
                pass
        self._mimetype = mimetype

    @property
    def mimetype(self):
        return self._mimetype


class StringFileStorage(BytesFileStorage):
    def __init__(self, data, filename, mimetype=None, **kwargs):
        kwargs['io_class'] = StringIO
        super().__init__(data, filename, mimetype, **kwargs)


def generate_filename(filename, uuid_prefix=None, uuid_prefix_path_separator=None, keep_filename=None,
                      subfolders=None, backend=None, secure_filename=True):

    state = get_extension_state('frasco_upload', must_exist=False)
    if state:
        if uuid_prefix is None:
            uuid_prefix = state.options["uuid_prefixes"]
        if keep_filename is None:
            keep_filename = state.options["keep_filenames"]
        if subfolders is None:
            subfolders = state.options["subfolders"]
        if uuid_prefix_path_separator is None:
            uuid_prefix_path_separator = state.options["uuid_prefix_path_separator"]

    if uuid_prefix and not keep_filename:
        _, ext = os.path.splitext(filename)
        filename = str(uuid.uuid4()) + ext
    else:
        if secure_filename:
            filename = wz_secure_filename(filename)
        if uuid_prefix:
            filename = str(uuid.uuid4()) + ("/" if uuid_prefix_path_separator else "-") + filename

    if subfolders:
        if uuid_prefix:
            parts = filename.split("-", 4)
            filename = os.path.join(os.path.join(*parts[:4]), filename)
        else:
            filename = os.path.join(os.path.join(*filename[:4]), filename)

    if backend:
        if backend is True:
            backend = state.options['default_backend'] if state else None
        if backend:
            filename = backend + '://' + filename

    return filename


def save_uploaded_file_temporarly(file, filename=None, tmp_dir=None):
    state = get_extension_state('frasco_upload', must_exist=False)
    if not tmp_dir:
        tmp_dir = state.options.get('upload_tmp_dir') if state else None
    if filename:
        tmpfilename = os.path.join(tmp_dir or gettempdir(), wz_secure_filename(filename))
    else:
        _, ext = os.path.splitext(file.filename)
        tmp = NamedTemporaryFile(delete=False, suffix=ext, dir=tmp_dir)
        tmp.close()
        tmpfilename = tmp.name
    file.save(tmpfilename)
    return tmpfilename


def file_size(file):
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    return size


def format_file_size(size, suffix='B'):
    for unit in ['','K','M','G','T','P','E','Z']:
        if abs(size) < 1024.0:
            return "%3.1f%s%s" % (size, unit, suffix)
        size /= 1024.0
    return "%.1f%s%s" % (size, 'Y', suffix)
