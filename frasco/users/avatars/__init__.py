from frasco.ext import *
from frasco.upload import url_for_upload
from frasco.helpers import url_for
from frasco.utils import slugify
from flask import current_app, request
import sqlalchemy as sqla
import hashlib
import urllib.request, urllib.parse, urllib.error
import base64
import requests

from .first_letter_avatar import generate_first_letter_avatar_svg


def svg_to_base64_data(svg):
    return 'data:image/svg+xml;base64,' + base64.b64encode(svg)


class UserAvatarModelMixin(object):
    avatar_filename = sqla.Column(sqla.String)

    @property
    def avatar_url(self):
        return url_for_avatar(self)


class FrascoUsersAvatars(Extension):
    name = "frasco_users_avatars"
    defaults = {"url": None,
                "avatar_size": 80,
                "add_flavatar_route": False,
                "email_column": None,
                "name_column": None,
                "try_gravatar": True,
                "force_gravatar": False,
                "gravatar_size": None,
                "gravatar_default": "mm",
                "force_flavatar": False,
                "flavatar_size": "100%",
                "flavatar_font_size": 70,
                "flavatar_text_dy": "20%",
                "flavatar_length": 1,
                "flavatar_colors": ["#0E7C7B", "#17BEBB", "#D4F4DD", "#D62246", "#4B1D3F", "#C0DA74", "#BEEDAA", "#B2DDF7", "#FFFF82", "#13315C", "#6761A8", "#407887", "#0CCE6B", "#F1AB86", "#EAD94C", "#23B5D3", "#324376"]}

    def _init_app(self, app, state):
        app.add_template_global(url_for_avatar)

        def flavatar(name, bgcolorstr=None):
            if bgcolorstr is None:
                bgcolorstr = request.args.get('bgcolorstr')
            svg = generate_first_letter_avatar_svg(name, bgcolorstr, request.args.get('size'))
            return svg, 200, {
                'Content-Type': 'image/svg+xml',
                'Cache-Control': 'public, max-age=31536000'
            }

        @app.route('/avatar/<hash>/<name>')
        def avatar(hash, name):
            if state.options['try_gravatar']:
                size = state.options['gravatar_size'] or state.options["avatar_size"]
                try:
                    r = requests.get(url_for_gravatar(hash, size=size, default=404))
                    if r.status_code != 404:
                        return r.content, 200, {'Content-Type': r.headers['content-type']}
                except Exception:
                    pass
            return flavatar(name, hash)

        if state.options['add_flavatar_route']:
            app.add_url_rule('/flavatar/<name>.svg', 'flavatar', flavatar)
            app.add_url_rule('/flavatar/<name>/<bgcolorstr>.svg', 'flavatar', flavatar)


def url_for_avatar(user):
    state = get_extension_state('frasco_users_avatars')
    if getattr(user, 'avatar_filename', None):
        return url_for_upload(user.avatar_filename)

    hash = None
    username = getattr(user, state.options["name_column"] or 'username', None)
    if username:
        username = slugify(username.lower())
        hash = hashlib.md5(username.encode('utf-8')).hexdigest()

    email = getattr(user, state.options["email_column"] or 'email', None)
    if email:
        hash = hashlib.md5(email.lower().encode('utf-8')).hexdigest()
        if not username:
            username = slugify(email.split('@')[0])

    if state.options["force_flavatar"] and username:
        if state.options['add_flavatar_route']:
            return url_for('flavatar', name=username, bgcolorstr=hash, _external=True)
        return svg_to_base64_data(generate_first_letter_avatar_svg(username, hash))
    if state.options["force_gravatar"] and email:
        return url_for_gravatar(email)
    if state.options['url'] and email:
        return state.options["url"].format(email=email, email_hash=hash, username=username)
    return url_for('avatar', hash=hash, name=username, _external=True)


def url_for_gravatar(email, size=None, default=None):
    state = get_extension_state('frasco_users_avatars')
    hash = hashlib.md5(email.lower().encode('utf-8')).hexdigest()
    params = {
        's': size or state.options['gravatar_size'] or state.options["avatar_size"],
        'd': default or state.options['gravatar_default']
    }
    return "https://www.gravatar.com/avatar/%s?%s" % (hash, urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}))

