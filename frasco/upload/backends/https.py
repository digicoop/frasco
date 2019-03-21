from frasco.upload.backend import StorageBackend, RemoteOpenStorageBackendMixin


class HttpsStorageBackend(RemoteOpenStorageBackendMixin, StorageBackend):
    def url_for(self, filename, **kwargs):
        return 'https://' + filename
