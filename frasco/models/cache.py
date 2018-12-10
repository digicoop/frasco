from .ext import db
import uuid


class CachableModelMixin(object):
    cache_id = db.Column(db.String, default=uuid.uuid4)

    def clear_cache(self):
        self.cache_id = str(uuid.uuid4())
