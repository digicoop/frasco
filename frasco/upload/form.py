from wtforms import FileField as BaseFileField, ValidationError
from flask_wtf.file import FileRequired
from werkzeug.datastructures import FileStorage
from frasco.ext import get_extension_state
import os
import uuid

from .utils import generate_filename, file_size


class FileField(BaseFileField):
    def __init__(self, label=None, validators=None, auto_save=True, upload_dir=None, upload_backend=None,\
                 uuid_prefix=None, keep_filename=None, subfolders=None, backend_in_filename=True,
                 save_original_filename=None, save_file_size=None, save_mimetype=None, **kwargs):
        super(FileField, self).__init__(label, validators, **kwargs)
        self.file = None
        self.auto_save = auto_save
        self.upload_dir = upload_dir
        self._upload_backend = upload_backend
        self.uuid_prefix = uuid_prefix
        self.keep_filename = keep_filename
        self.subfolders = subfolders
        self.backend_in_filename = backend_in_filename
        self.save_original_filename = save_original_filename
        self.save_file_size = save_file_size
        self.save_mimetype = save_mimetype

    @property
    def upload_backend(self):
        return get_extension_state('frasco_upload').get_backend(self._upload_backend)

    def process_formdata(self, valuelist):
        if not valuelist:
            return
        self.file = valuelist[0]
        self.data = None
        self.filename = None
        if not self.has_file():
            return

        self.filename = generate_filename(self.file.filename,
            self.uuid_prefix, self.keep_filename, self.subfolders)
        if self.upload_dir:
            self.filename = os.path.join(self.upload_dir, self.filename)
        if self.backend_in_filename:
            self.data = self._upload_backend + '://' + self.filename
        else:
            self.data = self.filename

        if self.auto_save:
            self.save_file()

    @property
    def file_size(self):
        return file_size(self.file)

    def save_file(self):
        self.upload_backend.save(self.file, self.filename)

    def has_file(self):
        # compatibility with Flask-WTF
        if not isinstance(self.file, FileStorage):
            return False
        return self.file.filename not in [None, '', '<fdopen>']

    def populate_obj(self, obj, name):
        setattr(obj, name, self.data)
        if self.save_original_filename:
            setattr(obj, self.save_original_filename, self.file.filename)
        if self.save_file_size:
            setattr(obj, self.save_file_size, self.file_size)
        if self.save_mimetype:
            setattr(obj, self.save_mimetype, self.file.mimetype)


class FileAllowed(object):
    def __init__(self, extensions, message=None):
        self.extensions = extensions
        self.message = message

    def __call__(self, form, field):
        if not field.has_file():
            return

        filename = field.file.filename.lower()
        ext = filename.rsplit('.', 1)[-1]
        if ext in self.extensions:
            return

        message = self.message
        if message is None:
            message = field.gettext("File type not allowed")
        raise ValidationError(message)
