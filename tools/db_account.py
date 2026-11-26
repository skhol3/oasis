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
      what fixes an authentication failure (doctor and check-environment print it): recreating the volume
      only when odoo.conf names the endpoint the compose service publishes, correcting the account on the
      server odoo.conf names when it is another one, and both when the port the compose file publishes to
      5432 cannot be read (several ports, the long syntax, a variable or a range).
  db_account.py unsupported <odoo.conf> <env_file>
      a `FAIL env_file=unsupported_value <names>` line and its fix when the env file writes an account
      variable Odoo would get with compose interpolation ($) or a double-quoted escape (\\), which this reader
      does not implement (exit 1); nothing otherwise (exit 0).
  db_account.py compose-project-name <env_file>
      the env file's COMPOSE_PROJECT_NAME (docker compose reads it from --env-file), or nothing.

A value this reader cannot read as docker compose does is never passed on: exports refuses it (exit 2,
naming the file and the variable) rather than giving Odoo another credential. Nothing here prints a value
of the account, a line of either file or a message of the server. Python 3.7 compatible: the probe runs
with the environment's Python, as old as Odoo 15's.
"""
from __future__ import annotations

import configparser
import os
import re
import shlex
import sys

ENV_ASSIGNMENT = re.compile(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)')
ACCOUNT = (('user', 'db_user', 'ODOO_DB_USER', 'PGUSER'), ('password', 'db_password', 'ODOO_DB_PASSWORD', 'PGPASSWORD'))
# Values Odoo's configuration reads as unset (odoo/tools/config.py: '' is falsy, False and None convert).
UNSET = ('', 'False', 'false', 'None')
TOP_LEVEL_NAME = re.compile(r'''^(?:name|"name"|'name')\s*:(.*)$''')
EMPTY_VALUES = ('', '""', "''", '~', 'null')
# A compose short-syntax entry that publishes the container's PostgreSQL port: `- '127.0.0.1:6001:5432'`,
# `- "6001:5432"`, `- 6001:5432/tcp`, with an optional host address and trailing comment. Anything else
# (the long syntax, ranges, variables) is not read; no YAML parser is used.
PUBLISHED_PORT = re.compile(r'''\s*-\s*(["']?)(?:(?:[0-9]{1,3}(?:\.[0-9]{1,3}){3}|localhost|\[[0-9A-Fa-f:]*\]):)?'''
                            r'''([0-9]{1,5}):5432(?:/tcp)?\1\s*(?:#.*)?''')
# Any other line under a `ports:` key (port_entries) that names the container's PostgreSQL port as a port entry:
# a list entry (a variable, a range, no host port) or a key of the long syntax (`target: 5432`). The port it
# publishes cannot be read from it. Lines under other keys (expose:, environment:) are not port entries.
OTHER_PORT_ENTRY = re.compile(r'''\s*(?:-\s*(?:target\s*:\s*)?|target\s*:\s*)\S*5432(?![0-9]).*''')
# The ports key, with YAML node properties when it has them: a tag (compose's !override, !reset) or an anchor.
PORTS_KEY = re.compile(r'''(\s*)(?:ports|"ports"|'ports')\s*:(?:\s+(?:![^\s#]*|&[^\s#]+))*\s*(?:#.*)?''')
UNREAD_ENTRY = 'an entry other than - [<address>:]<port>:5432'
# The hosts that reach the port the compose service publishes on 127.0.0.1.
LOCAL_HOSTS = ('127.0.0.1', 'localhost')
POSTGRES_PORT = 5432
NOT_RUNNING = ('could not connect', 'connection refused', 'no such file or directory', 'timeout expired',
               'could not translate host name', 'server closed the connection', 'network is unreachable')


class AccountError(Exception):
    """A file cannot be read; the message names the path, never content."""


class UnsupportedValue(Exception):
    """An account variable the env file writes in a way this reader does not implement (compose
    interpolation, a double-quoted escape); the message names the file and the variables, never a value."""

    def __init__(self, path, names):
        super().__init__(f'{path} sets {" and ".join(names)} with compose interpolation ($) or a double-quoted '
                         'escape (\\), which oasis does not read: write the value literally in single quotes.')


class Unsupported:
    """The value of an env file variable that docker compose would interpolate or unescape (UNSUPPORTED)."""

    def __repr__(self):
        return '<unsupported value>'


UNSUPPORTED = Unsupported()


def env_value(raw: str):
    """An env file value as docker compose reads it: inside single quotes literal, inside double quotes
    as written, else up to a ` #` comment, stripped; empty when it is only a ` # comment`; UNSUPPORTED when
    docker compose would read it otherwise: a `$` outside single quotes (interpolation) or a `\\` inside double
    quotes (an escape). `~` and `null` are those words, not empty (YAML does not apply to an env file)."""
    if re.match(r'\s+#', raw):
        # Only a comment after the `=` (`NAME= # fill in`): empty, as doctor reads it and setup fills it (docker
        # compose itself would read the comment as the value).
        return ''
    value = raw.strip()
    if len(value) >= 2 and value[0] == "'" and "'" in value[1:]:
        return value[1:value.index("'", 1)]
    if len(value) >= 2 and value[0] == '"' and '"' in value[1:]:
        inner = value[1:value.index('"', 1)]
        return UNSUPPORTED if '$' in inner or '\\' in inner else inner
    plain = re.sub(r'\s+#.*$', '', value).strip()
    return UNSUPPORTED if '$' in plain else plain


def text_values(text: str, names) -> dict:
    """The values of names an env file text assigns (env_value; the last assignment wins)."""
    found = {}
    for line in text.splitlines():
        match = ENV_ASSIGNMENT.fullmatch(line)
        if match and match.group(1) in names:
            found[match.group(1)] = env_value(match.group(2))
    return found


def env_values(path, names=None) -> dict:
    """ODOO_DB_USER and ODOO_DB_PASSWORD (or names) of the env file (the last assignment wins); {} without
    the file."""
    try:
        with open(path, 'rb') as stream:
            text = stream.read().decode('utf-8', errors='replace')
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise AccountError(f'Cannot read {path}.') from exc
    return text_values(text, names or account_names())


def account_names() -> list:
    return [name for _key, _option, name, _variable in ACCOUNT]


def fill_names(values: dict) -> list:
    """The account variables `oasis setup` writes to an existing env file (v0.16.0 S2): only those it assigns an
    empty value (as older setups wrote them); an absent one is never added (an existing file is respected)."""
    return [name for name in account_names() if name in values and not values[name]]


def unassigned_advice(env_file, program) -> str:
    """What setup and doctor say of an env file that assigns neither account variable: kept as it is."""
    return (f'setup leaves {env_file} unchanged (an existing file is respected); to use the account oasis generates, '
            f'add the empty lines ODOO_DB_USER= and ODOO_DB_PASSWORD= to it, then run {program} setup --apply')


def move(conf, env_file) -> dict:
    """What `oasis setup` does with the db_user and db_password odoo.conf sets (v0.16.0 S2): {'same': the
    options the env file holds (or setup writes to it from odoo.conf), 'differs': those it holds another value
    for, 'lacks': those it does not set}. Setup removes the options from odoo.conf only when none differs or
    lacks. Raises AccountError when a file cannot be read."""
    options = conf_options(conf)
    values = env_values(env_file)
    fill = fill_names(values) if os.path.lexists(env_file) else account_names()
    found = {'same': [], 'differs': [], 'lacks': []}
    for _key, option, name, _variable in ACCOUNT:
        if option not in options:
            continue
        if name in fill or values.get(name) == options[option]:
            found['same'].append(option)
        elif values.get(name):
            found['differs'].append(option)
        else:
            found['lacks'].append(option)
    return found


def unsupported(conf, env_file) -> list:
    """The account variables Odoo would get from the env file (odoo.conf leaves them unset) whose value this
    reader does not implement. Raises AccountError when a file cannot be read."""
    options, values = conf_options(conf), env_values(env_file)
    return [name for _key, option, name, _variable in ACCOUNT
            if option not in options and values.get(name) is UNSUPPORTED]


def unsupported_fix(env_file, names) -> str:
    return (f'write {" and ".join(names)} in {env_file} literally in single quotes: oasis does not read compose '
            'interpolation ($) or double-quoted escapes (\\), so Odoo would get another credential')


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
    cannot be read, nothing: the command runs as before (Odoo reports its odoo.conf, doctor both files). A value
    this reader does not implement raises UnsupportedValue: never another credential."""
    try:
        found = account(conf, env_file)
    except AccountError:
        return ''
    refused = [name for key, _option, name, _variable in ACCOUNT
               if key in found['from_env'] and found[key] is UNSUPPORTED]
    if refused:
        raise UnsupportedValue(env_file, refused)
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
            if found[key] is UNSUPPORTED:
                return 'failed'
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


def compose_lines(compose):
    """The lines of the compose file, or None when it cannot be read."""
    try:
        with open(compose, encoding='utf-8') as stream:
            return stream.read().splitlines()
    except (OSError, UnicodeError):
        return None


def published_ports(lines) -> set:
    """The host ports the PUBLISHED_PORT entries of lines publish to 5432."""
    ports = set()
    for line in lines:
        match = PUBLISHED_PORT.fullmatch(line)
        if match and 1 <= int(match.group(2)) <= 65535:
            ports.add(int(match.group(2)))
    return ports


def published_port(compose):
    """The one host port the compose file publishes to 5432 (PUBLISHED_PORT), or None: none, several
    different ones, or an unreadable file."""
    lines = compose_lines(compose)
    ports = published_ports(lines) if lines is not None else set()
    return ports.pop() if len(ports) == 1 else None


def port_entries(lines):
    """The lines of the block of each `ports:` key of lines (block style, read by indentation as YAML does): those
    indented deeper than the key, and its `- ` items at the key's own indentation; blank and comment lines
    included. No YAML parser is used."""
    entries, indent = [], None
    for line in lines:
        stripped = line.strip()
        if indent is not None and stripped and not stripped.startswith('#'):
            width = len(line) - len(line.lstrip())
            if width < indent or (width == indent and not stripped.startswith('-')):
                indent = None
        if indent is not None:
            entries.append(line)
            continue
        key = PORTS_KEY.fullmatch(line)
        if key is not None:
            indent = len(key.group(1))
    return entries


def port_mapping(compose):
    """(the one host port the compose file publishes to 5432 or None, why that port cannot be read or None): no
    reason with no port means no entry names 5432; a reason means the file cannot be read, it publishes several
    ports, or an entry under ports: is not one PUBLISHED_PORT reads (OTHER_PORT_ENTRY)."""
    lines = compose_lines(compose)
    if lines is None:
        return None, 'it cannot be read'
    if any(OTHER_PORT_ENTRY.fullmatch(line) and not PUBLISHED_PORT.fullmatch(line) for line in port_entries(lines)):
        return None, UNREAD_ENTRY
    ports = published_ports(lines)
    if len(ports) > 1:
        return None, 'several ports'
    return (ports.pop() if ports else None), None


def recreate_command(compose, program, root) -> str:
    """The Tier B command that recreates the volume of the compose project, with --confirm when it has a name."""
    try:
        project = compose_project(compose)
    except (OSError, UnicodeError):
        project = None
    command = [program, '--project', str(root), 'recreate-database-volume']
    if project is not None:
        command += ['--confirm', project]
    return ' '.join(shlex.quote(word) for word in command)


def authentication_fix(conf, env_file, compose, program, root) -> str:
    """What fixes Odoo's account being refused: odoo.conf's own account values when they differ from the
    env file's; else, when the port the compose file publishes to 5432 cannot be read (port_mapping), both
    fixes, since oasis cannot tell which server odoo.conf names; else, when odoo.conf names the endpoint the
    compose service publishes (db_host 127.0.0.1 or localhost, and its published port), recreating the volume,
    which was initialized with other credentials; else correcting the account on the server odoo.conf names,
    which is not that service."""
    try:
        options = differing(conf, env_file)
    except AccountError:
        options = []
    if options:
        names = ' and '.join(options)
        return (f'{conf} sets {names} to other values than {env_file}: remove {names} from {conf} so Odoo uses the '
                f'account of {env_file}, then run {program} doctor again')
    try:
        endpoint = conf_options(conf)
    except AccountError:
        endpoint = {}
    host, port = endpoint.get('db_host'), endpoint.get('db_port')
    published, unread = port_mapping(compose)
    where = (f'db_host {host}' if host else 'no db_host') + (f', db_port {port}' if port else ', no db_port')
    if unread is not None:
        return (f'the PostgreSQL that {conf} names ({where}) refuses the account Odoo uses, and oasis could not read '
                f'the port {compose} publishes to 5432 ({unread}), so it cannot tell whether that server is the service '
                f'of {compose}: if it is, {recreate_command(compose, program, root)} recreates its volume with the '
                f'account of {env_file} (Tier B: it deletes every database of the service); if it is not, correct that '
                f'account on that server; then run {program} doctor again')
    try:
        local = host in LOCAL_HOSTS and published is not None and int(port or POSTGRES_PORT) == published
    except ValueError:
        local = False
    if not local:
        service = (f'published on 127.0.0.1:{published}' if published is not None
                   else 'no port published to 5432 found')
        return (f'the PostgreSQL that {conf} names ({where}) refuses the account Odoo uses, and it is not the service '
                f'of {compose} ({service}): correct that account on that server, or set db_host = 127.0.0.1 and the '
                f'db_port {compose} publishes in {conf}; then run {program} doctor again')
    return (f'the PostgreSQL that {conf} names refuses the account Odoo uses: its volume was initialized with other '
            f'credentials than {env_file}; {recreate_command(compose, program, root)} recreates it with them '
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
        if len(argv) == 3 and argv[0] == 'unsupported':
            names = unsupported(argv[1], argv[2])
            if names:
                print(f'FAIL env_file=unsupported_value {",".join(names)}\n  fix: {unsupported_fix(argv[2], names)}')
                return 1
            return 0
        if len(argv) == 2 and argv[0] == 'compose-project-name':
            value = env_values(argv[1], ['COMPOSE_PROJECT_NAME']).get('COMPOSE_PROJECT_NAME')
            if value is UNSUPPORTED:
                print(f'ERROR: {argv[1]} sets COMPOSE_PROJECT_NAME with compose interpolation ($) or a double-quoted '
                      'escape (\\), which oasis does not read.', file=sys.stderr)
                return 2
            if value:
                print(value)
            return 0
    except (AccountError, UnsupportedValue) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    print('Usage: db_account.py exports|probe|unsupported <odoo.conf> <env_file> | compose-project <compose file> | '
          'compose-project-name <env_file> | fix <odoo.conf> <env_file> <compose file> <program> <project root>',
          file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
