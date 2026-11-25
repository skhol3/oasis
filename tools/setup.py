#!/usr/bin/env python3
"""Set up a checkout for oasis (`oasis setup`, v0.14.0 S1, S6, S7, S9, S10).

User-run: --apply writes the project's and the machine's configuration (the Gentle Shell bash guard
blocks it for agents; the plan stays allowed). Without --apply it prints the plan and changes
nothing. It infers what it can (the checkout, the Odoo series from the module manifests, the source
from the machine file), asks on a terminal what it cannot (every answer also has a flag; without a
terminal a missing answer is an error naming the flag), adopts what exists and never overwrites:
an existing workspace file, odoo.conf, compose file, environment file, requirement inputs, locks and
environment are kept, and only the missing pieces are created. Without a workspace file, the
workspace is the checkout itself: oasis-workspace.toml at its root and config/, data/, logs/ and the
environment under .oasis/, both excluded in .git/info/exclude (never the tracked .gitignore);
--workspace <dir> chooses another directory at or above the checkout. The Odoo source goes to the
machine file, never to a new workspace file. The locks are compiled with tools/locks.py, as
bootstrap does, then the environment is created with uv and synced. The environment file gets only
the variable names, with empty values: it is never read or printed.

In a checkout of a series its workspace file has no section for (v0.15.0 S5), setup appends a
[series."<x.y>"] section to that file (a version 1 file becomes version 2, that line only) and plans
the files of that series, adopting a folder that already holds them (series_plan).
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tomllib

VALUE_OPTIONS = ('--series', '--community', '--enterprise', '--workspace', '--name', '--config-dir')
REPEATED_OPTIONS = ('--exception',)
FLAG_OPTIONS = ('--apply', '--plan', '--no-enterprise')
# Options that only answer the questions of a new configuration (an existing one is only filled in).
SOURCE_OPTIONS = ('--community', '--enterprise', '--no-enterprise')
# Options that only apply when setup adds a series section to an existing workspace file, and every
# option accepted then.
SECTION_OPTIONS = ('--exception', '--config-dir')
SERIES_PLAN_OPTIONS = ('--apply', '--plan', *SOURCE_OPTIONS, *SECTION_OPTIONS)
# The workspace_version line a version 1 file must have, once, to be converted (only the 1 changes).
VERSION_LINE = re.compile(r'(?m)^(workspace_version[ \t]*=[ \t]*)(1)([ \t]*(?:#[^\r\n]*)?\r?)$')
SECTION_COMMENT = ('# Added by oasis setup: what differs for the Odoo {series} checkouts '
                   '(docs/setup.md#another-odoo-series).\n')
COMPOSE_NAMES = ('compose.yml', 'compose.yaml', 'docker-compose.yml', 'docker-compose.yaml')
NAME = re.compile(r'[a-z][a-z0-9_]{1,19}')
NAME_RULE = '2 to 20 lowercase letters, digits or underscores, starting with a letter'
PORTS = range(5432, 5532)
# The port an odoo.conf without db_port connects to: PostgreSQL's default.
POSTGRES_PORT = 5432
# A compose short-syntax entry that publishes the container's PostgreSQL port: `- '127.0.0.1:6001:5432'`,
# `- "6001:5432"`, `- 6001:5432/tcp`, with an optional host address and trailing comment. Anything else
# (the long syntax, ranges, variables) is not read; no YAML parser is used.
PUBLISHED_PORT = re.compile(r'''\s*-\s*(["']?)(?:(?:[0-9]{1,3}(?:\.[0-9]{1,3}){3}|localhost|\[[0-9A-Fa-f:]*\]):)?'''
                            r'''([0-9]{1,5}):5432(?:/tcp)?\1\s*(?:#.*)?''')
LAYOUT = '.oasis'
EXCLUDES = ('/oasis-workspace.toml', f'/{LAYOUT}/')
DIRECTORY_MODE = 0o700
DRY_RUN = 'dry run: nothing changed; run with --apply to set up'
WORKSPACE_HEADER = ('# Written by oasis setup. Paths are relative to this file, addons_paths to each checkout;\n'
                    '# the Odoo source comes from the machine file (docs/workspace-file.md#machine-file).\n')
MACHINE_HEADER = ('# Written by oasis setup: the Odoo source of each series on this machine '
                  '(docs/workspace-file.md#machine-file).\n')
ENV_FILE = ('# Written by oasis setup: fill in both values, the PostgreSQL account of the compose service. '
            'Never commit this file.\nODOO_DB_USER=\nODOO_DB_PASSWORD=\n')
CONF = '''; Written by oasis setup. Path-free: oasis passes --addons-path and --data-dir on the command line.
; Set db_user and db_password to the ODOO_DB_USER and ODOO_DB_PASSWORD of {env_file}.
[options]
db_host = 127.0.0.1
db_port = {port}
db_user =
db_password =
'''
COMPOSE = '''# Written by oasis setup: the PostgreSQL service of this workspace. oasis runs it as
# docker compose --env-file <env_file> -f <this file>; the account comes from the environment file.
name: {name}
services:
  {service}:
    image: postgres:{postgres}
    environment:
      POSTGRES_DB: postgres
      POSTGRES_USER: ${{ODOO_DB_USER}}
      POSTGRES_PASSWORD: ${{ODOO_DB_PASSWORD}}
      ODOO_DB_USER: ${{ODOO_DB_USER}}
      ODOO_DB_PASSWORD: ${{ODOO_DB_PASSWORD}}
    ports:
      - '127.0.0.1:{port}:5432'
    volumes:
      - db:/var/lib/postgresql/data
    healthcheck:
      test: ['CMD-SHELL', 'pg_isready -U "$${{POSTGRES_USER}}" -d postgres']
      interval: 2s
      retries: 30
volumes:
  db:
'''
RUNTIME_IN = '# Written by oasis setup: the requirements of the Odoo source.\n-r {source}/requirements.txt\n'
DEV_IN = ('# Written by oasis setup: the runtime requirements within their lock; add development tools '
          'below.\n-c runtime.txt\n-r runtime.in\n')
HELP = '''
Sets up the checkout (--project, else the git top level of the current directory) for oasis.
Without --apply it prints the plan and changes nothing; --plan asks for that plan explicitly and
can never apply. With --apply it creates only what is missing and keeps everything that exists:
  - the machine file's [series."<x.y>"] entry with the Odoo source (--community, --enterprise or
    --no-enterprise; asked on a terminal), when the machine file has none; an existing entry is
    used and never edited;
  - oasis-workspace.toml (no source keys; database prefixes from the checkout's name or --name),
    by default at the checkout's root with config/, data/, logs/ and the environment under .oasis/,
    both excluded from git in .git/info/exclude; --workspace <dir> puts them in <dir>, which must
    be at or above the checkout; an existing workspace file is adopted;
  - a path-free odoo.conf, a compose file with the PostgreSQL service, the environment file with
    ODOO_DB_USER and ODOO_DB_PASSWORD (empty values, mode 0600), runtime.in and dev.in;
  - the locks (uv pip compile, as bootstrap --apply) and the Python environment (uv venv, uv pip sync).
The series comes from the module manifests (<series>.x.y.z), else from the machine file's single series,
else --series. It ends with the next steps.

In a checkout of a series the existing workspace file has no section for (its oasis-checkout.toml
odoo_version, else its module manifests, the modules of --exception <module> left out), it appends a
[series."<x.y>"] section to that file (a workspace_version 1 file becomes 2, that line only) and
creates that series' missing files: by default in <config folder>/<x.y>/, or in a folder that already
holds its odoo.conf or compose file (<config folder>/odoo-<major>/, ...; --config-dir <dir> names one),
which is adopted. --exception (repeatable) writes series_exceptions.
'''


class Refused(Exception):
    """A refusal before any change: exit 2 with the message."""


def sibling(name: str):
    """A packaged helper loaded from its file (python3 -I keeps the tools directory off sys.path)."""
    spec = importlib.util.spec_from_file_location(f'oasis_setup_{name}', Path(__file__).with_name(f'{name}.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


config, migrate, locks = sibling('config'), sibling('migrate'), sibling('locks')


def usage() -> str:
    return (f'Usage: {config.usage_name()} setup [--series <x.y>] [--community <dir>] '
            '[--enterprise <dir> | --no-enterprise] [--workspace <dir>] [--name <name>] '
            '[--exception <module>]... [--config-dir <dir>] [--apply | --plan]')


def parse_arguments(arguments: list[str]) -> dict | None:
    """The options in argument order, or None for a usage error (no abbreviations)."""
    options, index = {}, 0
    while index < len(arguments):
        argument = arguments[index]
        key, equals, value = argument.partition('=')
        if argument in FLAG_OPTIONS and argument not in options:
            options[argument] = True
        elif equals and key in REPEATED_OPTIONS:
            options.setdefault(key, []).append(value)
        elif argument in REPEATED_OPTIONS and index + 1 < len(arguments):
            index += 1
            options.setdefault(argument, []).append(arguments[index])
        elif equals and key in VALUE_OPTIONS and key not in options:
            options[key] = value
        elif argument in VALUE_OPTIONS and argument not in options and index + 1 < len(arguments):
            index += 1
            options[argument] = arguments[index]
        else:
            return None
        index += 1
    if ('--apply' in options and '--plan' in options) or ('--enterprise' in options and '--no-enterprise' in options):
        return None
    return options


class Questions:
    """What setup cannot infer: asked on a terminal, else refused with the flag that answers it."""

    def __init__(self):
        self.interactive = sys.stdin.isatty() and sys.stderr.isatty()

    def ask(self, prompt: str, refusal: str) -> str:
        if not self.interactive:
            raise Refused(refusal)
        sys.stderr.write(prompt)
        sys.stderr.flush()
        line = sys.stdin.readline()
        if not line:
            raise Refused(refusal)
        return line.strip()


# -- inference -------------------------------------------------------------------------------------

def modules(root: Path) -> list[tuple[str, str | None]]:
    """(addon root relative to root, declared series or None) of every module manifest directly in
    root or one directory below it; hidden directories are skipped. The series is read as the series
    guard reads it (config.manifest_series: a series-style version of a known or plausible series)."""
    found = []
    for manifest in sorted([*root.glob('*/__manifest__.py'), *root.glob('*/*/__manifest__.py')]):
        if any(part.startswith('.') for part in manifest.relative_to(root).parts):
            continue
        declared = config.manifest_series(manifest)
        found.append((manifest.parent.parent.relative_to(root).as_posix(), declared[0] if declared else None))
    return found


def checkout_kind(root: Path) -> tuple[str, Path | None]:
    try:
        kind, _top, main = config.git_checkout(root)
    except config.GitFailed as exc:
        if config.dot_git(root) is None:
            return 'none', None
        raise Refused(f'Cannot read the git checkout {root}: {exc}.') from exc
    return kind, main


def read_machine() -> tuple[Path, bytes | None, dict]:
    """The machine file's path, its bytes (None when absent) and its document, checked like oasis
    reads it (trust and every key)."""
    path = config.machine_file()
    if path is None:
        raise Refused('Cannot place the machine file: there is no home directory; set XDG_CONFIG_HOME.')
    if not os.path.lexists(path):
        return path, None, {}
    try:
        config.machine_series(config.versions().supported()[0])
        raw = path.read_bytes()
        return path, raw, tomllib.loads(raw.decode('utf-8'))
    except config.InvalidConfig as exc:
        raise Refused(str(exc)) from exc
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise Refused(f'Cannot read {path}.') from exc


def choose_series(root, options, machine_document, questions) -> tuple[str, str]:
    supported = config.versions().supported()

    def checked(series, refusal=None):
        if series not in supported:
            raise Refused(refusal or f'Unsupported series {series}; supported: {", ".join(supported)}.')
        return series
    if '--series' in options:
        return checked(options['--series']), 'from --series'
    declared = sorted({series for _root, series in modules(root) if series})
    if len(declared) > 1:
        raise Refused(f'The module manifests of {root} declare several Odoo series ({", ".join(declared)}); '
                      'pass --series <x.y>.')
    if declared:
        return checked(declared[0], f'The module manifests of {root} declare Odoo {declared[0]}, which oasis '
                                    f'does not support (supported: {", ".join(supported)}).'), 'from the module manifests'
    tables = machine_document.get('series', {})
    if len(tables) == 1:
        return next(iter(tables)), 'from the machine file'
    answer = questions.ask(f'Odoo series (supported: {", ".join(supported)}): ',
                           f'Cannot infer the Odoo series of {root}: no module manifest declares one and the '
                           f'machine file has no single series; pass --series <x.y> (supported: {", ".join(supported)}).')
    return checked(answer), 'answered'


def suggested_source(root: Path, series: str) -> Path | None:
    """An Odoo source of the series near the checkout, only ever offered, never chosen."""
    for ancestor in list(root.parents)[:4]:
        for candidate in (ancestor / 'odoo', ancestor / 'source' / 'odoo', ancestor / 'src' / 'odoo',
                          ancestor / series / 'odoo', ancestor / series / 'source' / 'odoo'):
            if config.release_is(candidate / 'odoo' / 'release.py', series):
                return candidate
    return None


def directory_answer(value: str, label: str) -> Path:
    if not value or not os.path.isabs(value) or not os.path.isdir(value):
        raise Refused(f'{label} requires an absolute existing directory.')
    return Path(value).resolve()


def community_source(value: str, label: str, series: str) -> Path:
    path = directory_answer(value, label)
    if not config.release_is(path / 'odoo' / 'release.py', series):
        raise Refused(f'{label} {path} is not an Odoo {series} source (no odoo/release.py that declares it).')
    return path


def choose_sources(root, series, options, machine, questions):
    """(community, enterprise or None, its origins, the plan lines and actions of the machine entry)."""
    path, raw, document = machine
    table = f'[series.{json.dumps(series)}]'
    if series in document.get('series', {}):
        _path, values = config.machine_series(series)
        if 'community' not in values:
            raise Refused(f'The machine file {path} has {table} without community; setup never edits an '
                          'existing entry: add community there yourself.')
        for key, flag in (('community', '--community'), ('enterprise', '--enterprise'), ('enterprise', '--no-enterprise')):
            # Only a flag that disagrees with the entry is refused: --no-enterprise against an entry with
            # Enterprise, a path against an entry without that key or with another path.
            if flag not in options:
                continue
            if (key in values if flag == '--no-enterprise'
                    else key not in values or str(Path(options[flag]).resolve()) != values[key]):
                state = f'already sets {key} for {series}' if key in values else f'has {table} without {key}'
                raise Refused(f'The machine file {path} {state}; setup never edits an existing entry: drop {flag}, '
                              'or change the machine file yourself.')
        if not config.release_is(Path(values['community']) / 'odoo' / 'release.py', series):
            raise Refused(f'The machine file {path} sets community {values["community"]} for {series}, which is '
                          f'not an Odoo {series} source.')
        origin = 'from the machine file'
        return (Path(values['community']), Path(values['enterprise']) if 'enterprise' in values else None,
                (origin, origin), [f'kept {path}: {table} gives the Odoo source'], [], values.get('environments'))
    if '--community' in options:
        community, community_origin = community_source(options['--community'], '--community', series), 'from --community'
    else:
        found = suggested_source(root, series)
        answer = questions.ask(
            f'Odoo Community source for {series} (absolute path)' + (f' [Enter: {found}]' if found else '') + ': ',
            f'No Odoo Community source for {series} in the machine file {path}: pass --community <dir>'
            + (f'; found {found}, a suggestion only: pass it to use it' if found else '') + '.')
        community, community_origin = community_source(answer or str(found or ''), 'The answer', series), 'answered'
    if '--enterprise' in options:
        enterprise, enterprise_origin = directory_answer(options['--enterprise'], '--enterprise'), 'from --enterprise'
    elif '--no-enterprise' in options:
        enterprise, enterprise_origin = None, 'from --no-enterprise'
    else:
        answer = questions.ask(f'Odoo Enterprise source for {series} (absolute path, empty for none): ',
                               f'Enterprise or not for {series}: pass --enterprise <dir> or --no-enterprise.')
        enterprise = directory_answer(answer, 'The answer') if answer else None
        enterprise_origin = 'answered'
    entry = f'{table}\ncommunity = {migrate.toml_string(str(community))}\n'
    if enterprise is not None:
        entry += f'enterprise = {migrate.toml_string(str(enterprise))}\n'
    if raw is None:
        if path.parent.exists() and migrate.untrusted(path.parent):
            raise Refused(f'Refusing to write {path}: {migrate.untrusted(path.parent)}.')
        text = MACHINE_HEADER + entry
        lines = [f'create {path} (mode 0600):'] + [f'  {line}' for line in text.splitlines()]
        actions = [*directories(path.parent, set()), ('create', path, text.encode(), 0o600)]
        new = text.encode()
    else:
        separator = b'' if not raw.strip() else b'\n' if raw.endswith(b'\n') else b'\n\n'
        new = raw + separator + entry.encode()
        lines = [f'add {table} to {path}:'] + [f'  {line}' for line in entry.splitlines()]
        actions = [('extend', path, raw, new)]
    expected = {'community': str(community), **({'enterprise': str(enterprise)} if enterprise else {})}
    try:
        if tomllib.loads(new.decode('utf-8')).get('series', {}).get(series) != expected:
            raise ValueError
    except (ValueError, UnicodeError):
        raise Refused(f'Cannot add {table} to {path}: edit it yourself.') from None
    return community, enterprise, (community_origin, enterprise_origin), lines, actions, None


def directories(target: Path, planned: set) -> list:
    """mkdir actions for target and its missing parents, outermost first, each planned once."""
    missing = []
    for directory in (target, *target.parents):
        if directory.exists() or directory in planned:
            break
        missing.append(directory)
    planned.update(missing)
    return [('mkdir', directory) for directory in reversed(missing)]


def free_port(taken=()) -> int:
    for port in PORTS:
        if port in taken:
            continue
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                continue
            return port
    raise Refused(f'No free port from {PORTS[0]} to {PORTS[-1]} on 127.0.0.1 for PostgreSQL.')


def git_exclude(root: Path) -> tuple[Path, list[str]]:
    """The checkout's info/exclude file and the EXCLUDES git does not ignore yet."""
    env = migrate.git_env()
    try:
        result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--path-format=absolute', '--git-path',
                                 'info/exclude'], capture_output=True, text=True, env=env, timeout=30)
        if result.returncode != 0 or not result.stdout.strip():
            raise OSError(result.stderr.strip())
        missing = []
        for pattern in EXCLUDES:
            ignored = subprocess.run(['git', '-C', str(root), 'check-ignore', '-q', '--no-index', '--',
                                      pattern.lstrip('/')], capture_output=True, env=env, timeout=30)
            if ignored.returncode not in (0, 1):
                raise OSError('git check-ignore failed')
            if ignored.returncode == 1:
                missing.append(pattern)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refused(f'Cannot read the git exclude file of {root}: {exc}.') from exc
    return Path(result.stdout.strip()), missing


# -- plan ------------------------------------------------------------------------------------------

def make_plan(root: Path, options: dict, questions: Questions) -> dict:
    """Every line to print, every change to make and the steps after them; nothing is written."""
    kind, main = checkout_kind(root)
    lines = [f'checkout: {root} ({"outside git" if kind == "none" else kind})']
    actions, planned = [], set()
    workspace = config.workspace_file(root)
    machine = read_machine()
    if workspace is not None:
        target = section_target(root, workspace, options)
        if target is not None:
            return series_plan(root, kind, options, questions, workspace, machine, target, lines)
        try:
            document, base, workspace, name, origins, refusal = config.layered_configuration(root)
        except config.InvalidConfig as exc:
            raise Refused(str(exc)) from exc
        lines.append(f'workspace: {workspace} (existing)')
        try:
            values, missing_source = config.assignments(document, root, base, workspace, name,
                                                        missing_source=refusal), False
        except config.InvalidConfig as exc:
            if str(exc) != refusal:
                raise Refused(str(exc)) from exc
            values, missing_source = None, True
        for option in options:
            if option not in ('--apply', '--plan') and not (missing_source and option in SOURCE_OPTIONS):
                raise Refused(f'{option}: {root} is already configured by {workspace}; setup only fills what is '
                              'missing.')
        if missing_source:
            series = document['tooling']['version']
            community, enterprise, origin, machine_lines, machine_actions, _envs = choose_sources(
                root, series, options, machine, questions)
            lines += [f'community: {community} ({origin[0]})', f'enterprise: {enterprise or "none"} ({origin[1]})',
                      *machine_lines]
            actions += machine_actions
            document['tooling']['community'] = str(community)
            if enterprise is not None and 'enterprise' not in document['tooling']:
                document['tooling']['enterprise'] = str(enterprise)
            try:
                values = config.assignments(document, root, base, workspace, name)
            except config.InvalidConfig as exc:
                raise Refused(str(exc)) from exc
        elif origins['ODOO_SOURCE_FROM'] == 'machine':
            lines.append(f'kept {machine[0]}: [series.{json.dumps(document["tooling"]["version"])}] gives the '
                         'Odoo source')
        directory, new = workspace.parent, False
    else:
        for option in SECTION_OPTIONS:
            if option in options:
                raise Refused(f'{option}: {root} has no workspace file; it only applies when setup adds a '
                              '[series."<x.y>"] section to one.')
        if kind == 'linked':
            raise Refused(f'{root} is a linked worktree of {main}: run {config.program_name()} setup in the main '
                          'checkout.')
        directory = root
        if '--workspace' in options:
            directory = Path(options['--workspace']).resolve()
            if not root.is_relative_to(directory):
                raise Refused(f'Refusing --workspace {directory}: it is not at or above the checkout {root}.')
        workspace = directory / config.WORKSPACE_NAME
        reason = migrate.untrusted(directory)
        if reason:
            raise Refused(f'Refusing to write {workspace}: {reason}.')
        series, series_origin = choose_series(root, options, machine[2], questions)
        roots = sorted({addon_root for addon_root, _series in modules(root)} or {'.'},
                       key=lambda item: (item != '.', item))
        # The series guard of the configuration about to be written, before any question (S11).
        guarded({'ODOO_VERSION': series, 'PROJECT_ROOT': str(root), 'WORKSPACE_ROOT': str(directory),
                 'ADDON_ROOTS': '\n'.join(str((root / item).resolve()) for item in roots)})
        community, enterprise, origin, machine_lines, machine_actions, environments = choose_sources(
            root, series, options, machine, questions)
        if '--name' in options:
            name = options['--name']
            if not NAME.fullmatch(name):
                raise Refused(f'Invalid --name {name}: use {NAME_RULE}.')
        else:
            name = re.sub(r'[^a-z0-9]+', '_', root.name.lower()).strip('_')
            if not NAME.fullmatch(name):
                raise Refused(f'Cannot derive database prefixes from the checkout name {root.name}: pass --name '
                              f'<name> ({NAME_RULE}).')
        lines += [f'series: {series} ({series_origin})', f'community: {community} ({origin[0]})',
                  f'enterprise: {enterprise or "none"} ({origin[1]})', f'workspace: {directory} (new)', *machine_lines]
        actions += machine_actions
        layout = f'{LAYOUT}/' if directory == root else ''
        tooling = {'environment': f'{environments}/{name}' if environments else f'{layout}venv',
                   'config': f'{layout}config/odoo.conf', 'env_file': f'{layout}config/.env',
                   'compose': f'{layout}config/compose.yml', 'requirements': f'{layout}config/requirements',
                   'addons_paths': roots, 'db_service': 'db', 'dev_prefix': f'{name}_dev_',
                   'test_prefix': f'{name}_test_', 'logs': f'{layout}logs', 'data_dir': f'{layout}data'}
        text = (WORKSPACE_HEADER + f'workspace_version = 1\nodoo_version = {migrate.toml_string(series)}\n\n'
                + migrate.toml_table('tooling', tooling))
        sources = {'community': str(community), **({'enterprise': str(enterprise)} if enterprise else {})}
        document = {'workspace_version': 1, 'odoo_version': series,
                    'tooling': {**tooling, **sources, 'version': series,
                                'python_version': config.versions().capability(series, 'python_default')}}
        try:
            values = config.assignments(document, root, directory, workspace, '')
        except config.InvalidConfig as exc:
            raise Refused(str(exc)) from exc
        lines.append(f'create {workspace} (mode 0600):')
        lines += [f'  {line}' if line else '' for line in text.splitlines()]
        actions.append(('create', workspace, text.encode(), 0o600))
        new = True
        if directory == root and kind == 'main':
            exclude, missing = git_exclude(root)
            if missing:
                lines.append(f'exclude {" and ".join(missing)} in {exclude} (this clone only; .gitignore unchanged)')
                addition = ''.join(f'{pattern}\n' for pattern in missing).encode()
                if exclude.exists():
                    original = exclude.read_bytes()
                    actions.append(('extend', exclude, original,
                                    original + (b'\n' if original and not original.endswith(b'\n') else b'') + addition))
                else:
                    actions += [*directories(exclude.parent, planned), ('create', exclude, addition, 0o644)]
    guarded(values)
    plan = {'root': root, 'workspace': workspace, 'values': values, 'lines': lines, 'actions': actions,
            'after': [], 'created': set(), 'new': new}
    gaps(plan, directory, planned)
    return plan


# -- another series in an existing workspace file (v0.15.0 S5) ------------------------------------

def section_target(root: Path, workspace: Path, options: dict) -> tuple[str, str, dict] | None:
    """(series, where it came from, the checked workspace document) when root is a checkout of a series
    the workspace file has no section for, else None: every other case, an invalid configuration
    included, is the existing configuration's (make_plan refuses it as before). The series is the
    checkout file's odoo_version, else the one its module manifests declare (config.detected_series,
    the series_exceptions of every section and the --exception modules left out), also for a version 1
    file; manifests of several series are left to the existing refusal."""
    if (root / config.PROFILE_NAME).is_file():
        return None
    try:
        document = config.checked_workspace(workspace)
        declared = config.checkout_file(root).get('odoo_version', config.MISSING)
        if declared is config.MISSING:
            series = config.detected_series(root, document, workspace, options.get('--exception', ()))
            origin = 'from the module manifests'
        elif isinstance(declared, str) and declared in config.versions().CAPABILITIES:
            series, origin = declared, f'from {root / config.CHECKOUT_NAME}'
        else:
            return None
    except config.InvalidConfig:
        return None
    configured = (config.declared_series(document, workspace) if document['workspace_version'] == 2
                  else [document['odoo_version']])
    if series is None or series in configured:
        return None
    return series, origin, document


def as_version2(document: dict) -> dict:
    """A copy of a checked document read as workspace_version 2 (a version 1 file's [series] tables,
    which it does not read, left out): what its series would get once converted."""
    view = copy.deepcopy(document)
    if view['workspace_version'] == 1:
        view.pop('series', None)
    view['workspace_version'] = 2
    return view


def series_folder(document: dict, workspace: Path, series: str, options: dict) -> tuple[Path, Path | None, str]:
    """(the default folder of the series' files, relative as written or absolute; the folder to adopt,
    resolved, or None; where it came from). The default is <folder of [tooling].config>/<x.y>; a
    folder next to it named for the series (<x.y>, odoo-<major>, odoo<major>, odoo-<x.y>, odoo<x.y>,
    <major>) that holds an odoo.conf or a compose file is adopted, or the --config-dir folder."""
    view, base = as_version2(document), workspace.parent
    current = config.series_tooling(view, workspace, document['odoo_version']).get('config')
    placed = config.series_tooling(view, workspace, series).get('config')
    if not isinstance(current, str) or not current or not isinstance(placed, str) or not placed:
        raise Refused('Invalid tooling path: config.')
    parent = Path(current).parent if placed == current else Path(placed).parent.parent
    if str(parent) == '.':
        parent = Path('config')
    if '--config-dir' in options:
        return parent / series, Path(options['--config-dir']).resolve(), 'from --config-dir'
    major = series.split('.')[0]
    found = []
    for name in (series, f'odoo-{major}', f'odoo{major}', f'odoo-{series}', f'odoo{series}', major):
        folder = (base / parent / name).resolve()
        holds = folder.is_dir() and any((folder / item).is_file() for item in ('odoo.conf', *COMPOSE_NAMES))
        if holds and folder not in found:
            found.append(folder)
    if len(found) > 1:
        raise Refused(f'Several folders hold Odoo {series} files: {", ".join(map(str, found))}; pass --config-dir '
                      '<dir>.')
    return parent / series, (found[0] if found else None), 'found'


def relative(path: Path, base: Path) -> str:
    """A path for the workspace file: relative to its directory when below it, else absolute."""
    return path.relative_to(base).as_posix() if path.is_relative_to(base) else str(path)


def series_section(document, workspace, series, exceptions, sources, environments, options):
    """The [series."<series>"] values (in config.SERIES_KEYS order) and the adoption plan lines: only
    what [tooling] would otherwise share with the default series. The per-series files go to the
    series folder (series_folder), the environment next to [tooling]'s (<environment>-<x.y>, or
    <environments>/<name><major> with the machine file's environments), logs and data_dir to
    <logs>/<x.y> and <data_dir>/<x.y>, the prefixes to <name><major>_dev_ and _test_ (<name> from the
    default series' dev_prefix, its own major left out). A source that [tooling] sets is overridden
    with this series' (sources: community and enterprise or None)."""
    view, base, default = as_version2(document), workspace.parent, document['odoo_version']
    old = config.series_tooling(view, workspace, default)
    new = config.series_tooling(view, workspace, series)

    def varies(key):
        return key in new and new.get(key) != old.get(key)
    section, lines = {}, []
    community, enterprise = sources
    if 'community' in old and not varies('community'):
        section['community'] = str(community)
    if 'enterprise' in old and not varies('enterprise'):
        value = str(enterprise) if enterprise is not None else False
        if value != old['enterprise']:
            section['enterprise'] = value
    dev = old.get('dev_prefix')
    if not isinstance(dev, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]+_dev_', dev):
        raise Refused('Unsafe tooling database prefixes.')
    name, own = dev[:-len('_dev_')], default.split('.')[0]
    if name.endswith(own) and name[:-len(own)].rstrip('_'):
        name = name[:-len(own)].rstrip('_')
    name += series.split('.')[0]
    environment = old.get('environment')
    if environment is None and isinstance(view.get('environments'), dict):
        environment = view['environments'].get('default', {}).get('path') if isinstance(
            view['environments'].get('default'), dict) else None
        varying = config.placed(environment, series) != config.placed(environment, default)
    else:
        varying = varies('environment')
    if not varying and environments:
        section['environment'] = f'{environments}/{name}'
    elif not varying and isinstance(environment, str) and environment:
        section['environment'] = (Path(environment).parent / f'{Path(environment).name}-{series}').as_posix()
    folder, adopted, origin = series_folder(document, workspace, series, options)
    files = {'config': 'odoo.conf', 'compose': 'compose.yml', 'env_file': '.env', 'requirements': 'requirements'}
    if adopted is not None:
        compose = next((item for item in COMPOSE_NAMES if (adopted / item).is_file()), 'compose.yml')
        files['compose'] = compose
        held = [(key, item) for key, item in files.items()
                if ((adopted / item).is_dir() if key == 'requirements' else (adopted / item).is_file())]
        lines.append(f'adopt {adopted} ({origin}): '
                     + (', '.join(item + ('/' if key == 'requirements' else '') for key, item in held) or 'no files yet'))
        for key, item in files.items():
            if key in dict(held) or not varies(key):
                section[key] = relative(adopted / item, base)
    else:
        for key, item in files.items():
            if not varies(key):
                written = old.get(key)
                if isinstance(written, str) and written and key != 'requirements':
                    item = Path(written).name
                section[key] = (folder / item).as_posix()
    # A key that only repeats what the series already gets from [tooling] is left out.
    for key in list(section):
        if key in files and varies(key) and (base / section[key]).resolve() == (base / new[key]).resolve():
            del section[key]
    section['dev_prefix'], section['test_prefix'] = f'{name}_dev_', f'{name}_test_'
    database, test = old.get('test_database'), old.get('test_prefix')
    if (isinstance(database, str) and isinstance(test, str) and database.startswith(test)
            and not varies('test_database')):
        section['test_database'] = f'{name}_test_' + database[len(test):]
    for key, directory in (('logs', 'logs'), ('data_dir', 'data')):
        if not varies(key):
            written = old.get(key)
            section[key] = (f'{written.rstrip("/")}/{series}' if isinstance(written, str) and written
                            else f'{directory}/{series}')
    if exceptions:
        section['series_exceptions'] = exceptions
    return {key: section[key] for key in config.SERIES_KEYS if key in section}, lines


def effective(document: dict, workspace: Path, series: str) -> list:
    """What a checked document gives a checkout of series, for every environment it may select: the
    derived [tooling] and the environment name, or the refusal (series_exceptions [] left out, which
    version 2 adds)."""
    environments = document.get('environments')
    found = []
    for selected in [None, *(environments if isinstance(environments, dict) else ())]:
        try:
            derived, name = config.series_document(copy.deepcopy(document), workspace, selected, series)
        except config.InvalidConfig as exc:
            found.append(str(exc))
            continue
        tooling = derived['tooling']
        if tooling.get('series_exceptions') == []:
            del tooling['series_exceptions']
        found.append((tooling, name))
    return found


def extended_workspace(workspace: Path, document: dict, series: str, section: dict):
    """(the new bytes, the original ones, the plan lines, the checked new document) of the workspace
    file with the section appended and, for version 1, its workspace_version line changed to 2. The
    result must parse to the same document with only those changes, pass the workspace checks, and
    give every series it configured the same configuration; otherwise it is refused."""
    table = f'[series.{json.dumps(series)}]'
    try:
        raw = workspace.read_bytes()
        text = raw.decode('utf-8')
    except (OSError, UnicodeError) as exc:
        raise Refused(f'Cannot read {workspace}.') from exc
    lines = []
    if document['workspace_version'] == 1:
        found = list(VERSION_LINE.finditer(text))
        if len(found) != 1:
            raise Refused(f'Cannot convert {workspace} to workspace_version 2: no single line workspace_version = 1; '
                          f'set workspace_version = 2 yourself, then run {config.program_name()} setup again.')
        text = text[:found[0].start(2)] + '2' + text[found[0].end(2):]
        lines.append(f'change workspace_version = 1 to workspace_version = 2 in {workspace} (that line only)')
    addition = SECTION_COMMENT.format(series=series) + migrate.toml_table(f'series.{json.dumps(series)}', section)
    separator = '' if not text.strip() else '\n' if text.endswith('\n') else '\n\n'
    lines += [f'add {table} to {workspace}:', *(f'  {line}' if line else '' for line in addition.splitlines())]
    expected = copy.deepcopy(document)
    expected['workspace_version'] = 2
    try:
        parsed = tomllib.loads(text + separator + addition)
        expected.setdefault('series', {})[series] = section
    except (tomllib.TOMLDecodeError, TypeError, AttributeError):
        parsed = None
    if parsed != expected:
        raise Refused(f'Cannot add {table} to {workspace}: the result is not the same file with that section added; '
                      'edit the file yourself.')
    try:
        checked = config.checked_document(copy.deepcopy(parsed), workspace)
    except config.InvalidConfig as exc:
        raise Refused(f'Cannot add {table} to {workspace}: as workspace_version 2 it would be refused ({exc}); edit '
                      'the file yourself.') from exc
    configured = (config.declared_series(document, workspace) if document['workspace_version'] == 2
                  else [document['odoo_version']])
    for other in configured:
        if effective(document, workspace, other) != effective(checked, workspace, other):
            raise Refused(f'Cannot add {table} to {workspace}: the change would alter the configuration of Odoo '
                          f'{other} ({{series}} or a [series] table that version 1 does not read); edit the file '
                          'yourself.')
    return (text + separator + addition).encode(), raw, lines, checked


def configured_port(conf: Path) -> int | None:
    """The port an existing odoo.conf connects to (db_port, PostgreSQL's default without one), None when
    it cannot be read. Only db_port is read, never the rest of odoo.conf."""
    reader = sibling('odoo_addons_path')
    try:
        return int(reader.read_option(conf, 'db_port') or POSTGRES_PORT)
    except (ValueError, reader.ConfError):
        return None


def series_ports(document: dict, workspace: Path) -> set[int]:
    """The ports the series a workspace configures already use (their odoo.conf and compose files), which
    a new series' compose file must not publish."""
    taken = set()
    configured = (config.declared_series(document, workspace) if document['workspace_version'] == 2
                  else [document['odoo_version']])
    for series in configured:
        tooling = config.series_tooling(document, workspace, series)
        for key, read in (('config', configured_port), ('compose', published_port)):
            value = tooling.get(key)
            if isinstance(value, str) and value and '\x00' not in value and (workspace.parent / value).is_file():
                port = read(workspace.parent / value)
                if port is not None:
                    taken.add(port)
    return taken


def series_plan(root, kind, options, questions, workspace, machine, target, lines) -> dict:
    """make_plan for a checkout of a series the workspace file has no section for (section_target)."""
    series, origin, document = target
    lines.append(f'workspace: {workspace} (existing)')
    for option in options:
        if option not in SERIES_PLAN_OPTIONS:
            raise Refused(f'{option}: {root} is already configured by {workspace}; setup only fills what is '
                          'missing.')
    exceptions = list(dict.fromkeys(options.get('--exception', [])))
    for module in exceptions:
        if not config.MODULE_NAME.fullmatch(module):
            raise Refused(f'Invalid --exception {module}: use a module name.')
    # The series guard of the section about to be written, before any question.
    addons = document['tooling'].get('addons_paths')
    if isinstance(addons, list) and addons and all(isinstance(path, str) and path and '\x00' not in path
                                                   and '\n' not in path for path in addons):
        mismatch = config.series_mismatch({'ODOO_VERSION': series, 'SERIES_EXCEPTIONS': '\n'.join(exceptions),
                                           'ADDON_ROOTS': '\n'.join(str((root / path).resolve()) for path in addons)})
        if mismatch is not None:
            raise Refused(f'The module {mismatch["module"]} declares Odoo {mismatch["series"]} (version '
                          f'{mismatch["version"]} in {mismatch["manifest"]}), but {root} is an Odoo {series} checkout: '
                          f'pass --exception {mismatch["module"]} to list it in series_exceptions under '
                          f'[series.{json.dumps(series)}], or set its version to {series}.x.y.z if it is an Odoo '
                          f'{series} module.')
    community, enterprise, source_origin, machine_lines, machine_actions, environments = choose_sources(
        root, series, options, machine, questions)
    lines += [f'series: {series} ({origin}; {workspace} has no [series.{json.dumps(series)}] section)',
              f'community: {community} ({source_origin[0]})', f'enterprise: {enterprise or "none"} ({source_origin[1]})',
              *machine_lines]
    section, adoption = series_section(document, workspace, series, exceptions, (community, enterprise),
                                       environments, options)
    new, raw, workspace_lines, checked = extended_workspace(workspace, document, series, section)
    lines += [*workspace_lines, *adoption]
    try:
        planned, base, _workspace, name, _origins, _refusal = config.layered_configuration(root, planned=checked)
        # A new machine entry is not written yet: its source, as the existing flow does.
        if 'community' not in planned['tooling']:
            planned['tooling']['community'] = str(community)
        if enterprise is not None and 'enterprise' not in planned['tooling']:
            planned['tooling']['enterprise'] = str(enterprise)
        values = config.assignments(planned, root, base, workspace, name)
    except config.InvalidConfig as exc:
        raise Refused(str(exc)) from exc
    guarded(values)
    plan = {'root': root, 'workspace': workspace, 'values': values, 'lines': lines,
            'actions': [*machine_actions, ('extend', workspace, raw, new)], 'after': [], 'created': set(),
            'new': False, 'taken': series_ports(document, workspace)}
    gaps(plan, base, set())
    return plan


def guarded(values: dict):
    """Refuse a configuration whose modules declare another Odoo series (config.series_mismatch, S11)."""
    mismatch = config.series_mismatch(values)
    if mismatch is not None:
        raise Refused(config.series_refusal(mismatch, values))


def published_port(compose: Path) -> int | None:
    """The one host port the compose file publishes to 5432 (PUBLISHED_PORT), or None: none, several
    different ones, or an unreadable file."""
    try:
        lines = compose.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError):
        return None
    ports = {int(match.group(2)) for line in lines if (match := PUBLISHED_PORT.fullmatch(line))}
    ports = {port for port in ports if 1 <= port <= 65535}
    return ports.pop() if len(ports) == 1 else None


def gaps(plan: dict, directory: Path, planned: set):
    """Plan every missing file, directory, lock and environment of the configuration; keep the rest."""
    values, lines, actions, root = plan['values'], plan['lines'], plan['actions'], plan['root']

    def create(path: Path, text: str, mode: int, line: str, key: str):
        if path.exists():
            lines.append(f'kept {path}')
            return
        actions.extend(directories(path.parent, planned))
        actions.append(('create', path, text.encode(), mode))
        lines.append(line)
        plan['created'].add(key)

    conf, compose, env_file = (Path(values[key]) for key in ('ODOO_CONFIG', 'COMPOSE_FILE', 'ENV_FILE'))
    # One port for both files: a new one takes the port of the one that is kept (odoo.conf's db_port,
    # PostgreSQL's default without one; the port the compose file publishes to 5432); two kept files
    # that disagree are reported; only without either is a free port chosen.
    conf_port = compose_port = None
    if conf.exists():
        conf_port = configured_port(conf)
    if compose.exists():
        compose_port = published_port(compose)
    port, unread = None, False
    # A new series' compose file never publishes a port another series of the workspace uses.
    taken = plan.get('taken', set())
    if conf.exists() and not compose.exists():
        port = conf_port if conf_port is not None else free_port(taken)
    elif compose.exists() and not conf.exists():
        port, unread = (compose_port, False) if compose_port is not None else (free_port(taken), True)
    elif not conf.exists():
        port = free_port(taken)
    series = values['ODOO_VERSION']
    postgres = config.versions().capability(series, 'postgres_default')
    name = values['DEV_PREFIX'][:-len('_dev_')].lower().replace('_', '-')
    compose_name = f'oasis-{name}-{hashlib.sha256(str(directory).encode()).hexdigest()[:6]}'
    service = values['DB_SERVICE']
    create(conf, CONF.format(env_file=env_file, port=port), 0o600,
           f'create {conf} (mode 0600): path-free; db_port {port}; db_user and db_password empty', 'conf')
    if unread:
        lines.append(f'check {conf}: no port published to 5432 found in {compose}; set db_port {port} to the port '
                     'it publishes')
    create(compose, COMPOSE.format(name=compose_name, service=service, postgres=postgres, port=port), 0o644,
           f'create {compose}: PostgreSQL {postgres} (postgres:{postgres}) as service {service} on '
           f'127.0.0.1:{port}, compose project {compose_name}', 'compose')
    if 'conf' not in plan['created'] and 'compose' not in plan['created'] and None not in (conf_port, compose_port) \
            and conf_port != compose_port:
        lines.append(f'mismatch: {conf} connects to port {conf_port} but {compose} publishes {compose_port}: make '
                     'them the same')
    create(env_file, ENV_FILE, 0o600, f'create {env_file} (mode 0600): ODOO_DB_USER and ODOO_DB_PASSWORD, empty',
           'env')
    requirements = Path(values['REQUIREMENTS_DIR'])
    source = Path(values['ODOO_SOURCE'])
    if not (requirements / 'runtime.in').exists() and not (source / 'requirements.txt').is_file():
        raise Refused(f'Cannot write {requirements / "runtime.in"}: {source / "requirements.txt"} does not exist.')
    create(requirements / 'runtime.in', RUNTIME_IN.format(source=source), 0o644,
           f'create {requirements / "runtime.in"}: -r {source}/requirements.txt', 'inputs')
    create(requirements / 'dev.in', DEV_IN, 0o644,
           f'create {requirements / "dev.in"}: -c runtime.txt, -r runtime.in', 'inputs')
    for key in ('LOGS_DIR', 'DATA_DIR'):
        if values[key]:
            path = Path(values[key])
            if path.exists():
                lines.append(f'kept {path}/')
            else:
                actions.extend(directories(path, planned))
                lines.append(f'create {path}/')
    python = values['PYTHON_VERSION']
    usable = True
    if 'inputs' not in plan['created'] and locks.current(requirements, root):
        lines.append(f'kept the locks in {requirements}: current')
    elif 'inputs' not in plan['created'] and locks.state(requirements, root) == 'edited':
        lines.append(f'kept the locks in {requirements}: a lock was changed by hand; move it away or fingerprint '
                     f'it again (see {config.program_name()} bootstrap)')
        usable = False
    else:
        lines.append(f'compile {requirements}/runtime.txt, dev.txt and lock.sha256 with Python {python} '
                     '(uv pip compile)')
        plan['after'].append(('compile', requirements, python))
    environment = Path(values['PROJECT_ENVIRONMENT'])
    if (environment / 'pyvenv.cfg').is_file():
        lines.append(f'kept the environment {environment}')
    elif not usable:
        lines.append(f'not created: the environment {environment}, until the locks match lock.sha256')
    else:
        lines.append(f'create the environment {environment} with Python {python} (uv venv) and sync dev.txt '
                     '(uv pip sync)')
        plan['after'].append(('environment', environment, python, requirements / 'dev.txt'))


# -- apply -----------------------------------------------------------------------------------------

class Changes:
    """The file changes made so far, undone in reverse order by rollback. Files are created
    exclusively (never overwritten); an existing file is only extended, when it still has the
    content the plan read."""

    def __init__(self):
        self.undo = []

    def apply(self, action):
        kind, path = action[0], action[1]
        if kind == 'mkdir':
            os.mkdir(path, DIRECTORY_MODE)
            self.undo.append(('rmdir', path))
        elif kind == 'create':
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, action[3])
            self.undo.append(('remove', path))
            with os.fdopen(descriptor, 'wb') as stream:
                os.fchmod(stream.fileno(), action[3])
                stream.write(action[2])
        else:
            original, data = action[2], action[3]
            if path.read_bytes() != original:
                raise OSError(0, f'{path} changed since the plan')
            migrate.write_in_place(path, data, lambda: self.undo.append(('restore', path, original)))

    def rollback(self) -> list[str]:
        failed = []
        for step in reversed(self.undo):
            try:
                if step[0] == 'rmdir':
                    os.rmdir(step[1])
                elif step[0] == 'remove':
                    os.unlink(step[1])
                else:
                    migrate.write_in_place(step[1], step[2])
            except OSError as exc:
                failed.append(f'{step[1]}: {exc.strerror or exc}')
        self.undo = []
        return failed


def undone(message: str, failed: list[str]) -> int:
    if failed:
        print(f'ERROR: {message}; these changes could not be undone:', file=sys.stderr)
    else:
        print(f'ERROR: {message}; every change was undone.', file=sys.stderr)
    for line in failed:
        print(f'  {line}', file=sys.stderr)
    return 1


def apply_plan(plan: dict) -> int:
    program, root = config.program_name(), plan['root']
    changes = Changes()
    try:
        for action in plan['actions']:
            changes.apply(action)
        config.load(root)
    except OSError as exc:
        return undone(f'Could not set up: {exc.strerror or exc}', changes.rollback())
    except config.InvalidConfig as exc:
        return undone(f'Verification failed ({exc})', changes.rollback())
    except BaseException:
        changes.rollback()
        raise
    print(f'verified: {root} loads its configuration from {plan["workspace"]}', flush=True)
    rerun = f'{program} setup --apply'
    for step in plan['after']:
        if step[0] == 'compile':
            if locks.compile_locks(step[1], step[2], rerun):
                return 2
            print(f'compiled {step[1]}/runtime.txt, dev.txt and lock.sha256', flush=True)
            continue
        _kind, environment, python, lock = step
        environment.parent.mkdir(parents=True, exist_ok=True)
        for command in (['uv', 'venv', '--python', python, str(environment)],
                        ['uv', 'pip', 'sync', '--python', str(environment / 'bin/python'), str(lock)]):
            try:
                status = subprocess.run(command).returncode
            except OSError:
                status = 127
            if status == 0:
                continue
            if command[1] == 'pip':
                # The environment exists now: a second setup run keeps it unsynced, bootstrap syncs it.
                print(f'ERROR: uv pip sync failed (exit {status}); the files above and the environment '
                      f'{environment} are kept: fix it, then run {program} --project {root} bootstrap --apply '
                      'to sync it.', file=sys.stderr)
            else:
                print(f'ERROR: uv venv failed (exit {status}); the files above are kept: fix it, then run '
                      f'{rerun} again.', file=sys.stderr)
            return 2
        print(f'created the environment {environment}', flush=True)
    values, created = plan['values'], plan['created']
    env_file, conf = values['ENV_FILE'], values['ODOO_CONFIG']
    steps = []
    if 'env' in created and 'conf' in created:
        steps.append(f'fill in ODOO_DB_USER and ODOO_DB_PASSWORD in {env_file}, and the same values as db_user '
                     f'and db_password in {conf}')
    elif 'env' in created:
        steps.append(f'fill in ODOO_DB_USER and ODOO_DB_PASSWORD in {env_file}')
    elif 'conf' in created:
        steps.append(f'fill in db_user and db_password in {conf} with ODOO_DB_USER and ODOO_DB_PASSWORD of {env_file}')
    if any(step[0] == 'compile' for step in plan['after']) and not any(step[0] == 'environment' for step in plan['after']):
        steps.append(f'{program} --project {root} bootstrap --apply')
    steps += [f'docker compose --env-file {env_file} -f {values["COMPOSE_FILE"]} up -d --wait',
              f'{program} --project {root} doctor']
    # init-dev-database needs the role accounts of [development] (tools/dev_users.py). A workspace
    # file that cannot be read now gets no edit advice: doctor reports the configuration.
    workspace_file = Path(values['WORKSPACE_ROOT']) / config.WORKSPACE_NAME
    try:
        development = isinstance(config.read_toml(workspace_file).get('development'), dict)
    except config.InvalidConfig:
        development = None
    if development is False:
        steps.append(f'add a [development] table with administrator_login to {workspace_file} '
                     '(docs/dev-database.md)')
    steps.append(f'{program} --project {root} init-dev-database <module> {values["DEV_PREFIX"]}manual')
    print('next steps:')
    for number, step in enumerate(steps, 1):
        print(f'  {number}. {step}')
    return 0


def main(arguments: list[str]) -> int:
    if arguments in (['--help'], ['-h']):
        print(usage() + '\n' + HELP, end='')
        return 0
    options = parse_arguments(arguments)
    if options is None:
        print(usage(), file=sys.stderr)
        return 2
    for option in ('--workspace', '--config-dir'):
        if option in options and (not os.path.isabs(options[option]) or not os.path.isdir(options[option])):
            print(f'ERROR: {option} requires an absolute existing directory.', file=sys.stderr)
            return 2
    root = config.selected_root()
    if root is None:
        print(f'ERROR: {config.PROJECT_ROOT_REQUIRED}', file=sys.stderr)
        return 2
    try:
        plan = make_plan(root, options, Questions())
    except Refused as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    print('\n'.join(plan['lines']), flush=True)
    if not plan['actions'] and not plan['after']:
        print(f'nothing to set up: run {config.program_name()} --project {root} doctor')
        return 0
    if '--apply' not in options:
        print(DRY_RUN)
        return 0
    return apply_plan(plan)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
