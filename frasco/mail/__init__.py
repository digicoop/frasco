from flask import g, current_app
from flask.signals import Namespace
from frasco.ext import *
from frasco.models import delayed_tx_calls
from frasco.tasks import enqueue_task
from frasco.templating.extensions import RemoveYamlFrontMatterExtension
from frasco.utils import extract_unmatched_items, import_class, AttrDict
from jinja_macro_tags import MacroLoader, MacroRegistry
from jinja2 import ChoiceLoader, FileSystemLoader, PackageLoader
from contextlib import contextmanager
from flask_mail import Mail
import os
import datetime

from .message import create_message, clickable_links, log_message
from .provider import MailProvider, bulk_connection_context


_signals = Namespace()
email_sent = _signals.signal('email_sent')


class FrascoMailError(Exception):
    pass


class FrascoMailState(ExtensionState):
    def __init__(self, *args):
        super(FrascoMailState, self).__init__(*args)
        self.connections = AttrDict()
        self.template_loaders = []
        layout_loader = PackageLoader(__name__, "templates")
        self.jinja_loader = MacroLoader(ChoiceLoader([ChoiceLoader(self.template_loaders), layout_loader]))
        self.jinja_env = None

    def add_template_folder(self, path):
        self.template_loaders.append(FileSystemLoader(path))

    def add_templates_from_package(self, pkg_name, pkg_path="emails"):
        self.template_loaders.append(PackageLoader(pkg_name, pkg_path))


class FrascoMail(Extension):
    """Send emails using SMTP
    """
    name = "frasco_mail"
    state_class = FrascoMailState
    defaults = {"provider": "smtp",
                "connections": {},
                "default_layout": "layout.html",
                "default_template_vars": {},
                "inline_css": False,
                "auto_render_missing_content_type": True,
                "log_messages": None, # default is app.testing
                "log_messages_on_failure": False, # default is app.testing
                "dumped_messages_folder": "email_logs",
                "localized_emails": None,
                "default_locale": None,
                "markdown_options": {},
                "suppress_send": False,
                "silent_failures": False,
                "send_async": False}

    def _init_app(self, app, state):
        mail = Mail(app) # needed for Message even if we will never use
        connections = dict(state.options['connections'])
        if "default" not in connections:
            connections["default"] = dict(extract_unmatched_items(state.options, self.defaults or {}),
                provider=state.require_option('provider'))
        for name, opts in connections.items():
            self.register_connection(name, opts, _app=app)

        state.add_template_folder(os.path.join(app.root_path, "emails"))
        state.jinja_env = app.jinja_env.overlay(loader=state.jinja_loader)
        state.jinja_env.add_extension(RemoveYamlFrontMatterExtension)
        state.jinja_env.macros = MacroRegistry(state.jinja_env) # the overlay methods does not call the constructor of extensions
        state.jinja_env.macros.register_from_template("layouts/macros.html")
        state.jinja_env.default_layout = state.options["default_layout"]
        state.jinja_env.filters['clickable_links'] = clickable_links

        if has_extension('frasco_babel', app):
            if state.options['default_locale'] is None:
                state.options['default_locale'] = app.extensions.frasco_babel.options['default_locale']
            if state.options['localized_emails'] is None:
                state.options['localized_emails'] = '{locale}/{filename}'

    @ext_stateful_method
    def create_connection(self, state, options, provider=None):
        if not provider:
            options = dict(**options)
            provider = options.pop('provider', 'smtp')
        provider_class = import_class(provider, MailProvider, "frasco.mail.providers")
        return provider_class(state, options)

    @ext_stateful_method
    def register_connection(self, state, name, options, provider=None):
        state.connections[name] = self.create_connection(options, provider, _state=state)


@delayed_tx_calls.proxy
def send_message_sync(msg, connection="default", silent=None):
    state = get_extension_state('frasco_mail')

    if state.options['suppress_send']:
        if state.options["log_messages"] or current_app.testing or current_app.debug:
            log_message(msg, state.options['dumped_messages_folder'], connection)
        email_sent.send(msg)
        return

    try:
        if bulk_connection_context.top:
            bulk_connection_context.top.send(msg)
        elif isinstance(connection, MailProvider):
            connection.send(msg)
        else:
            state.connections[connection].send(msg)
        email_sent.send(msg)
        if state.options["log_messages"] or current_app.testing or current_app.debug:
            log_message(msg, state.options['dumped_messages_folder'], connection)
    except Exception as e:
        if state.options["log_messages_on_failure"]:
            log_message(msg, state.options['dumped_messages_folder'], connection)
        if (silent is None and not state.options['silent_failures']) or silent is False:
            raise e
        current_app.log_exception(e)


@delayed_tx_calls.proxy
def send_message_async(msg, connection="default"):
    require_extension('frasco_tasks')
    enqueue_task(send_message_sync, msg=msg, connection=connection)


def send_message(msg, connection="default"):
    state = get_extension_state('frasco_mail')
    if has_extension('frasco_tasks') and state.options['send_async']:
        send_message_async(msg, connection)
    else:
        send_message_sync(msg, connection)


def send_mail(to, template_filename, *args, **kwargs):
    state = get_extension_state('frasco_mail')
    force_sync = kwargs.pop('_force_sync', False)
    connection = kwargs.pop('_connection', 'default')
    msg = create_message(to, template_filename, *args, **kwargs)
    if msg:
        if force_sync:
            send_message_sync(msg, connection)
        else:
            send_message(msg, connection)

@contextmanager
def bulk_mail_connection(connection="default"):
    state = get_extension_state('frasco_mail')
    with state.connections[connection].bulk_connection():
        yield
