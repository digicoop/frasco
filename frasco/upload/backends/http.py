from frasco.upload.backend import StorageBackend


class HttpStorageBackend(StorageBackend):
    def url_for(self, filename, **kwargs):
        return 'http://' + filename
