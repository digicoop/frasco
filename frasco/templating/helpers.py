from jinja2 import Markup, evalcontextfilter
import re
import ago


__all__ = ('html_tag', 'html_attributes', 'nl2br', 'timeago', 'plural')


def html_tag(tagname, attrs=None, **kwargs):
    html_attrs = html_attributes(attrs, **kwargs)
    return Markup("<%s%s>" % (tagname, " " + html_attrs if html_attrs else ""))


def html_attributes(attrs=None, **kwargs):
    attrs = dict(attrs or {})
    attrs.update(kwargs)
    html = []
    for k, v in attrs.items():
        if v is None:
            continue
        if k.endswith('_'):
            k = k[:-1]
        if isinstance(v, bool):
            v = k if v else ""
        k = k.replace("_", "-")
        html.append(u'%s="%s"' % (k, unicode(v).strip()))
    return Markup(" ".join(html))


_paragraph_re = re.compile(r'(?:\r\n|\r(?!\n)|\n){2,}')

@evalcontextfilter
def nl2br(eval_ctx, value):
    result = u'\n\n'.join(u'<p>%s</p>' % p.replace(u'\n', Markup('<br>\n'))
                                         for p in _paragraph_re.split(value))
    if eval_ctx.autoescape:
        result = Markup(result)
    return result


def timeago(dt, **args):
    return ago.human(dt, **args)


def plural(singular, plural, num):
    if num > 1:
        return plural
    return singular
