from flask import request
from frasco.ext import get_extension_state
import requests


def validate_recaptcha():
    state = get_extension_state('frasco_users')
    if 'g-recaptcha-response' in request.form:
        r = requests.post('https://www.google.com/recaptcha/api/siteverify', data={
            'secret': state.options['recaptcha_secret'],
            'response': request.form['g-recaptcha-response'],
            'remote_ip': request.remote_addr
        })
        return r.ok and r.json().get('success')
    return False


def validate_hcaptcha():
    state = get_extension_state('frasco_users')
    if 'h-captcha-response' in request.form:
        r = requests.post('https://hcaptcha.com/siteverify', data={
            'secret': state.options['hcaptcha_secret'],
            'response': request.form['h-captcha-response'],
            'remoteip': request.remote_addr
        })
        return r.ok and r.json().get('success')
    return False
