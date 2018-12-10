from flask_sqlalchemy import SQLAlchemy, Model as BaseModel, SignallingSession
from flask_migrate import Migrate
from frasco.ext import get_extension_config
from frasco.utils import inject_app_config
from sqlalchemy import event
import datetime
from flask import current_app


class Model(BaseModel):
    def __taskdump__(self):
        return None, str(self.id)

    @classmethod
    def __taskload__(cls, id):
        return cls.query.get(id)


class FrascoModels(SQLAlchemy):
    name = "frasco_models"

    def __init__(self, *args, **kwargs):
        kwargs['model_class'] = Model
        kwargs.setdefault('session_options', {}).setdefault('expire_on_commit', False)
        super(FrascoModels, self).__init__(*args, **kwargs)

    def init_app(self, app):
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        inject_app_config(app, get_extension_config(app, 'frasco_models'), prefix="SQLALCHEMY_")
        super(FrascoModels, self).init_app(app)
        self.migrate = Migrate(app, self)


db = FrascoModels()


@event.listens_for(SignallingSession, "before_flush")
def before_flush(session, flush_context=None, instances=None):
    for obj in session.dirty:
        if (not hasattr(obj, 'clear_cache') and not hasattr(obj, 'updated_at')) or not session.is_modified(obj):
            continue
        if hasattr(obj, 'updated_at'):
            obj.updated_at = datetime.datetime.utcnow()
        if hasattr(obj, 'clear_cache'):
            obj.clear_cache()
