import logging
import sqlalchemy
import datetime
from collections import OrderedDict
from .ext import db
from .utils import model_obj_to_dict, extract_model_attr_to_col_mapping


logger = logging.getLogger('frasco.models.serializer')


class DatabaseDictSerializer(object):
    remap_only_tables = None
    ignore_tables = None

    @classmethod
    def merge_idmaps(cls, idmap1, *idmaps):
        for idmap in idmaps:
            for table, rows in idmap1.items():
                rows.extend(idmap.get(table, []))
        return idmap1

    def __init__(self, keep_existing_fks=False):
        self.keep_existing_fks = keep_existing_fks

    def dump(self, obj, data=None, many=False, ignore_tables=None, follow_rels=True):
        data = {} if data is None else data
        ignore_tables = ignore_tables or []
        if obj is None:
            return data
        if many or isinstance(obj, list):
            for o in obj:
                self.dump(o, data, False, ignore_tables, follow_rels)
            return data
        if obj.__table__.name in ignore_tables:
            return data

        row = obj.__export_to_dict__(data) if hasattr(obj, '__export_to_dict__') else model_obj_to_dict(obj, value_serializer=self._dump_value)
        if row:
            data.setdefault(obj.__table__.name, []).append(row)

        if follow_rels and (isinstance(follow_rels, (list, tuple)) or hasattr(obj, '__export_follow_rels__') or \
          (isinstance(follow_rels, dict) and obj.__class__.__name__ in follow_rels)):
            mapper = sqlalchemy.inspect(obj.__class__)

            if isinstance(follow_rels, dict):
                obj_follow_rels = follow_rels[obj.__class__.__name__]
            elif isinstance(follow_rels, (list, tuple)):
                obj_follow_rels = follow_rels
            else:
                obj_follow_rels = obj.__export_follow_rels__

            for relattr in obj_follow_rels:
                rel_follow_rels = follow_rels if isinstance(follow_rels, dict) else True
                if isinstance(relattr, tuple):
                    relattr, rel_follow_rels = relattr
                attr = getattr(mapper.attrs, relattr, None)
                if attr and attr.secondary is not None:
                    data.setdefault(attr.secondary.name, [])
                    for r in db.session.query(attr.secondary).filter(attr.synchronize_pairs[0][1] == getattr(obj, attr.synchronize_pairs[0][0].name)):
                        data[attr.secondary.name].append({c.name: str(getattr(r, c.name)) for c in attr.secondary.columns})
                elif not attr or attr.target.name not in ignore_tables:
                    self.dump(getattr(obj, relattr), data, attr.uselist if attr else True, ignore_tables, rel_follow_rels)

        return data

    def dump_many(self, objs, data=None, **kwargs):
        kwargs['many'] = True
        return self.dump(objs, data, **kwargs)

    def dump_obj(self, obj):
        data = self.dump(obj, follow_rels=False)
        return data[obj.__table__.name][0]

    def _dump_value(self, value):
        return value

    def load(self, data, idmap=None):
        idmap = idmap or {}
        pre_insert_tables, tables_need_remap = self._get_tables_need_remap(data)

        for table in pre_insert_tables:
            for row in data.get(table.name, []):
                self._insert_without_fks(table, row, idmap)

        for table in tables_need_remap:
            for row in data.get(table.name, []):
                self.remap(table, row, idmap)

        return idmap

    def _get_tables_need_remap(self, data, remap_only_tables=None, ignore_tables=None):
        remap_only_tables = ((self.remap_only_tables or []) + (remap_only_tables or []))
        ignore_tables = set((self.ignore_tables or []) + (ignore_tables or []))
        all_tables = {name: self._get_table(name) for name in data.keys() if name not in ignore_tables}

        pre_insert_tables = [table for table in all_tables.values() if 'id' in table.c and table.name not in remap_only_tables]

        # use of OrderedDict for dedup while keeping ordering
        # keeping the order of remap_only_tables is important because remapping can depend on the order of insert
        tables_need_remap = OrderedDict([(name, all_tables[name]) for name in remap_only_tables if name in all_tables] \
                          + [(table.name, table) for table in all_tables.values() \
                                if len(self._get_foreign_cols(table)) > 0 or 'id' not in table.c])

        return pre_insert_tables, list(tables_need_remap.values())

    def _get_table(self, name):
        return db.Model.metadata.tables[name]

    def _get_foreign_cols(self, table):
        return [col.name for col in [col for col in table.c if col.foreign_keys]]

    def _validate_data(self, table, data):
        data = {k: v for k, v in data.items() if k in table.c}
        for col, value in data.items():
            if value is None and not table.c[col].nullable:
                logger.debug("%s: %s can't be null (%s)" % (table.name, col, data))
                return
        return data

    def _process_data(self, table, row, idmap, data):
        if 'id' in row and int(row['id']) in idmap.get(table.name, {}):
            # don't process unique values for rows already inserted
            return data
        return self._ensure_data_has_no_unique_conflict(table, data)

    def _ensure_data_has_no_unique_conflict(self, table, data):
        for col in [c for c in table.c if c.unique]:
            if not data.get(col.name):
                continue
            value = data[col.name]
            c = 1
            while db.session.query(table).filter(col==value).count() > 0:
                value = "%s-%s" % (data[col.name], c)
                c += 1
            data[col.name] = value
        return data

    def _insert_raw(self, table, oldid, data, idmap):
        newid = int(db.session.execute(table.insert().returning(table.c.id), data).scalar())
        idmap.setdefault(table.name, {})[int(oldid)] = newid
        return newid

    def _insert_without_fks(self, table, row, idmap):
        if 'id' not in row:
            return
        fks = self._get_foreign_cols(table)
        data = self._process_data(table, row, idmap,
            {k: v for k, v in row.items() if k != 'id' and k not in fks})

        data = self._validate_data(table, data)
        if data:
            newid = self._insert_raw(table, row['id'], data, idmap)
            logger.debug('insert(%s, %s -> %s, %s)' % (table.name, row['id'], newid, data))
            return newid

    def remap(self, table, row, idmap):
        if isinstance(table, str):
            table = self._get_table(table)
        fks = self._get_foreign_cols(table)
        alread_inserted = 'id' in row and int(row['id']) in idmap.get(table.name, {})

        if alread_inserted:
            # when data are already inserted, we are just remapping the foreign keys
            if not fks:
                return
            data = {}
        else:
            data = self._process_data(table, row, idmap,
                {k: v for k, v in row.items() if k != 'id' and k not in fks})

        for col in fks:
            if col not in row or not row[col]:
                continue
            target = list(table.c[col].foreign_keys)[0].column.table
            data[col] = self._mapid(idmap, target.name, int(row[col]))

        data = self._validate_data(table, data)
        if not data:
            return

        if alread_inserted:
            id = idmap.get(table.name, {})[int(row['id'])]
            logger.debug('remap_update(%s, %s -> %s, %s)' % (table.name, row['id'], id, data))
            db.session.execute(table.update().where(table.c.id==id).values(**data))
        else:
            if 'id' in row:
                newid = self._insert_raw(table, row['id'], data, idmap)
                logger.debug('remap_insert_id(%s, %s -> %s, %s)' % (table.name, row['id'], newid, data))
            else:
                logger.debug('remap_insert(%s, %s)' % (table.name, data))
                db.session.execute(table.insert(), data)

    def _mapid(self, idmap, tablename, id, keep_existing=None):
        if keep_existing is None:
            keep_existing = self.keep_existing_fks
        return idmap.get(tablename, {}).get(id, id if keep_existing else None)
