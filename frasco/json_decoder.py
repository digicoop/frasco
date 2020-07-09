from flask import json
import speaklater
import datetime


class JSONEncoder(json.JSONEncoder):
    """A JSONEncoder which always activates the for_json feature
    """
    def __init__(self, *args, **kwargs):
        kwargs["for_json"] = True
        super(JSONEncoder, self).__init__(*args, **kwargs)

    def default(self, o):
        if isinstance(o, speaklater._LazyString):
            return o.value
        if isinstance(o, (set, map)):
            return list(o)
        if isinstance(o, datetime.time):
            return str(o)
        return json.JSONEncoder.default(self, o)
