from flask import current_app, json
from frasco.ext import get_extension_state
from frasco.utils import shell_exec
from babel.messages import pofile
import os
import tempfile
import contextlib


@contextlib.contextmanager
def edit_pofile(filename, autosave=True):
    with open(filename, "r") as f:
        catalog = pofile.read_po(f)
    yield catalog
    if autosave:
        with open(filename, "w") as f:
            pofile.write_po(f, catalog)


def merge_pofile(filename1, filename2):
    with edit_pofile(filename1) as catalog1:
        with edit_pofile(filename2) as catalog2:
            for msg in catalog2:
                if msg.id not in catalog1:
                    catalog1[msg.id] = msg


def create_babel_mapping(jinja_dirs=None, jinja_exts=None, extractors=None):
    exts = ",".join(jinja_exts or [])
    conf = "[python:**.py]\n"
    if jinja_dirs:
        for jinja_dir in jinja_dirs:
            if jinja_dir == '.':
                jinja_dir = ''
            conf += "[jinja2:%s]\n" % os.path.join(jinja_dir, "**.html")
            if exts:
                conf += "extensions=%s\n" % exts
    if extractors:
        for extractor, settings in extractors:
            conf += "[%s]\n" % extractor
            for k, v in settings.iteritems():
                conf += "%s = %s\n" % (k, v)
    return conf


def exec_babel_extract(path, potfile, mapping=None, keywords=None):
    state = get_extension_state('frasco_babel')
    if mapping:
        mapping_file = tempfile.NamedTemporaryFile()
        mapping_file.write(mapping)
        mapping_file.flush()

    if isinstance(keywords, (str, unicode)):
        keywords = map(str.strip, str(keywords).split(";"))
    elif not keywords:
        keywords = []
    keywords.extend(["_n:1,2", "translatable", "translate", "ntranslate",
                        "lazy_translate", "lazy_gettext"])
    keywords.extend(state.options['extract_keywords'])

    cmdline = [state.options["babel_bin"], "extract", "-o", potfile]
    if mapping:
        cmdline.extend(["-F", mapping_file.name])
    for k in keywords:
        cmdline.append("-k")
        cmdline.append(k)
    cmdline.append(path)

    shell_exec(cmdline)
    if mapping:
        mapping_file.close()


def po_to_json(filename):
    json_dct = {}
    with edit_pofile(filename) as catalog:
        for message in catalog:
            if not message.id:
                continue
            if message.pluralizable:
                json_dct[message.id[0]] = [message.id[1]] + list(message.string)
            else:
                json_dct[message.id] = [None, message.string]
    return json.dumps(json_dct)
