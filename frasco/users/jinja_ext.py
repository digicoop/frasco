from jinja2 import nodes
from jinja2.ext import Extension
from frasco.templating import jinja_fragment_extension

from .user import current_user


__all__ = ('LoginRequiredExtension', 'AnonymousOnlyExtension')


class LoginRequiredExtension(Extension):
    """Jinja extension that adds a {% login_required %}{% endlogin %} block.
    The content will only be outputted if the user is logged in. Also accepts
    an {% else %} block which will be called when the user is not logged in.
    Example:
       {% login_required %}Hello {% current_user.name %}{% else %}Please login{% endlogin %}
    """
    tags = set(['login_required'])
    
    def parse(self, parser):
        lineno = parser.stream.next().lineno
        body = parser.parse_statements(['name:else', 'name:endlogin'])
        token = next(parser.stream)
        if token.test('name:else'):
            else_ = parser.parse_statements(['name:endlogin'], drop_needle=True)
        else:
            else_ = []

        test = nodes.Getattr(nodes.Name("current_user", "load", lineno=lineno), \
                    "is_authenticated", "load", lineno=lineno)

        return nodes.If(test, body, [], else_, lineno=lineno)


@jinja_fragment_extension("anonymous_only", endtag="endanon")
def AnonymousOnlyExtension(caller):
    if not current_user.is_authenticated():
        return caller()
    return ""
