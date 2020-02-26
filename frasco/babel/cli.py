from flask import current_app
from flask.cli import AppGroup
from frasco.ext import get_extension_state
from frasco.utils import shell_exec
import click
import tempfile
import os
import re

from .extract import edit_pofile, merge_pofile, create_babel_mapping, exec_babel_extract, po_to_json
from .signals import *


babel_cli = AppGroup('babel', help='Commands to manage translations')


def _extract():
    state = get_extension_state('frasco_babel')
    path = os.path.join(current_app.root_path, "translations")
    if not os.path.exists(path):
        os.mkdir(path)
    potfile = os.path.join(path, "messages.pot")

    click.echo("Extracting translatable strings from %s" % current_app.root_path)
    mapping = create_babel_mapping(state.options["extract_jinja_dirs"],
        state.options["extract_with_jinja_exts"], state.options["extractors"])
    exec_babel_extract(current_app.root_path, potfile, mapping)

    # we need to extract message from other paths independently then
    # merge the catalogs because babel's mapping configuration does
    # not support absolute paths
    for path, jinja_dirs, jinja_exts, extractors in state.extract_dirs:
        click.echo("Extracting translatable strings from %s" % path)
        mapping = create_babel_mapping(jinja_dirs, jinja_exts, extractors)
        path_potfile = tempfile.NamedTemporaryFile(delete=False)
        path_potfile.close()
        exec_babel_extract(path, path_potfile.name, mapping)
        merge_pofile(potfile, path_potfile.name)
        os.unlink(path_potfile.name)

    translation_extracted.send()


@babel_cli.command('extract')
def extract_cmd():
    _extract()


@babel_cli.command("init")
@click.argument('locale')
@click.option('--gotrans/--no-gotrans', default=False)
def init_translation(locale, gotrans=False):
    state = get_extension_state('frasco_babel')
    path = os.path.join(current_app.root_path, "translations")
    potfile = os.path.join(path, "messages.pot")
    if not os.path.exists(potfile):
        _extract()
    click.echo("Initializing new translation '%s' in %s" % (locale, os.path.join(path, locale)))
    shell_exec([state.options["babel_bin"], "init", "-i", potfile, "-d", path, "-l", locale])
    translation_updated.send(None, locale=locale)
    if gotrans:
        translate_with_google(locale)


@babel_cli.command("update")
@click.option('--extract/--no-extract', default=True)
@click.option('--gotrans/--no-gotrans', default=False)
def update_translations(extract=True, gotrans=False):
    state = get_extension_state('frasco_babel')
    path = os.path.join(current_app.root_path, "translations")
    potfile = os.path.join(path, "messages.pot")
    if not os.path.exists(potfile) or extract:
        _extract()
    click.echo("Updating all translations")
    shell_exec([state.options["babel_bin"], "update", "-i", potfile, "-d", path])
    for entry in os.scandir(path):
        if entry.is_dir():
            translation_updated.send(locale=entry.name)
            if gotrans:
                translate_with_google(f)


@babel_cli.command("compile")
def compile_translations():
    click.echo("Compiling all translations")
    state = get_extension_state('frasco_babel')
    path = os.path.join(current_app.root_path, "translations")
    shell_exec([state.options["babel_bin"], "compile", "-d", path])
    if state.options['compile_to_json']:
        output = os.path.join(current_app.static_folder, state.options['compile_to_json'])
        for entry in os.scandir(path):
            if entry.is_dir():
                _po2json(entry.name, output % entry.name)
    if state.options['compile_to_js']:
        output = os.path.join(current_app.static_folder, state.options['compile_to_js'])
        for entry in os.scandir(path):
            if entry.is_dir():
                _po2js(entry.name, output % entry.name)
    translation_compiled.send()


def _po2json(locale, output=None):
    filename = os.path.join(current_app.root_path, "translations", locale, "LC_MESSAGES", "messages.po")
    dump = po_to_json(filename)
    if output:
        with open(output, 'w') as f:
            f.write(dump)
    else:
        click.echo(dump)


def _po2js(locale, output=None):
    filename = os.path.join(current_app.root_path, "translations", locale, "LC_MESSAGES", "messages.po")
    varname = get_extension_state('frasco_babel').options['js_catalog_varname']
    dump = "var %s = %s;" % (varname % locale.upper(), po_to_json(filename))
    if output:
        with open(output, 'w') as f:
            f.write(dump)
    else:
        click.echo(dump)


@babel_cli.command('po2json')
@click.argument('locale')
@click.option('--output', '-o')
def po2json(locale, output=None):
    _po2json(locale, output)


@babel_cli.command('po2js')
@click.argument('locale')
@click.option('--output', '-o')
def po2js(locale, output=None):
    _po2js(locale, output)


@babel_cli.command("gotrans")
@click.argument('locale')
def translate_with_google(locale):
    import goslate
    click.echo("Google translating '%s'" % locale)
    click.echo("WARNING: you must go through the translation after the process as placeholders may have been modified", fg="red")
    filename = os.path.join(current_app.root_path, "translations", locale, "LC_MESSAGES", "messages.po")

    def translate(id):
        # google translate messes with the format placeholders thus
        # we replace them with something which is easily recoverable
        string, placeholders = safe_placeholders(id)
        string = gs.translate(string, locale)
        return unsafe_placeholders(string, placeholders, "## %s ##")

    with edit_pofile(filename) as catalog:
        gs = goslate.Goslate()
        for message in catalog:
            if not message.id:
                continue
            if message.pluralizable:
                string = list(message.string)
                if not string[0]:
                    string[0] = translate(message.id[0])
                if not string[1]:
                    string[1] = translate(message.id[1])
                message.string = tuple(string)
            elif not message.string:
                message.string = translate(message.id)


def safe_placeholders(string, repl="##%s##"):
    placeholders = []
    def replace_placeholder(m):
        placeholders.append(m.group(1))
        return repl % (len(placeholders) - 1)
    string = re.sub(r"%\(([a-zA-Z_]+)\)s", replace_placeholder, string)
    return string, placeholders


def unsafe_placeholders(string, placeholders, repl="##%s##"):
    for i, placeholder in enumerate(placeholders):
        string = string.replace(repl % i, "%%(%s)s" % placeholder)
    return string
