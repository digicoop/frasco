from frasco.ext import *
from frasco.upload import url_for_upload
from frasco.helpers import url_for
from frasco.utils import slugify
from flask import current_app, request
import sqlalchemy as sqla
import hashlib
import urllib.request, urllib.parse, urllib.error
import math
import random
import base64
import requests


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
                "try_gravatar": True,
                "force_gravatar": False,
                "gravatar_size": None,
                "gravatar_email_column": None,
                "gravatar_default": "mm",
                "force_flavatar": False,
                "flavatar_size": "100%",
                "flavatar_name_column": None,
                "flavatar_font_size": 80,
                "flavatar_text_dy": "0.32em",
                "flavatar_length": 1,
                "flavatar_text_color": "#ffffff",
                "flavatar_bg_colors": ["#5A8770", "#B2B7BB", "#6FA9AB", "#F5AF29", "#0088B9", "#F18636", "#D93A37", "#A6B12E", "#5C9BBC", "#F5888D", "#9A89B5", "#407887", "#9A89B5", "#5A8770", "#D33F33", "#A2B01F", "#F0B126", "#0087BF", "#F18636", "#0087BF", "#B2B7BB", "#72ACAE", "#9C8AB4", "#5A8770", "#EEB424", "#407887"]}

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
    username = getattr(user, state.options["flavatar_name_column"] or 'username', None)
    if username:
        username = slugify(username.lower())
        hash = hashlib.md5(username.encode('utf-8')).hexdigest()

    email = getattr(user, state.options["gravatar_email_column"] or 'email', None)
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


def generate_first_letter_avatar_svg(name, bgcolorstr=None, size=None):
    state = get_extension_state('frasco_users_avatars')
    size = size or state.options['flavatar_size'] or state.options["avatar_size"]
    if size and isinstance(size, int):
        size = "%spx" % size

    svg_tpl = ('<svg xmlns="http://www.w3.org/2000/svg" pointer-events="none" viewBox="0 0 100 100" '
            'width="%(w)s" height="%(h)s" style="background-color: %(bgcolor)s;">%(letter)s</svg>')

    char_svg_tpl = ('<text text-anchor="middle" y="50%%" x="50%%" dy="%(dy)s" '
                    'pointer-events="auto" fill="%(fgcolor)s" font-family="'
                    'HelveticaNeue-Light,Helvetica Neue Light,Helvetica Neue,Helvetica, Arial,Lucida Grande, sans-serif" '
                    'style="font-weight: 400; font-size: %(size)spx">%(char)s</text>')

    if not name:
        text = '?'
    else:
        text = name[0:min(state.options['flavatar_length'], len(name))]
    colors_len = len(state.options['flavatar_bg_colors'])
    if bgcolorstr:
        bgcolor = sum([ord(c) for c in bgcolorstr]) % colors_len
    elif ord(text[0]) < 65:
        bgcolor = random.randint(0, colors_len - 1)
    else:
        bgcolor = int(math.floor((ord(text[0]) - 65) % colors_len))

    return svg_tpl % {
        'bgcolor': state.options['flavatar_bg_colors'][bgcolor],
        'w': size,
        'h': size,
        'letter': char_svg_tpl % {
            'dy': state.options['flavatar_text_dy'],
            'fgcolor': state.options['flavatar_text_color'],
            'size': state.options['flavatar_font_size'],
            'char': text
        }
    }
