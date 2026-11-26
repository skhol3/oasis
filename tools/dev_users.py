#!/usr/bin/env python3
"""Validate project account declarations and get the passwords of the new database's accounts.

On a terminal each password is asked with the echo off; Enter at its first prompt generates it. Without a
terminal every password is generated (v0.16.0 S2: no oasis workflow requires typing one). Generated
passwords (secrets.token_urlsafe(24)) are stored, never printed, in <database>.logins next to the env file
(mode 0600), once the database exists: written to a 0600 temporary file in that directory first (removed when
it cannot be written), then renamed into place only when the runner says the database was created (exit 0, or
4: created, then a later step failed), so a refused existing database keeps its file (exit 3). When the outcome
is unknown (another exit, such as 1 for an uncaught error, or an interrupt after the runner started) or the
rename fails, the temporary file is kept and its path printed, never a password.
"""
import contextlib
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
import warnings

from config import InvalidConfig, configuration, load, program_name, versions
from dev_users_runtime import CREATED_THEN_FAILED
from odoo_addons_path import ConfError, config_arguments

INVALID = 'ERROR: Invalid development user configuration.'
TERMINAL = 'ERROR: Password entry failed on the terminal; no database was created.'
LOGINS_HEADER = ('# Written by oasis init-dev-database: the generated passwords of {database} (docs/dev-database.md).\n'
                 '# One "<login> <password>" per line. Never commit this file.\n')


def logins_file(values, database) -> Path:
    """Where the generated passwords of database go: <database>.logins next to the env file."""
    return Path(values['ENV_FILE']).parent / f'{database}.logins'


def staged(path: Path, database, generated) -> Path:
    """A 0600 temporary file next to path with the generated passwords; renamed to path once the database
    exists. Removed again when it cannot be written (OSError raised)."""
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(LOGINS_HEADER.format(database=database)
                         + ''.join(f'{login} {password}\n' for login, password in generated))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(name)
        raise
    return Path(name)


def kept(pending: Path, note, generated) -> str:
    """The line that names a staged logins file left in place (never a password)."""
    return f'Generated passwords: {pending} (mode 0600; {note}): {", ".join(login for login, _password in generated)}'


def created(result) -> bool:
    """Whether the runner (dev_users_runtime.py) says the database was created: exit 0 (initialized) or
    CREATED_THEN_FAILED (4: created, then a later step failed). Any other exit is unknown (3 alone says nothing
    was created; 1 is an error the runner did not catch, an import error included)."""
    return result.returncode in (0, CREATED_THEN_FAILED)


def runtime_values(values, with_demo):
    """What dev_users_runtime.py needs from the configuration, decided here: it runs with the environment's
    Python (3.7+), which cannot import config.py. The demo options and the users' groups field of the Odoo
    series (tools/odoo_versions.py): demo-off through config.py, demo-on (nothing in a series that loads demo
    data by default); and the options of common.sh's odoo_config_arguments, from the same decision: -c, then
    --addons-path (composed for a path-free odoo.conf, or a linked worktree's own root) and --data-dir
    ([tooling].data_dir) when they apply. Raises ConfError when the configuration cannot be read."""
    capability = versions().capability
    return {
        'python': values['PYTHON'], 'odoo_bin': values['ODOO_BIN'], 'odoo_source': values['ODOO_SOURCE'],
        'demo_flags': (capability(values['ODOO_VERSION'], 'demo_on_args') if with_demo
                       else shlex.split(values['ODOO_DEMO_OFF_ARGS'])),
        'groups_field': capability(values['ODOO_VERSION'], 'user_groups_field'),
        'config_args': config_arguments(values),
    }


def declaration(root):
    # [development] of the workspace file.
    section = configuration(root)[0].get('development')
    if (not isinstance(section, dict) or set(section) - {'administrator_login', 'users', 'demo_modules'}
            or 'administrator_login' not in section):
        raise ValueError
    modules = section.get('demo_modules', [])
    if (not isinstance(modules, list)
            or any(not isinstance(module, str) or not re.fullmatch(r'[A-Za-z0-9_]+', module)
                   for module in modules) or len(modules) != len(set(modules))):
        raise ValueError
    users = section.get('users', [])
    if not isinstance(users, list):
        raise ValueError
    logins = [section['administrator_login']]
    for user in users:
        if (not isinstance(user, dict) or set(user) != {'login', 'name', 'groups'}
                or not isinstance(user['name'], str) or not user['name'].strip()
                or any(ord(c) < 32 for c in user['name'])
                or not isinstance(user['groups'], list) or not user['groups']
                or any(not isinstance(group, str) or not re.fullmatch(
                    r'[A-Za-z0-9_]+\.[A-Za-z0-9_]+', group) for group in user['groups'])):
            raise ValueError
        logins.append(user['login'])
    if (any(not isinstance(login, str) or not re.fullmatch(r'[A-Za-z0-9_.@+-]+', login)
            for login in logins) or len(logins) != len(set(logins))):
        raise ValueError
    return section, logins


def main():
    validate_only = len(sys.argv) > 1 and sys.argv[1] == '--validate'
    args = sys.argv[2:] if validate_only else sys.argv[1:]
    if len(args) != 4 or args[3] not in ('true', 'false'):
        print(INVALID, file=sys.stderr)
        return 2
    root, module, database = Path(args[0]), args[1], args[2]
    try:
        values = load(root)
        section, logins = declaration(root)
    except (OSError, ValueError, TypeError, InvalidConfig):
        print(INVALID, file=sys.stderr)
        return 2
    target = logins_file(values, database)
    if not target.parent.is_dir():
        print(f'ERROR: {target.parent} does not exist: run {program_name()} setup --apply; no '
              'database was created.', file=sys.stderr)
        return 2
    with_demo = args[3] == 'true'
    try:
        runtime = runtime_values(values, with_demo)
    except ConfError as error:
        # The message names the path, never content (odoo_addons_path.py).
        print(f'ERROR: {error}', file=sys.stderr)
        return 2
    if validate_only:
        return 0
    passwords, generated = [], []
    # Only a terminal is asked (getpass never falls back to visible piped input); otherwise every password
    # is generated.
    interactive = sys.stdin.isatty() and sys.stderr.isatty()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            if interactive:
                print(f'Enter at a password prompt generates one into {target} (mode 0600).', file=sys.stderr)
            for login in logins:
                password = getpass.getpass(f'Password for {login}: ') if interactive else ''
                if not password:
                    password = secrets.token_urlsafe(24)
                    generated.append((login, password))
                elif password != getpass.getpass(f'Confirm password for {login}: '):
                    print('ERROR: Passwords must match; no database was created.', file=sys.stderr)
                    return 2
                passwords.append(password)
    except (EOFError, KeyboardInterrupt, getpass.GetPassWarning, OSError):
        print(TERMINAL, file=sys.stderr)
        return 2
    compose = ['docker', 'compose', '--env-file', values['ENV_FILE'],
               '-f', values['COMPOSE_FILE']]
    if subprocess.run(compose + ['up', '-d', '--wait', '--wait-timeout', '60',
                                 values['DB_SERVICE']], capture_output=True).returncode:
        print('ERROR: Local database service is unavailable; no initialization was attempted.',
              file=sys.stderr)
        return 1
    payload = {'declaration': section, 'passwords': passwords, 'with_demo': with_demo, 'runtime': runtime}
    runner = Path(__file__).with_name('dev_users_runtime.py')
    # Typed passwords exist only in process memory and the anonymous stdin pipe; generated ones also in the
    # 0600 logins file, staged before the database exists so that none is lost once it does.
    try:
        pending = staged(target, database, generated) if generated else None
    except OSError:
        print(f'ERROR: Cannot write the generated passwords next to {target}; no database was created.',
              file=sys.stderr)
        return 2
    unknown = f'rename it to {target} if {database} exists'
    try:
        result = subprocess.run([values['PYTHON'], '-B', str(runner), str(root), module, database],
                                input=json.dumps(payload), text=True, capture_output=True)
    except KeyboardInterrupt:
        # The runner may have created the database already: its generated passwords stay where they are.
        print(f'ERROR: Interrupted while creating {database}; it may exist: {program_name()} list-databases shows it.',
              file=sys.stderr)
        if pending is not None:
            print(kept(pending, unknown, generated))
        return 130
    except BaseException:
        if pending is not None:
            pending.unlink(missing_ok=True)
        raise
    if result.returncode != 3 and not created(result):
        # Never relay the child's output; whether the database exists is unknown.
        print(f'ERROR: Development setup stopped unexpectedly (exit {result.returncode}); {database} may exist: '
              f'{program_name()} list-databases shows it.', file=sys.stderr)
        if pending is not None:
            print(kept(pending, unknown, generated))
        return 1
    stored = renamed = ''
    if pending is not None:
        if result.returncode == 3:
            # No database was created: an existing one keeps its logins file.
            pending.unlink(missing_ok=True)
        else:
            try:
                os.replace(pending, target)
                stored = (f'Generated passwords: {target} (mode 0600): '
                          f'{", ".join(login for login, _password in generated)}')
            except OSError:
                renamed = f'ERROR: Cannot rename {pending} to {target}; the generated passwords stay in {pending}.'
                stored = kept(pending, f'it could not be renamed to {target}', generated)
    if result.returncode:
        # Never relay Odoo exceptions, SQL logs, or an unexpected child traceback.
        message = ('Could not create a fresh development database; existing data was not modified.'
                   if result.returncode == 3 else
                   'Development setup failed; the new database was retained.')
        print('ERROR: ' + message, file=sys.stderr)
        if renamed:
            print(renamed, file=sys.stderr)
        if stored:
            print(stored)
        return 1
    print(f'Development database initialized: {database}')
    print(f'Accounts ready: {len(logins)}')
    if stored:
        print(stored)
    if renamed:
        print(renamed, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
