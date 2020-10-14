from flask import g, current_app
from frasco.ext import get_extension_state
from frasco.utils import remove_yaml_frontmatter
from flask_mail import Message, Attachment
from jinja2 import TemplateNotFound
import yaml
import os
import markdown
import premailer
import re
import datetime
import logging

try:
    # html2text being licensed under the GPL, it is not
    # directly included and may be not available
    import html2text
except ImportError:
    html2text = None


__all__ = ('render_message', 'create_message', 'log_message')


def get_template_source(template_filename, locale=None):
    state = get_extension_state('frasco_mail')
    filename, ext = os.path.splitext(template_filename)

    localized_filename = None
    if state.options['localized_emails']:
        if locale is None and 'current_locale' in g:
            locale = g.current_locale
        if locale and locale != state.options['default_locale']:
            localized_filename = state.options['localized_emails'].format(**{
                "locale": locale, "filename": template_filename,
                "name": filename, "ext": ext})

    source = None
    for tpl_filename in [localized_filename, template_filename]:
        if not tpl_filename:
            continue
        filename, ext = os.path.splitext(tpl_filename)
        auto_ext = not ext
        if auto_ext:
            ext = ".md,html,txt"
        for source_filename in ["%s.%s" % (filename, e) for e in ext[1:].split(",")]:
            try:
                source, _, __ = state.jinja_env.loader.get_source(state.jinja_env, source_filename)
            except TemplateNotFound:
                continue
            if source:
                return tpl_filename, source

    raise TemplateNotFound(template_filename)


def render_message(template_filename, vars=None, auto_render_missing_content_type=None,
                   auto_html_layout="layouts/text.html", auto_markdown_template="layouts/markdown.html",
                   **kwargs_vars):

    state = get_extension_state('frasco_mail')
    text_body = None
    html_body = None
    vars = vars or {}
    vars.update(kwargs_vars)

    template_filename, source = get_template_source(template_filename, vars.get('locale'))
    source, frontmatter_source = remove_yaml_frontmatter(source, True)
    frontmatter = None
    if frontmatter_source:
        frontmatter = yaml.safe_load(re.sub("^---\n", "", frontmatter_source))
        if frontmatter:
            for k, v in frontmatter.items():
                vars.setdefault(k, state.jinja_env.from_string(v).render(**vars))

    filename, ext = os.path.splitext(template_filename)
    auto_ext = not ext
    if auto_ext:
        ext = ".md,html,txt"
    templates = [("%s.%s" % (filename, e), e) for e in ext[1:].split(",")]
    for tpl_filename, ext in templates:
        try:
            rendered = state.jinja_env.get_template(tpl_filename).render(**vars)
        except TemplateNotFound:
            if not auto_ext:
                raise
            continue
        if ext == "html":
            html_body = rendered
        elif ext == "txt":
            text_body = rendered
        elif ext == "md":
            text_body = rendered
            content = markdown.markdown(rendered, **state.options["markdown_options"])
            html_body = state.jinja_env.get_template(auto_markdown_template).render(
                content=content, **vars)
        if auto_ext and html_body and text_body:
            break

    if (auto_render_missing_content_type is not None and auto_render_missing_content_type) or \
        (auto_render_missing_content_type is None and state.options["auto_render_missing_content_type"]):
        if html_body is None:
            html_body = state.jinja_env.get_template(auto_html_layout).render(
                text_body=text_body, **vars)
        if text_body is None and html2text is not None:
            text_body = html2text.html2text(html_body)

    if html_body and state.options["inline_css"]:
        html_body = premailer.transform(html_body)

    return (frontmatter, vars, text_body, html_body)


def create_message(to, tpl, **kwargs):
    recipients = to if isinstance(to, (list, tuple)) else [to]
    frontmatter, vars, text_body, html_body = render_message(tpl, **kwargs)

    kwargs = {}
    for k in ('subject', 'sender', 'cc', 'bcc', 'attachments', 'reply_to', 'send_date', 'charset', 'extra_headers'):
        if k in vars:
            kwargs[k] = vars[k]
        elif frontmatter and k in frontmatter:
            kwargs[k] = frontmatter[k]
    kwargs["date"] = kwargs.pop("send_date", None)

    if not kwargs.get("subject"):
        raise ValueError("Missing subject for email with template '%s'" % tpl)
    subject = kwargs.pop("subject")
    attachments = kwargs.pop("attachments", None)

    msg = Message(recipients=recipients, subject=subject, body=text_body, html=html_body, **kwargs)
    msg.template = tpl

    if attachments:
        for attachment in attachments:
            if isinstance(attachment, Attachment):
                msg.attachments.append(attachment)
            elif isinstance(attachment, dict):
                msg.attach(**attachment)
            else:
                msg.attach(attachment)

    return msg


def log_message(message, dump_dir=None, connection=None):
    logging.getLogger('frasco.mail').info("Email %s sent to %s from %s titled \"%s\" via connection %s" % (
        getattr(message, 'template', '[no template]'), message.recipients, message.sender, message.subject, str(connection) or "?"))
    if dump_dir:
        if not os.path.exists(dump_dir):
            os.mkdir(dump_dir, 0o777)
        filename = os.path.join(dump_dir, "-".join([
            datetime.datetime.now().isoformat("-"),
            os.path.splitext(getattr(message, 'template', ''))[0].replace("/", "_"),
                "-".join(message.recipients)]))
        if message.body:
            with open(filename + ".txt", "w") as f:
                f.write(message.body)
        if message.html:
            with open(filename + ".html", "w") as f:
                f.write(message.html)


_url_regexp = re.compile(r'(http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+)')
def clickable_links(text):
    return _url_regexp.sub(r'<a href="\1">\1</a>', text)
