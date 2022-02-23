from flask import json
import speaklater
import datetime


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, speaklater._LazyString):
            return o.value
        if isinstance(o, (set, map)):
            return list(o)
        if isinstance(o, datetime.time):
            return str(o)
        return json.JSONEncoder.default(self, o)
