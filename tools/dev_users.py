#!/usr/bin/env python3
"""Validate project account declarations and collect passwords only on a terminal."""
import getpass
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib
import warnings

from config import InvalidConfig, load

INVALID = 'ERROR: Invalid development user configuration.'
TERMINAL = 'ERROR: Password entry requires an interactive terminal.'


def declaration(root):
    with (root / '.odoo19-agent.toml').open('rb') as stream:
        section = tomllib.load(stream).get('development')
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
    # Never let getpass fall back to visible piped input.
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        print(TERMINAL, file=sys.stderr)
        return 2
    if validate_only:
        return 0
    passwords = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            for login in logins:
                password = getpass.getpass(f'Password for {login}: ')
                confirmation = getpass.getpass(f'Confirm password for {login}: ')
                if not password or password != confirmation:
                    print('ERROR: Passwords must be nonempty and match; no database was created.',
                          file=sys.stderr)
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
    # Passwords exist only in process memory and the anonymous stdin pipe.
    result = subprocess.run([values['PYTHON'], '-B', str(runner), str(root), module, database],
                            input=json.dumps(payload), text=True, capture_output=True)
    if result.returncode:
        # Never relay Odoo exceptions, SQL logs, or an unexpected child traceback.
        message = ('Could not create a fresh development database; existing data was not modified.'
                   if result.returncode == 3 else
                   'Development setup failed; the new database was retained.')
        print('ERROR: ' + message, file=sys.stderr)
        return 1
    print(f'Development database initialized: {database}')
    print(f'Accounts ready: {len(logins)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
