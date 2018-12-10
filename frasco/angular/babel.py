from jinja2.ext import Extension
import re


class AngularCompatExtension(Extension):
    """Jinja extension that does the bare minimum into making angular templates
    parsable by Jinja so gettext strings can be extacted.
    Removes angular one-time binding indicators and javascript ternary operator.
    """
    special_chars_re = re.compile(r"'[^']*'|\"[^\"]+\"|(\{[^{]+\}|[?:!&|$=]{1,3})")
    replacements = {'!': ' not ', '$': '', '=': '=', '==': '==',
                    '===': '==', '!=': '!=', '!==': '!=', '&&': ' and ', '||': ' or '}

    def process_expression(self, source, start):
        p = start
        end = p
        while True:
            end = source.find('}}', p)
            m = self.special_chars_re.search(source, p, end)
            if not m:
                break
            if m.group(1) is None:
                p = m.end(0)
                continue
            if m.group(1).startswith('{'):
                repl = 'True'
            else:
                repl = self.replacements.get(m.group(1), ' or ')
            p = m.start(1) + len(repl)
            source = source[:m.start(1)] + repl + source[m.end(1):]
        return source, end + 2

    def preprocess(self, source, name, filename=None):
        source = source.replace('{{::', '{{')
        p = 0
        while True:
            p = source.find('{{', p)
            if p == -1:
                break
            source, p = self.process_expression(source, p + 2)
        return source
