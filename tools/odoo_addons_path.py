#!/usr/bin/env python3
"""Print an odoo.conf addons_path with the main checkout's root moved to another checkout.

Usage: odoo_addons_path.py <odoo.conf> <main_root> <project_root>
       odoo_addons_path.py --option <http_port|gevent_port|http_interface> <odoo.conf>

Reads only the `addons_path` option of the `[options]` section and prints nothing else from
the file: any read or parse error exits 2 with a message that names the path, never content.
Each comma-separated item whose resolved path is the main root or lies inside it gets the
project root in its place (the relative remainder is kept); items that already lie inside the
project root, relative items and every other item stay as written, in order. Empty items are
dropped. Without an addons_path nothing is printed and the exit status is 0.

common.sh (odoo_config_arguments) runs this file; dev_users_runtime.py imports
linked_addons_path, the same decision for its in-process Odoo configuration.

With --option it reads only that one option (the ports and interface `start` needs) and prints
its value, or nothing when it is absent; a port that is not 1-65535 exits 2 without the value.
"""
import configparser
import os
from pathlib import Path
import sys

USAGE = 'Usage: odoo_addons_path.py <odoo.conf> <main_root> <project_root>'
# The only other options this reader may print.
OPTIONS = ('http_port', 'gevent_port', 'http_interface')


class ConfError(Exception):
    """The configuration cannot be read; the message names the path, never content."""


def read_addons_path(conf):
    """The raw addons_path of [options], or None when there is none."""
    return read_option(conf, 'addons_path')


def read_option(conf, option):
    """The raw value of one [options] option, or None when there is none."""
    try:
        with open(conf, encoding='utf-8') as stream:
            text = stream.read()
    except UnicodeDecodeError as exc:
        raise ConfError(f'Cannot read {option} from {conf}: invalid configuration file.') from exc
    except OSError as exc:
        raise ConfError(f'Cannot read {conf}.') from exc
    # Odoo reads its configuration with RawConfigParser; parse errors quote lines, so they
    # are replaced by a fixed message.
    parser = configparser.RawConfigParser()
    try:
        parser.read_string(text, source=str(conf))
    except configparser.Error as exc:
        raise ConfError(f'Cannot read {option} from {conf}: invalid configuration file.') from exc
    if not parser.has_option('options', option):
        return None
    return parser.get('options', option)


def option_value(conf, option):
    """--option: the stripped value ('' when absent); ports must be 1-65535."""
    value = (read_option(conf, option) or '').strip()
    if value and option.endswith('_port') and not (value.isdigit() and 1 <= int(value) <= 65535):
        raise ConfError(f'Invalid {option} in {conf}: it must be a port number.')
    return value


def rewrite(value, main, project):
    items = []
    for item in value.split(','):
        item = item.strip()
        if not item:
            continue
        if os.path.isabs(item):
            resolved = Path(item).resolve()
            # The project's own items first: a worktree may live inside the main checkout.
            if not resolved.is_relative_to(project) and resolved.is_relative_to(main):
                remainder = resolved.relative_to(main)
                item = str(project / remainder) if remainder.parts else str(project)
        items.append(item)
    return ','.join(items)


def linked_addons_path(values):
    """The --addons-path value for a checkout (tools/config.py values), or ''.

    Only a linked worktree whose odoo.conf names the main checkout gets one; the main
    checkout and a project outside git never read the file.
    """
    if values.get('CHECKOUT_KIND') != 'linked':
        return ''
    value = read_addons_path(values['ODOO_CONFIG'])
    if value is None:
        return ''
    project = Path(values['PROJECT_ROOT']).resolve()
    rewritten = rewrite(value, Path(values['CHECKOUT_MAIN_ROOT']).resolve(), project)
    # The same normalization without the move: a conf that already names this checkout adds nothing.
    return rewritten if rewritten and rewritten != rewrite(value, project, project) else ''


def main():
    if len(sys.argv) == 4 and sys.argv[1] == '--option' and sys.argv[2] in OPTIONS:
        try:
            value = option_value(sys.argv[3], sys.argv[2])
        except ConfError as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 2
        if value:
            print(value)
        return 0
    if len(sys.argv) != 4 or sys.argv[1] == '--option':
        print('ERROR: ' + USAGE, file=sys.stderr)
        return 2
    main_root, project_root = (Path(path).resolve() for path in sys.argv[2:])
    try:
        value = read_addons_path(sys.argv[1])
    except ConfError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    result = rewrite(value, main_root, project_root) if value is not None else ''
    if result:
        print(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
