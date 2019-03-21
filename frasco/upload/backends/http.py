from frasco.upload.backend import StorageBackend, RemoteOpenStorageBackendMixin


class HttpStorageBackend(RemoteOpenStorageBackendMixin, StorageBackend):
    def url_for(self, filename, **kwargs):
        return 'http://' + filename
