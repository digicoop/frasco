from jinja2 import ChoiceLoader
from jinja2.ext import ExprStmtExtension
from jinja_macro_tags import configure_environment as configure_macro_environment, FileLoader
from jinja_layout import LayoutExtension
import os
from ..helpers import url_for, url_for_static, url_for_same
from ..utils import slugify
from .extensions import *
from .helpers import *


def configure_environment(env):
    env.loader = ChoiceLoader([env.loader,
        FileLoader(os.path.join(os.path.dirname(__file__), "layout.html"), "frasco_layout.html"),
        FileLoader(os.path.join(os.path.dirname(__file__), "layout.html"), "layout.html")
    ])

    env.add_extension(ExprStmtExtension)
    env.add_extension(LayoutExtension)
    env.add_extension(FlashMessagesExtension)
    configure_macro_environment(env)

    env.globals.update(real_dict=dict,
                       getattr=getattr,
                       url_for=url_for,
                       url_for_static=url_for_static,
                       url_for_same=url_for_same,
                       html_tag=html_tag,
                       html_attributes=html_attributes,
                       plural=plural)
    env.filters.update(slugify=slugify,
                       nl2br=nl2br,
                       timeago=timeago)

    env.add_extension(jinja_block_as_fragment_extension("content"))
    env.macros.register_file(os.path.join(os.path.dirname(__file__), "macros.html"), alias="frasco.html")


def register_bootstrap_macros(app):
    app.jinja_env.macros.register_directory(os.path.join(os.path.dirname(__file__), "bootstrap"), prefix="bootstrap")
