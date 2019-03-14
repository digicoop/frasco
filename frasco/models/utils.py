from flask import current_app, abort
from frasco.utils import unknown_value
from sqlalchemy.ext.mutable import Mutable
from flask_sqlalchemy import Pagination
import uuid
import functools
from .ext import db


def move_obj_position_in_collection(obj, new_position, position_attr='position', scope=None, data=None, current_position=unknown_value):
    if not data:
        data = {}
    if current_position is unknown_value:
        current_position = getattr(obj, position_attr, None)
    shift, lower_idx, upper_idx = compute_move_obj_position_in_collection_bounds(current_position, new_position)
    position_col = getattr(obj.__class__, position_attr)

    q = obj.__class__.query
    if scope:
        q = q.filter_by(**scope)
    q = q.filter(position_col >= lower_idx, position_col <= upper_idx)
    q.update(dict(dict([(position_col.name, position_col + shift)]), **data))
    setattr(obj, position_attr, new_position)


def compute_move_obj_position_in_collection_bounds(current_position, new_position):
    if current_position is None:
        return 1, new_position, None
    up = new_position > current_position
    shift = -1 if up else 1
    lower_idx = min(current_position, new_position)
    lower_idx += 1 if up else 0
    upper_idx = max(current_position, new_position)
    upper_idx -= 0 if up else 1
    return shift, lower_idx, upper_idx


def ensure_unique_value(model, column, value, fallback=None, counter_start=1):
    if not fallback:
        fallback = value + "-%(counter)s"
    counter = counter_start
    q = model.query
    while q.filter_by(**dict([(column, value)])).count() > 0:
        value = fallback % {'counter': counter}
        counter += 1
    return value


def clone_sqla_obj(obj, propmapping=None):
    if not propmapping:
        propmapping = {}
    new = obj.__class__()
    for c in obj.__table__.columns:
        prop = propmapping.get(c.name, c.name)
        if prop == 'cache_id':
            new.cache_id = uuid.uuid4()
        elif prop != 'id' and hasattr(obj, prop):
            setattr(new, prop, getattr(obj, prop))
    return new


class MutableList(Mutable, list):
    def append(self, value):
        list.append(self, value)
        self.changed()

    def remove(self, value):
        list.remove(self, value)
        self.changed()

    @classmethod
    def coerce(cls, key, value):
        if not isinstance(value, MutableList):
            if isinstance(value, list):
                return MutableList(value)
            return Mutable.coerce(key, value)
        else:
            return value


def ensure_session_flushed(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        db.session.flush()
        return func(*args, **kwargs)
    return wrapper


def model_loader(model, nullable=False, *options, **options_kwargs):
    """Model loader of request params"""
    def loader(id):
        if id is None:
            if not nullable:
                abort(404)
            return None
        q = model.query
        for opt in options:
            q = q.options(opt)
        for item in options_kwargs.pop('joinedload', []):
            q = q.options(db.joinedload(item))
        for item in options_kwargs.pop('undefer', []):
            q = q.options(db.undefer_group(item))
        for method, value in options_kwargs.items():
            q = q.options(getattr(db, method)(value))
        return q.get_or_404(id)
    return loader
