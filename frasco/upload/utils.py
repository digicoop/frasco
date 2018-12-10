import mimetypes
from werkzeug import FileStorage, secure_filename
from StringIO import StringIO
from frasco.ext import get_extension_state
from tempfile import NamedTemporaryFile, gettempdir
import os
import uuid


__all__ = ('StringFileStorage', 'generate_filename', 'save_uploaded_file_temporarly', 'file_size', 'format_file_size')


mimetypes.init()


class StringFileStorage(FileStorage):
    def __init__(self, data, filename, mimetype=None, **kwargs):
        super(StringFileStorage, self).__init__(StringIO(data), filename, **kwargs)
        if mimetype is None:
            mimetype = mimetypes.guess_type(filename)[0]
        self._mimetype = mimetype

    @property
    def mimetype(self):
        return self._mimetype


def generate_filename(filename, uuid_prefix=None, uuid_prefix_path_separator=None, keep_filename=None,
                      subfolders=None, backend=None):

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
        filename = secure_filename(filename)
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
        tmpfilename = os.path.join(tmp_dir or gettempdir(), secure_filename(filename))
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
