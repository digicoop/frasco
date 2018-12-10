import datetime


_translate_callback = None
_ntranslate_callback = None
_lazy_translate_callback = None
_format_datetime_callback = None
_format_date_callback = None
_format_time_callback = None


def set_translation_callbacks(translate=None, ntranslate=None, lazy_translate=None,\
    format_datetime=None, format_date=None, format_time=None):
    global _translate_callback, _ntranslate_callback, _lazy_translate_callback,\
        _format_datetime_callback, _format_date_callback, _format_time_callback
    _translate_callback = translate
    _ntranslate_callback = ntranslate
    _lazy_translate_callback = lazy_translate
    _format_datetime_callback = format_datetime
    _format_date_callback = format_date
    _format_time_callback = format_time


def _format_str(string, **kwargs):
    if kwargs:
        return string % kwargs
    return string


def translatable(string):
    # used to mark strings for extraction but no immediate translation
    return string


def translate(string, **kwargs):
    if _translate_callback:
        return _translate_callback(string, **kwargs)
    return _format_str(string, **kwargs)

_ = translate


def ntranslate(singular, plural, num, **kwargs):
    if _ntranslate_callback:
        return _ntranslate_callback(singular, plural, num, **kwargs)
    if "%(num)s" in singular:
        kwargs["num"] = num
    if num > 1:
        return _format_str(plural, **kwargs)
    return _format_str(singular, **kwargs)


def lazy_translate(string, **kwargs):
    if _lazy_translate_callback:
        return _lazy_translate_callback(string, **kwargs)
    from speaklater import make_lazy_string
    return make_lazy_string(translate, string, **kwargs)


def format_datetime(dt=None, format=None, **kwargs):
    if _format_datetime_callback:
        return _format_datetime_callback(dt, format, **kwargs)
    if not dt:
        dt = datetime.datetime.now()
    if not format:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt.strftime(format)


def format_date(d=None, format=None, **kwargs):
    if _format_date_callback:
        return _format_date_callback(d, format, **kwargs)
    if not d:
        d = datetime.date.today()
    if not format:
        return d.strftime("%Y-%m-%d")
    return d.strftime(format)


def format_time(t=None, format=None, **kwargs):
    if _format_time_callback:
        return _format_time_callback(t, format, **kwargs)
    if not t:
        t = datetime.time()
    if not format:
        return t.isoformat()
    return t.strftime(format)