from jinja2 import nodes
from jinja2.ext import Extension
from flask import get_flashed_messages
from ..utils import remove_yaml_frontmatter


__all__ = ('jinja_fragment_extension', 'jinja_block_as_fragment_extension', 'FlashMessagesExtension')


def parse_block_signature(parser):
    args = []
    kwargs = []
    require_comma = False

    while parser.stream.current.type != 'block_end':
        if require_comma:
            parser.stream.expect('comma')
            # support for trailing comma
            if parser.stream.current.type == 'block_end':
                break
        if parser.stream.current.type == 'name' and \
           parser.stream.look().type == 'assign':
            key = parser.stream.current.value
            parser.stream.skip(2)
            value = parser.parse_expression()
            kwargs.append(nodes.Keyword(key, value,
                                        lineno=value.lineno))
        else:
            args.append(parser.parse_expression())
        require_comma = True

    return args, kwargs


def jinja_fragment_extension(tag, endtag=None, name=None, tag_only=False, allow_args=True, callblock_args=None):
    """Decorator to easily create a jinja extension which acts as a fragment.
    """
    if endtag is None:
        endtag = "end" + tag

    def decorator(f):
        def parse(self, parser):
            lineno = parser.stream.next().lineno
            args = []
            kwargs = []
            if allow_args:
                args, kwargs = parse_block_signature(parser)

            call = self.call_method("support_method", args, kwargs, lineno=lineno)
            if tag_only:
                return nodes.Output([call], lineno=lineno)

            call_args = []
            if callblock_args is not None:
                for arg in callblock_args:
                    call_args.append(nodes.Name(arg, 'param', lineno=lineno))

            body = parser.parse_statements(['name:' + endtag], drop_needle=True)
            return nodes.CallBlock(call, call_args, [], body, lineno=lineno)

        def support_method(self, *args, **kwargs):
            return f(*args, **kwargs)

        attrs = {"tags": set([tag]), "parse": parse, "support_method": support_method}
        return type(name or f.__name__, (Extension,), attrs)

    return decorator


class BaseJinjaBlockAsFragmentExtension(Extension):
    def parse(self, parser):
        lineno = parser.stream.next().lineno
        body = parser.parse_statements(['name:' + self.end_tag], drop_needle=True)
        return nodes.Block(self.block_name, body, False, lineno=lineno)


def jinja_block_as_fragment_extension(name, tagname=None, classname=None):
    """Creates a fragment extension which will just act as a replacement of the
    block statement.
    """
    if tagname is None:
        tagname = name
    if classname is None:
        classname = "%sBlockFragmentExtension" % name.capitalize()
    return type(classname, (BaseJinjaBlockAsFragmentExtension,), {
        "tags": set([tagname]), "end_tag": "end" + tagname, "block_name": name})


class RemoveYamlFrontMatterExtension(Extension):
    """Jinja extension to remove YAML front-matters
    """
    def preprocess(self, source, name, filename=None):
        before = ""
        if source.startswith("{% load_macro"):
            before, source = source.split("\n", 1)
        return before + remove_yaml_frontmatter(source)


@jinja_fragment_extension("flash_messages", endtag="endflash", allow_args=False,
                          callblock_args=["message", "category"])
def FlashMessagesExtension(caller=None):
    messages = get_flashed_messages(with_categories=True)
    html = ""
    if messages:
        for cat, msg in messages:
            html += caller(msg, cat)
    return html
