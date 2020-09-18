
from flask import session, g, current_app
from frasco.ext import *
from frasco.utils import shell_exec
from frasco.helpers import get_remote_addr
import geoip2.database
import os
import logging
import click
import sys


DOWNLOAD_URL = "https://download.maxmind.com/app/geoip_download"
COUNTRY_EDITION = "GeoLite2-Country"
CITY_EDITION = "GeoLite2-City"


class FrascoGeoip(Extension):
    name = "frasco_geoip"
    defaults = {"use_city_db": True,
                "db": "GeoLite2-City.mmdb",
                "license_key": None}

    def _init_app(self, app, state):
        app.add_template_global(geolocate_country)
        app.add_template_global(geolocate_city)

        if os.path.exists(state.options['db']):
            state.reader = geoip2.database.Reader(state.options['db'])
        else:
            logging.getLogger('frasco.geoip').info('%s does not exists, geolocation is disabled' % state.options['db'])

        @app.cli.command('dl-geo-db')
        @click.option('--edition')
        @click.option('--suffix', default='tar.gz')
        @click.option('--license-key')
        def download_db(edition=None, suffix='tar.gz', license_key=None):
            """Download GeoLite2 databases from MaxMind"""
            if not license_key:
                license_key = state.options['license_key']
            if not license_key:
                click.echo("You must register on MaxMind to obtain a license key in order to download databases")
                sys.exit(1)
            tmpfilename = "/tmp/GeoLite2.tar.gz"
            if not edition:
                edition = CITY_EDITION if state.options["use_city_db"] else COUNTRY_EDITION
            url = "%s?edition_id=%s&suffix=%s&license_key=%s" % (DOWNLOAD_URL, edition, suffix, license_key)
            shell_exec(["wget", "-O", tmpfilename, url])
            dbfilename = shell_exec(["tar", "tzf", tmpfilename, "--no-anchored", state.options['db']], echo=False).decode().strip()
            shell_exec(["tar", "-C", "/tmp", "-xzf", tmpfilename, dbfilename])
            shell_exec(["mv", os.path.join("/tmp", dbfilename), state.options['db']])


def geolocate(addr=None, method=None):
    state = get_extension_state('frasco_geoip')
    if not hasattr(state, 'reader'):
        return
    if not method:
        method = 'city' if state.options['use_city_db'] else 'country'
    try:
        return getattr(state.reader, method)(addr or get_remote_addr())
    except:
        pass


def geolocate_country(addr=None, use_session_cache=True):
    if use_session_cache and "geo_country_code" in session:
        return session["geo_country_code"]

    if get_extension_state('frasco_geoip').options['use_city_db']:
        city, country = geolocate_city(addr, use_session_cache)
        return country

    r = geolocate(addr, 'country')
    if r:
        if use_session_cache:
            session["geo_country_code"] = r.country.iso_code
        return r.country.iso_code


def geolocate_city(addr=None, use_session_cache=True):
    if use_session_cache and "geo_city" in session:
        return session["geo_city"]
    r = geolocate(addr, 'city')
    if r:
        if use_session_cache:
            session["geo_city"] = r.city.name
            session["geo_country_code"] = r.country.iso_code
        return r.city.name, r.country.iso_code
    return None, None


def clear_geo_cache():
    session.pop("geo_country_code", None)
    session.pop("geo_city", None)
