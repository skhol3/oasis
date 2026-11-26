#!/usr/bin/env python3
"""Odoo's PostgreSQL account (v0.16.0 S2), read for the commands that need it and never printed.

The account Odoo uses: each of db_user and db_password from odoo.conf when it sets one (Odoo reads
`False` and `None` there as unset too), else ODOO_DB_USER and ODOO_DB_PASSWORD of the env file
([tooling].env_file), the single 0600 file `oasis setup` generates and the compose service reads.
odoo.conf stays password-free: every oasis command that starts Odoo exports the env file's values as
PGUSER and PGPASSWORD, which libpq reads when Odoo passes no user or password, so the password is
never on a command line.

Usage:
  db_account.py exports <odoo.conf> <env_file>
      `export PGUSER=...` and `export PGPASSWORD=...`, shell-quoted, for what odoo.conf leaves empty and
      the env file sets (common.sh evaluates them); nothing when either file cannot be read; refused
      when stdout is a terminal.
  db_account.py probe <odoo.conf> <env_file>
      run with the environment's Python: connect to the PostgreSQL odoo.conf names (db_host and db_port,
      each left to libpq when empty, as Odoo does) with that account through psycopg2, and print one
      word: ready, authentication_failed, not_running, no_driver or failed.
  db_account.py compose-project <compose file>
      the compose file's top-level name, or nothing.
  db_account.py fix <odoo.conf> <env_file> <compose file> <program> <project root>
      what fixes an authentication failure (doctor and check-environment print it).

Nothing here prints a value of either file, a line of them or a message of the server. Python 3.7
compatible: the probe runs with the environment's Python, as old as Odoo 15's.
"""
from __future__ import annotations

import configparser
import re
import shlex
import sys

ENV_ASSIGNMENT = re.compile(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)')
ACCOUNT = (('user', 'db_user', 'ODOO_DB_USER', 'PGUSER'), ('password', 'db_password', 'ODOO_DB_PASSWORD', 'PGPASSWORD'))
# Values Odoo's configuration reads as unset (odoo/tools/config.py: '' is falsy, False and None convert).
UNSET = ('', 'False', 'false', 'None')
TOP_LEVEL_NAME = re.compile(r'''^(?:name|"name"|'name')\s*:(.*)$''')
EMPTY_VALUES = ('', '""', "''", '~', 'null')
NOT_RUNNING = ('could not connect', 'connection refused', 'no such file or directory', 'timeout expired',
               'could not translate host name', 'server closed the connection', 'network is unreachable')


class AccountError(Exception):
    """A file cannot be read; the message names the path, never content."""


def env_value(raw: str) -> str:
    """An env file value as docker compose reads it: inside single quotes literal, inside double quotes
    as written, else up to a ` #` comment, stripped."""
    value = raw.strip()
    for quote in ("'", '"'):
        if len(value) >= 2 and value[0] == quote and quote in value[1:]:
            return value[1:value.index(quote, 1)]
    return re.sub(r'\s+#.*$', '', value).strip()


def env_values(path) -> dict:
    """ODOO_DB_USER and ODOO_DB_PASSWORD of the env file (the last assignment wins); {} without the file."""
    try:
        with open(path, 'rb') as stream:
            text = stream.read().decode('utf-8', errors='replace')
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise AccountError(f'Cannot read {path}.') from exc
    names = {name for _key, _option, name, _variable in ACCOUNT}
    found = {}
    for line in text.splitlines():
        match = ENV_ASSIGNMENT.fullmatch(line)
        if match and match.group(1) in names:
            found[match.group(1)] = env_value(match.group(2))
    return found


def conf_options(path) -> dict:
    """db_host, db_port, db_user and db_password of odoo.conf's [options] (unset ones left out)."""
    parser = configparser.RawConfigParser()
    try:
        with open(path, encoding='utf-8') as stream:
            parser.read_string(stream.read(), source=str(path))
    except (OSError, UnicodeError, configparser.Error) as exc:
        raise AccountError(f'Cannot read {path}.') from exc
    found = {}
    for option in ('db_host', 'db_port', 'db_user', 'db_password'):
        if parser.has_option('options', option):
            value = parser.get('options', option).strip()
            if value not in UNSET:
                found[option] = value
    return found


def account(conf, env_file) -> dict:
    """{'user': .., 'password': ..} as Odoo will use them: odoo.conf's, else the env file's (keys without a
    non-empty value are left out), and 'from_env': the keys that come from the env file."""
    options, values = conf_options(conf), env_values(env_file)
    found, from_env = {}, []
    for key, option, name, _variable in ACCOUNT:
        if option in options:
            found[key] = options[option]
        elif values.get(name):
            found[key] = values[name]
            from_env.append(key)
    found['from_env'] = from_env
    return found


def differing(conf, env_file) -> list:
    """The odoo.conf options of the account that it sets to another value than the env file's."""
    options, values = conf_options(conf), env_values(env_file)
    return [option for _key, option, name, _variable in ACCOUNT
            if option in options and values.get(name) and options[option] != values[name]]


def exports(conf, env_file) -> str:
    """Only what odoo.conf leaves unset: Odoo 19 ranks PGUSER and PGPASSWORD above odoo.conf. When either file
    cannot be read, nothing: the command runs as before (Odoo reports its odoo.conf, doctor both files)."""
    try:
        found = account(conf, env_file)
    except AccountError:
        return ''
    return ''.join(f'export {variable}={shlex.quote(found[key])}\n'
                   for key, _option, _name, variable in ACCOUNT if key in found['from_env'])


def outcome(message: str) -> str:
    """The word of a connection error message (psycopg2.OperationalError)."""
    text = message.lower()
    if ('authentication failed' in text or 'no password supplied' in text
            or ('role' in text and 'does not exist' in text)):
        return 'authentication_failed'
    if any(words in text for words in NOT_RUNNING):
        return 'not_running'
    return 'failed'


def probe(conf, env_file) -> str:
    try:
        import psycopg2
    except ImportError:
        return 'no_driver'
    options, found = conf_options(conf), account(conf, env_file)
    arguments = {'dbname': 'postgres', 'connect_timeout': 5}
    for key, option in (('host', 'db_host'), ('port', 'db_port')):
        if option in options:
            arguments[key] = options[option]
    for key in ('user', 'password'):
        if key in found:
            arguments[key] = found[key]
    try:
        psycopg2.connect(**arguments).close()
    except psycopg2.OperationalError as exc:
        return outcome(str(exc))
    except Exception:  # noqa: BLE001  any other error is reported as one word, never its text
        return 'failed'
    return 'ready'


def compose_project(path):
    """The top-level `name:` of a compose file (quotes removed), None without a non-empty one; raises
    OSError or UnicodeError when it cannot be read."""
    with open(path, encoding='utf-8') as stream:
        lines = stream.read().splitlines()
    for line in lines:
        match = TOP_LEVEL_NAME.match(line)
        if match:
            value = re.sub(r'\s+#.*$', '', match.group(1)).strip()
            if value not in EMPTY_VALUES:
                return value.strip('\'"')
    return None


def authentication_fix(conf, env_file, compose, program, root) -> str:
    """What fixes Odoo's account being refused: odoo.conf's own account values when they differ from the
    env file's, else recreating the volume, which was initialized with other credentials."""
    try:
        options = differing(conf, env_file)
    except AccountError:
        options = []
    if options:
        names = ' and '.join(options)
        return (f'{conf} sets {names} to other values than {env_file}: remove {names} from {conf} so Odoo uses the '
                f'account of {env_file}, then run {program} doctor again')
    try:
        project = compose_project(compose)
    except (OSError, UnicodeError):
        project = None
    command = [program, '--project', str(root), 'recreate-database-volume']
    if project is not None:
        command += ['--confirm', project]
    return (f'the PostgreSQL that {conf} names refuses the account Odoo uses: its volume was initialized with other '
            f'credentials than {env_file}; {" ".join(shlex.quote(word) for word in command)} recreates it with them '
            '(Tier B: it deletes every database of the service)')


def main(argv: list) -> int:
    try:
        if len(argv) == 3 and argv[0] == 'exports':
            if sys.stdout.isatty():
                print('ERROR: db_account.py exports writes the account only to a pipe, never to a terminal.',
                      file=sys.stderr)
                return 2
            sys.stdout.write(exports(argv[1], argv[2]))
            return 0
        if len(argv) == 3 and argv[0] == 'probe':
            print(probe(argv[1], argv[2]))
            return 0
        if len(argv) == 2 and argv[0] == 'compose-project':
            try:
                project = compose_project(argv[1])
            except (OSError, UnicodeError):
                print(f'ERROR: Cannot read {argv[1]}.', file=sys.stderr)
                return 2
            if project is not None:
                print(project)
            return 0
        if len(argv) == 6 and argv[0] == 'fix':
            print(authentication_fix(*argv[1:]))
            return 0
    except AccountError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    print('Usage: db_account.py exports|probe <odoo.conf> <env_file> | compose-project <compose file> | '
          'fix <odoo.conf> <env_file> <compose file> <program> <project root>', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
