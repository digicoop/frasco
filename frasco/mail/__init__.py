from flask import g, current_app
from frasco.ext import *
from frasco.ctx import ContextStack
from frasco.tasks import enqueue_task
from frasco.templating.extensions import RemoveYamlFrontMatterExtension
from jinja_macro_tags import MacroLoader, MacroRegistry
from flask_mail import Mail, email_dispatched
from jinja2 import ChoiceLoader, FileSystemLoader, PackageLoader
from contextlib import contextmanager
import os
import datetime

try:
    from cpickle import pickle
except ImportError:
    import pickle

from .message import create_message, clickable_links, log_message


bulk_connection_context = ContextStack()


class FrascoMailError(Exception):
    pass


class FrascoMailState(ExtensionState):
    def __init__(self, *args):
        super(FrascoMailState, self).__init__(*args)
        self.template_loaders = []
        layout_loader = PackageLoader(__name__, "templates")
        self.jinja_loader = MacroLoader(ChoiceLoader([ChoiceLoader(self.template_loaders), layout_loader]))
        self.jinja_env = None
        self.connection = None

    def add_template_folder(self, path):
        self.template_loaders.append(FileSystemLoader(path))

    def add_templates_from_package(self, pkg_name, pkg_path="emails"):
        self.template_loaders.append(PackageLoader(pkg_name, pkg_path))


class FrascoMail(Extension):
    """Send emails using SMTP
    """
    name = "frasco_mail"
    state_class = FrascoMailState
    prefix_extra_options = "MAIL_"
    defaults = {"default_layout": "layout.html",
                "default_template_vars": {},
                "inline_css": False,
                "auto_render_missing_content_type": True,
                "log_messages": None, # default is app.testing
                "dumped_messages_folder": "email_logs",
                "localized_emails": None,
                "default_locale": None,
                "markdown_options": {},
                "silent_failures": False,
                "send_async": False}

    def _init_app(self, app, state):
        state.client = Mail(app)
        state.connection = None

        state.add_template_folder(os.path.join(app.root_path, "emails"))
        state.jinja_env = app.jinja_env.overlay(loader=state.jinja_loader)
        state.jinja_env.add_extension(RemoveYamlFrontMatterExtension)
        state.jinja_env.macros = MacroRegistry(state.jinja_env) # the overlay methods does not call the constructor of extensions
        state.jinja_env.macros.register_from_template("layouts/macros.html")
        state.jinja_env.default_layout = state.options["default_layout"]
        state.jinja_env.filters['clickable_links'] = clickable_links

        if (state.options["log_messages"] is not None and state.options["log_messages"]) or \
            (state.options["log_messages"] is None and app.testing):
            email_dispatched.connect(lambda msg, app: log_message(msg, app, state.options['dumped_messages_folder']), weak=False)

        if has_extension('frasco_babel', app):
            if state.options['default_locale'] is None:
                state.options['default_locale'] = app.extensions.frasco_babel.options['default_locale']
            if state.options['localized_emails'] is None:
                state.options['localized_emails'] = '{locale}/{filename}'


def send_message(msg):
    state = get_extension_state('frasco_mail')
    try:
        if bulk_connection_context.top:
            bulk_connection_context.top.send(msg)
        else:
            state.client.send(msg)
    except Exception as e:
        if not state.options['silent_failures']:
            raise e
        current_app.log_exception(e)


def send_message_async(msg):
    require_extension('frasco_tasks')
    enqueue_task(send_message, msg=msg)


def send_mail(to, template_filename, *args, **kwargs):
    state = get_extension_state('frasco_mail')
    force_sync = kwargs.pop('_force_sync', False)
    msg = create_message(to, template_filename, *args, **kwargs)
    if msg:
        if has_extension('tasks') and state.options['send_async'] and not force_sync:
            send_message_async(msg)
        else:
            send_message(msg)


@contextmanager
def bulk_mail_connection():
    state = get_extension_state('frasco_mail')
    try:
        connection = state.client.connect()
        # simulate entering a with context
        # (flask-mail does not provide a way to connect otherwise)
        connection.__enter__()
    except Exception as e:
        if not state.options['silent_failures']:
            raise e
        current_app.log_exception(e)
        connection = DummyBulkConnection()
    bulk_connection_context.push(connection)
    try:
        yield connection
    finally:
        bulk_connection_context.top.__exit__(None, None, None)
        bulk_connection_context.pop()


class DummyBulkConnection(object):
    def send(self, *args, **kwargs):
        pass

    def __exit__(self, *args):
        pass
