from frasco.upload.backend import StorageBackend


class HttpsStorageBackend(StorageBackend):
    def url_for(self, filename, **kwargs):
        return 'https://' + filename
