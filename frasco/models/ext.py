from flask_sqlalchemy import SQLAlchemy, Model as BaseModel
from flask_migrate import Migrate
from frasco.ext import get_extension_config
from frasco.helpers import inject_app_config


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

