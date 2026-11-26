#!/usr/bin/env python3
"""Validate project account declarations and get the passwords of the new database's accounts.

On a terminal each password is asked with the echo off; Enter at its first prompt generates it. Without a
terminal every password is generated (v0.16.0 S2: no oasis workflow requires typing one). Generated
passwords (secrets.token_urlsafe(24)) are stored, never printed, in <database>.logins next to the env file
(mode 0600), once the database exists: written to a 0600 temporary file in that directory first, then
renamed into place only when the database was created, so a refused existing database keeps its file.
"""
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import warnings

from config import InvalidConfig, configuration, load, program_name

INVALID = 'ERROR: Invalid development user configuration.'
TERMINAL = 'ERROR: Password entry failed on the terminal; no database was created.'
LOGINS_HEADER = ('# Written by oasis init-dev-database: the generated passwords of {database} (docs/dev-database.md).\n'
                 '# One "<login> <password>" per line. Never commit this file.\n')


def logins_file(values, database) -> Path:
    """Where the generated passwords of database go: <database>.logins next to the env file."""
    return Path(values['ENV_FILE']).parent / f'{database}.logins'


def staged(path: Path, database, generated) -> Path:
    """A 0600 temporary file next to path with the generated passwords; renamed to path once the database
    exists."""
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.')
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(LOGINS_HEADER.format(database=database)
                     + ''.join(f'{login} {password}\n' for login, password in generated))
    return Path(name)


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
    payload = {'declaration': section, 'passwords': passwords, 'with_demo': args[3] == 'true'}
    runner = Path(__file__).with_name('dev_users_runtime.py')
    # Typed passwords exist only in process memory and the anonymous stdin pipe; generated ones also in the
    # 0600 logins file, staged before the database exists so that none is lost once it does.
    try:
        pending = staged(target, database, generated) if generated else None
    except OSError:
        print(f'ERROR: Cannot write the generated passwords next to {target}; no database was created.',
              file=sys.stderr)
        return 2
    try:
        result = subprocess.run([values['PYTHON'], '-B', str(runner), str(root), module, database],
                                input=json.dumps(payload), text=True, capture_output=True)
    except BaseException:
        if pending is not None:
            pending.unlink(missing_ok=True)
        raise
    stored = ''
    if pending is not None:
        if result.returncode == 3:
            # No database was created: an existing one keeps its logins file.
            pending.unlink(missing_ok=True)
        else:
            os.replace(pending, target)
            stored = f'Generated passwords: {target} (mode 0600): {", ".join(login for login, _password in generated)}'
    if result.returncode:
        # Never relay Odoo exceptions, SQL logs, or an unexpected child traceback.
        message = ('Could not create a fresh development database; existing data was not modified.'
                   if result.returncode == 3 else
                   'Development setup failed; the new database was retained.')
        print('ERROR: ' + message, file=sys.stderr)
        if stored:
            print(stored)
        return 1
    print(f'Development database initialized: {database}')
    print(f'Accounts ready: {len(logins)}')
    if stored:
        print(stored)
    return 0


if __name__ == '__main__':
    sys.exit(main())
