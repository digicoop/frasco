from frasco.ext import get_extension_state
import random
import math


def generate_first_letter_avatar_svg(name, colorstr=None, size=None):
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
    colors_len = len(state.options['flavatar_colors'])
    if colorstr:
        color_pos = sum([ord(c) for c in colorstr]) % colors_len
    elif ord(text[0]) < 65:
        color_pos = random.randint(0, colors_len - 1)
    else:
        color_pos = int(math.floor((ord(text[0]) - 65) % colors_len))

    color = state.options['flavatar_colors'][color_pos]
    return svg_tpl % {
        'bgcolor': color,
        'w': size,
        'h': size,
        'letter': char_svg_tpl % {
            'dy': state.options['flavatar_text_dy'],
            'fgcolor': get_contrast_color(color),
            'size': state.options['flavatar_font_size'],
            'char': text
        }
    }


def get_contrast_color(color):
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)
    yiq = ((r * 299) + (g * 587) + (b * 114)) / 1000
    return '#000' if yiq >= 128 else '#fff'
