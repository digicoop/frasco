

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
        raise NotImplementedError()

    def url_for(self, filename, **kwargs):
        raise NotImplementedError()

    def delete(self, filename):
        raise NotImplementedError()

