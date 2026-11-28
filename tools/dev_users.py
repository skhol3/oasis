#!/usr/bin/env python3
"""Validate project account declarations and get the passwords of the new database's accounts.

The administrator keeps Odoo's default password (admin), or ODOO_ADMIN_PASSWORD of the env file
([tooling].env_file, the file of ODOO_DB_USER and ODOO_DB_PASSWORD) when it sets a non-empty one (v0.20.0 S7);
it is never asked. On a terminal each [[development.users]] password is asked with the echo off; Enter at its
first prompt generates it. Without a terminal every declared user's password is generated
(token_urlsafe(24); v0.16.0 S2: no oasis workflow requires typing one). No password is written to a file or
printed (v0.20.0 S8): the output says what each account's password is ("Odoo's default", "from <env file>
ODOO_ADMIN_PASSWORD", typed, or generated and not stored), never a value. A <database>.logins file an earlier
version wrote next to the env file is left as it is, with one WARN line.

The language and the country of the new database (v0.20.0 S12: init-dev-database's --lang and --country, what
Odoo's database manager form asks) are checked against the lists the form shows, read from the Odoo source, before
anything runs; the runner passes them to exp_create_database, which takes them the same way in every supported
series.

Usage (through init-dev-database): dev_users.py [--validate] <root> <module> <database> <true|false> <language>
<country, empty for none>
"""
import csv
import getpass
import json
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
import warnings
from xml.etree import ElementTree

from config import InvalidConfig, configuration, load, program_name, versions
from db_account import UNSUPPORTED, AccountError, UnsupportedValue, env_values
from dev_users_runtime import CREATED_THEN_FAILED
from odoo_addons_path import ConfError, config_arguments

INVALID = 'ERROR: Invalid development user configuration.'
TERMINAL = 'ERROR: Password entry failed on the terminal; no database was created.'
# The administrator's password (v0.20.0 S7): Odoo's own default, unless the env file sets this variable.
ADMIN_VARIABLE = 'ODOO_ADMIN_PASSWORD'
ODOO_DEFAULT_PASSWORD = 'admin'
TYPED = 'typed on the terminal'
GENERATED = 'generated, not stored or shown ({administrator} can set one in Odoo)'
# The language and country lists of Odoo's database manager form, in the Odoo source (every supported series), and the
# language of a database created without --lang (v0.20.0 S12).
LANGUAGES = 'odoo/addons/base/data/res.lang.csv'
COUNTRIES = 'odoo/addons/base/data/res_country_data.xml'
DEFAULT_LANGUAGE = 'en_US'


def legacy_logins(values, database) -> Path:
    """Where versions before 0.20.0 wrote the generated passwords of database: <database>.logins next to the
    env file. oasis no longer writes or reads it."""
    return Path(values['ENV_FILE']).parent / f'{database}.logins'


def administrator_password(values):
    """(the administrator's password, what the output says of it): ODOO_ADMIN_PASSWORD of the env file when it
    sets a non-empty value (db_account.env_values: the last assignment wins), else Odoo's default. Raises
    AccountError when the env file cannot be read, UnsupportedValue when its value is one oasis does not read."""
    env_file = values['ENV_FILE']
    value = env_values(env_file, [ADMIN_VARIABLE]).get(ADMIN_VARIABLE)
    if value is UNSUPPORTED:
        raise UnsupportedValue(env_file, [ADMIN_VARIABLE])
    if value:
        return value, f'from {env_file} {ADMIN_VARIABLE}'
    return ODOO_DEFAULT_PASSWORD, "Odoo's default"


def languages(source) -> list:
    """[(code, name)] of the languages Odoo offers, sorted by name: what its database manager form lists (exp_list_lang
    of odoo/service/db.py, odoo.tools.misc.scan_languages in every supported series: base/data/res.lang.csv), and
    like it [('en_US', 'English')] when that file cannot be read."""
    try:
        with (Path(source) / LANGUAGES).open(encoding='utf-8', newline='') as handle:
            reader = csv.reader(handle, delimiter=',', quotechar='"')
            fields = next(reader)
            code, name = fields.index('code'), fields.index('name')
            found = [(row[code], row[name]) for row in reader]
    except (OSError, UnicodeError, ValueError, IndexError, StopIteration, csv.Error):
        found = []
    return sorted(found or [(DEFAULT_LANGUAGE, 'English')], key=lambda item: item[1])


def countries(source) -> list:
    """[(code, name)] of the countries Odoo offers, sorted by name: what its database manager form lists
    (exp_list_countries of odoo/service/db.py in every supported series: the res.country records of
    base/data/res_country_data.xml, lowercase codes). Raises CountryError when that file cannot be read, as
    exp_list_countries fails there."""
    path = Path(source) / COUNTRIES
    try:
        records = ElementTree.parse(path).getroot().find('data').findall('record[@model="res.country"]')
        found = [(record.find('field[@name="code"]').text, record.find('field[@name="name"]').text)
                 for record in records]
    except (OSError, ElementTree.ParseError, AttributeError) as exc:
        raise CountryError(path) from exc
    if any(not isinstance(code, str) or not isinstance(name, str) for code, name in found):
        raise CountryError(path)
    return sorted(found, key=lambda item: item[1])


class CountryError(Exception):
    """The countries' file of the Odoo source cannot be read (its path)."""


def check_language_and_country(values, language, country):
    """The refusal of a language or country Odoo does not offer (an empty country: none), or None. The codes are the
    ones the database manager form takes: exp_create_database's lang and country_code (every supported series)."""
    source, series = values['ODOO_SOURCE'], values['ODOO_VERSION']
    if language not in [code for code, _name in languages(source)]:
        return (f'ERROR: Unknown language {language}: Odoo {series} lists its languages in {Path(source) / LANGUAGES}; '
                'init-dev-database --plan --json shows them. No database was created.')
    if country:
        try:
            codes = [code for code, _name in countries(source)]
        except CountryError as error:
            return f'ERROR: Cannot read the countries of Odoo {series}: {error}. No database was created.'
        if country not in codes:
            return (f'ERROR: Unknown country {country}: Odoo {series} lists its countries in '
                    f'{Path(source) / COUNTRIES}; init-dev-database --plan --json shows them. No database was '
                    'created.')
    return None


def account_line(login, source, administrator=False) -> str:
    """What the output says of an account's password: where it comes from, never its value."""
    return f'Account {login}{" (administrator)" if administrator else ""}, password: {source}'


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
    if len(args) != 6 or args[3] not in ('true', 'false'):
        print(INVALID, file=sys.stderr)
        return 2
    root, module, database, language, country = Path(args[0]), args[1], args[2], args[4], args[5]
    try:
        values = load(root)
        section, logins = declaration(root)
    except (OSError, ValueError, TypeError, InvalidConfig):
        print(INVALID, file=sys.stderr)
        return 2
    env_directory = Path(values['ENV_FILE']).parent
    if not env_directory.is_dir():
        print(f'ERROR: {env_directory} does not exist: run {program_name()} setup --apply; no '
              'database was created.', file=sys.stderr)
        return 2
    try:
        admin_password, admin_source = administrator_password(values)
    except (AccountError, UnsupportedValue) as error:
        # The message names the file and the variable, never a value (db_account.py).
        print(f'ERROR: {error}', file=sys.stderr)
        return 2
    with_demo = args[3] == 'true'
    try:
        runtime = runtime_values(values, with_demo)
    except ConfError as error:
        # The message names the path, never content (odoo_addons_path.py).
        print(f'ERROR: {error}', file=sys.stderr)
        return 2
    refusal = check_language_and_country(values, language, country)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    if validate_only:
        return 0
    legacy = legacy_logins(values, database)
    if legacy.exists():
        print(f'WARN: {legacy} is from an earlier oasis version: oasis no longer writes or reads it; it is left as '
              'it is.', file=sys.stderr)
    administrator = account_line(logins[0], admin_source, administrator=True)
    passwords, sources = [admin_password], [administrator]
    # Only a terminal is asked, and only for the declared users (getpass never falls back to visible piped
    # input); otherwise their passwords are generated.
    interactive = len(logins) > 1 and sys.stdin.isatty() and sys.stderr.isatty()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            if interactive:
                print('Enter at a password prompt generates one, which is not stored or shown.', file=sys.stderr)
            for login in logins[1:]:
                password = getpass.getpass(f'Password for {login}: ') if interactive else ''
                if not password:
                    password = secrets.token_urlsafe(24)
                    sources.append(account_line(login, GENERATED.format(administrator=logins[0])))
                elif password != getpass.getpass(f'Confirm password for {login}: '):
                    print('ERROR: Passwords must match; no database was created.', file=sys.stderr)
                    return 2
                else:
                    sources.append(account_line(login, TYPED))
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
    payload = {'declaration': section, 'passwords': passwords, 'with_demo': with_demo, 'lang': language,
               'country': country or None, 'runtime': runtime}
    runner = Path(__file__).with_name('dev_users_runtime.py')
    # The passwords exist only in process memory and the anonymous stdin pipe: no file holds them.
    try:
        result = subprocess.run([values['PYTHON'], '-B', str(runner), str(root), module, database],
                                input=json.dumps(payload), text=True, capture_output=True)
    except KeyboardInterrupt:
        # The runner may have created the database already, with the administrator's password set.
        print(f'ERROR: Interrupted while creating {database}; it may exist: {program_name()} list-databases shows it.',
              file=sys.stderr)
        print(administrator)
        return 130
    if result.returncode != 3 and not created(result):
        # Never relay the child's output; whether the database exists is unknown.
        print(f'ERROR: Development setup stopped unexpectedly (exit {result.returncode}); {database} may exist: '
              f'{program_name()} list-databases shows it.', file=sys.stderr)
        print(administrator)
        return 1
    if result.returncode == 3:
        # Never relay Odoo exceptions, SQL logs, or an unexpected child traceback.
        print('ERROR: Could not create a fresh development database; existing data was not modified.',
              file=sys.stderr)
        return 1
    if result.returncode:
        # Created, then a later step failed: the administrator's password is already set.
        print('ERROR: Development setup failed; the new database was retained.', file=sys.stderr)
        print(administrator)
        return 1
    print(f'Development database initialized: {database}')
    print(f'Accounts ready: {len(logins)}')
    for line in sources:
        print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
