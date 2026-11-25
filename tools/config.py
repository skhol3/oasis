#!/usr/bin/env python3
"""Parse project-owned tooling paths into literal shell assignments, not shell code.

The caller must supply the project (checkout) root; this module never discovers it from its
own (global installation) location. A checkout reads the nearest `oasis-workspace.toml` at or
above it (a linked worktree without one, the file its main checkout reads, found through git), with
its own optional `oasis-checkout.toml`, over the optional machine file
(`$XDG_CONFIG_HOME/oasis/config.toml`, else `~/.config/oasis/config.toml`), whose per-series
source paths are defaults the workspace overrides. A checkout that still has the legacy
profile `.odoo19-agent.toml` is refused: only tools/migrate.py reads that file, to convert it.
So is a checkout whose module manifests declare another Odoo series than its odoo_version (load,
series_mismatch). Path declarations do not grant access consent.

workspace_version 2 (v0.15.0 S3, S4) holds several series: a checkout's series is its
oasis-checkout.toml odoo_version, else the series of its module manifests (checkout_series), else
the workspace odoo_version; its [series."<x.y>"] section overrides [tooling], whose paths may use
`{series}` (series_tooling). Every assignment then follows that series, so the tools do too.
"""
import ast
import functools
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tomllib


def variable(name: str) -> str:
    """OASIS_<name>, else the legacy ODOO19_<name> when that is unset or empty, else ''.

    For the variables a user, a project wrapper or a test may set (PROJECT_ROOT, ENTRYPOINT,
    TOOLS_DIR, COMPOSE_LOCK_TIMEOUT); tools/oasis_env.sh oasis_variable in the shell tools.
    """
    return os.environ.get(f'OASIS_{name}') or os.environ.get(f'ODOO19_{name}') or ''


PROJECT_ROOT_REQUIRED = 'OASIS_PROJECT_ROOT must name an absolute existing project directory.'


def selected_root() -> Path | None:
    """The project root the entry point or a wrapper selected, resolved; None when the variable
    does not name an absolute existing directory (report PROJECT_ROOT_REQUIRED)."""
    selected = variable('PROJECT_ROOT')
    if not selected or not Path(selected).is_absolute() or not Path(selected).is_dir():
        return None
    return Path(selected).resolve()


def program_name() -> str:
    """The program a help or message tells the user to run (`oasis gc`): the invoked entry
    point, `odoo19` through its alias, else `oasis` (also through a project wrapper)."""
    return 'odoo19' if Path(variable('ENTRYPOINT')).name == 'odoo19' else 'oasis'


def usage_name() -> str:
    """What a usage line names: the entry point that ran the tool, else `oasis`."""
    return variable('ENTRYPOINT') or 'oasis'


@functools.cache
def versions():
    """tools/odoo_versions.py, loaded from its file when first needed: callers import this file
    by location (python3 -I does not put the script directory on sys.path), and the entry
    point's workspace finder must not depend on it."""
    spec = importlib.util.spec_from_file_location('oasis_odoo_versions',
                                                  Path(__file__).with_name('odoo_versions.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

PATHS = {
    'community': 'ODOO_SOURCE', 'enterprise': 'ENTERPRISE_SOURCE',
    'environment': 'PROJECT_ENVIRONMENT', 'config': 'ODOO_CONFIG',
    'env_file': 'ENV_FILE', 'compose': 'COMPOSE_FILE',
    'requirements': 'REQUIREMENTS_DIR',
}


# The legacy per-checkout profile: never read here, only refused (legacy_profile_refusal).
PROFILE_NAME = '.odoo19-agent.toml'
WORKSPACE_NAME = 'oasis-workspace.toml'
CHECKOUT_NAME = 'oasis-checkout.toml'
WORKSPACE_VERSION = 1
# The workspace_version values read: 1 (one series) and 2 (series sections, v0.15.0 S3).
WORKSPACE_VERSIONS = (1, 2)
# What a workspace_version 2 [series."<x.y>"] section may set over [tooling] (S3), and the modules the
# series guard and the series detection leave out for that series (series_exceptions, S4).
SERIES_KEYS = ('community', 'enterprise', 'environment', 'config', 'env_file', 'compose', 'requirements',
               'db_service', 'dev_prefix', 'test_prefix', 'test_database', 'logs', 'data_dir', 'series_exceptions')
# The path values in which workspace_version 2 replaces SERIES_PLACEHOLDER with the checkout's series.
SERIES_PLACEHOLDER = '{series}'
SERIES_PATHS = (*PATHS, 'logs', 'data_dir', 'lint_rcfile')
MODULE_NAME = re.compile(r'[A-Za-z0-9_]+')
DEFAULT_ENVIRONMENT = 'default'
MISSING = object()


class InvalidConfig(ValueError):
    pass


class MissingSeries(InvalidConfig):
    """A checkout of a series its workspace file has no section for: oasis setup adds it."""


def legacy_profile_refusal(profile: Path, program: str) -> str:
    """Why a checkout with the legacy profile is refused, and the fix (`oasis migrate`)."""
    return (f'{profile} is the old profile format, no longer read: run {program} migrate --plan to see '
            f'its conversion to {WORKSPACE_NAME}, then {program} migrate --apply.')


def missing_configuration(root: Path) -> str:
    """The error of a checkout without a workspace file at or above it."""
    return f'Missing tooling configuration: no {WORKSPACE_NAME} at or above {root}.'


SLUG = re.compile(r'[a-z0-9][a-z0-9_]{0,19}')
GIT_TIMEOUT_SECONDS = 5


class GitFailed(Exception):
    """git could not report the checkout; the message is the reason."""


def git_checkout(root: Path) -> tuple[str, Path, Path]:
    """Return the checkout kind with its top-level and main directories, read-only.

    The kind is `main` or `linked` (git dir differs from the common dir). Raises GitFailed
    when git cannot run, times out, exits non-zero (for example outside a work tree) or
    prints something unexpected; checkout_identity decides what that means.
    """
    env = {key: value for key, value in os.environ.items()
           if key not in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR')}
    try:
        result = subprocess.run(
            ['git', '-C', str(root), 'rev-parse', '--path-format=absolute',
             '--git-dir', '--git-common-dir', '--show-toplevel'],
            capture_output=True, text=True, env=env, timeout=GIT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise GitFailed(f'timed out after {GIT_TIMEOUT_SECONDS} s') from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitFailed(f'cannot run git: {getattr(exc, "strerror", None) or exc}') from exc
    lines = result.stdout.splitlines()
    if result.returncode != 0:
        errors = [line.strip() for line in result.stderr.splitlines() if line.strip()]
        raise GitFailed(f'exit {result.returncode}' + (f': {errors[-1][:200]}' if errors else ''))
    if len(lines) != 3 or not all(lines):
        raise GitFailed('unexpected output')
    git_dir, common_dir, top = (Path(line).resolve() for line in lines)
    if git_dir == common_dir:
        return 'main', top, top
    return 'linked', top, common_dir.parent


def dot_git(root: Path) -> Path | None:
    """The first `.git` entry at or above root, searched like git does, or None.

    Ancestors listed in GIT_CEILING_DIRECTORIES are not entered, as git does not enter them.
    """
    ceilings = {Path(entry).resolve() for entry in os.environ.get('GIT_CEILING_DIRECTORIES', '').split(':')
                if entry and os.path.isabs(entry)}
    for directory in (root, *root.parents):
        if directory != root and directory in ceilings:
            return None
        candidate = directory / '.git'
        if os.path.lexists(candidate):
            return candidate
    return None


def checkout_identity(root: Path, override: str | None) -> tuple[str, Path | None, Path | None]:
    """git_checkout, failing closed when git fails inside a repository.

    Without any `.git` at or above root the project is outside git (kind `none`). A `.git`
    file is a linked worktree's gitfile: its slug and namespace guard must not be lost, so
    only a checkout slug (oasis-checkout.toml) lets it continue (kind `linked`, main checkout
    unknown). A `.git` directory (or anything else) stops with the reason.
    """
    try:
        return git_checkout(root)
    except GitFailed as exc:
        entry = dot_git(root)
        if entry is None:
            return 'none', None, None
        if entry.is_file():
            if override is None:
                raise InvalidConfig('Cannot determine the checkout identity: git failed in a linked '
                                    'worktree; check git or set [tooling].checkout_slug.') from exc
            return 'linked', None, None
        raise InvalidConfig(f'Cannot determine the checkout identity: git failed ({exc}).') from exc


def derived_slug(top: Path, main: Path) -> str:
    """Slug of a linked worktree from its directory name, without the main directory prefix."""
    name = top.name
    if (main.name and name.startswith(main.name) and len(name) > len(main.name)
            and name[len(main.name)] in '-_.'):
        name = name[len(main.name):].lstrip('-_.')
    slug = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
    if not SLUG.fullmatch(slug):
        raise InvalidConfig('Cannot derive a checkout slug from the worktree directory name; '
                            'set [tooling].checkout_slug.')
    return slug


def find_workspace(root: Path) -> Path | None:
    """The nearest workspace file at or above root, or None.

    Searched like git searches `.git`, up to the filesystem root.
    """
    for directory in (root, *root.parents):
        candidate = directory / WORKSPACE_NAME
        if candidate.is_file():
            return candidate
    return None


def workspace_file(root: Path) -> Path | None:
    """The workspace file root reads: the nearest at or above it (find_workspace), else, for a linked
    worktree, the one its main checkout reads, found through git (`--git-common-dir`); None without
    either. Only a linked worktree with nothing above it asks git, so other layouts are unchanged.
    """
    found = find_workspace(root)
    if found is not None:
        return found
    try:
        kind, _top, main = git_checkout(root)
    except GitFailed:
        return None
    return find_workspace(main) if kind == 'linked' else None


def trusted(path: Path, kind: str = 'workspace file') -> Path:
    """path, refused unless it and its directory are owned by the current user or root and are
    not group- or other-writable: a file found above the checkout must not be one someone else
    could write. A symlinked file is checked at its target too. kind names the file in the
    refusal (the machine file says `machine file`)."""
    targets = [path.resolve(), path.resolve().parent]
    if path.parent.resolve() not in targets:
        targets.append(path.parent.resolve())
    for target in targets:
        try:
            info = target.stat()
        except OSError as exc:
            raise InvalidConfig(f'Refusing untrusted {kind} {path}: cannot inspect {target}.') from exc
        if info.st_uid not in (os.getuid(), 0):
            raise InvalidConfig(f'Refusing untrusted {kind} {path}: '
                                f'{target} is not owned by the current user or root.')
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise InvalidConfig(f'Refusing untrusted {kind} {path}: '
                                f'{target} is writable by group or others.')
    return path


# The machine file's [series."<x.y>"] keys: the Odoo source of the series (the defaults of
# [tooling].community and [tooling].enterprise) and where new environments go by default (read by
# oasis setup; it never chooses a checkout's environment).
MACHINE_KEYS = ('community', 'enterprise', 'environments')


def machine_file() -> Path | None:
    """Where the optional machine file is: $XDG_CONFIG_HOME/oasis/config.toml when that variable is
    an absolute path (the XDG rule ignores a relative one), else ~/.config/oasis/config.toml; None
    when there is no home directory to look in."""
    configured = os.environ.get('XDG_CONFIG_HOME', '')
    if os.path.isabs(configured):
        return Path(configured) / 'oasis' / 'config.toml'
    try:
        return Path.home() / '.config' / 'oasis' / 'config.toml'
    except RuntimeError:
        return None


def machine_series(series: str) -> tuple[Path | None, dict[str, str]]:
    """The machine file read (None without one) and its [series."<series>"] values as absolute paths.

    Trusted like a workspace file; the whole file is checked, every series. A relative path
    resolves from the machine file's directory.
    """
    path = machine_file()
    if path is None or not os.path.lexists(path):
        return None, {}
    document = read_toml(trusted(path, 'machine file'))
    for key in document:
        if key != 'series':
            raise InvalidConfig(f'Unknown key {key} in {path}; the machine file holds only '
                                '[series."<version>"] tables.')
    tables = document.get('series', {})
    if not isinstance(tables, dict):
        raise InvalidConfig(f'Invalid [series] in {path}.')
    for name, table in tables.items():
        if name not in versions().CAPABILITIES:
            raise InvalidConfig(f'Unknown series {shown(name)} in {path}; '
                                f'supported: {", ".join(versions().supported())}.')
        if not isinstance(table, dict):
            raise InvalidConfig(f'Invalid [series.{shown(name)}] in {path}.')
        for key, value in table.items():
            if key not in MACHINE_KEYS:
                raise InvalidConfig(f'Unknown key series.{shown(name)}.{key} in {path}; '
                                    'use community, enterprise or environments.')
            if not isinstance(value, str) or not value or '\x00' in value or '\n' in value:
                raise InvalidConfig(f'Invalid machine path series.{shown(name)}.{key} in {path}.')
    return path, {key: str((path.parent / value).resolve()) for key, value in tables.get(series, {}).items()}


def missing_source(series: str, machine: Path | None, workspace: Path) -> str:
    """The refusal of a workspace without [tooling].community when the machine file (machine,
    None when absent) gives none for the series: the machine file is the default place for it."""
    table = f'[series.{json.dumps(series)}]'
    if machine is None:
        location = machine_file()
        return (f'No Odoo source for {series}: create the machine file '
                f'{location if location is not None else "~/.config/oasis/config.toml"} with community under '
                f'{table}, or set [tooling].community in {workspace}.')
    return (f'No Odoo source for {series}: set community under {table} in the machine file {machine}, '
            f'or [tooling].community in {workspace}.')


def shown(value) -> str:
    """A TOML value for a message: JSON form (strings quoted), `(missing)` when absent."""
    return '(missing)' if value is MISSING else json.dumps(value, default=str)


def read_toml(path: Path) -> dict:
    try:
        with path.open('rb') as stream:
            return tomllib.load(stream)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise InvalidConfig(f'Invalid TOML in {path}.') from exc


def workspace_document(workspace: Path, selected=None, series=None) -> tuple[dict, str]:
    """The workspace document, trusted and versions checked, with the derived [tooling] keys of series
    (None: the workspace odoo_version), and the name of its environment (empty without named
    [environments]).

    selected is the checkout's environment name (None: the default one).
    """
    document = checked_workspace(workspace)
    return series_document(document, workspace, selected, document['odoo_version'] if series is None else series)


def checked_workspace(workspace: Path) -> dict:
    """The workspace document as written, trusted, with its versions, [tooling] and (version 2) its
    series sections checked; series_document derives a checkout's [tooling] from it."""
    return checked_document(read_toml(trusted(workspace)), workspace)


def checked_document(document: dict, workspace: Path) -> dict:
    """checked_workspace for a document already read (oasis setup checks the file it is about to write)."""
    version = document.get('workspace_version', MISSING)
    if type(version) is not int or version not in WORKSPACE_VERSIONS:
        raise InvalidConfig(f'Unsupported workspace_version {shown(version)} in {workspace}.')
    odoo = document.get('odoo_version', MISSING)
    if not isinstance(odoo, str) or odoo not in versions().CAPABILITIES:
        raise InvalidConfig(f'Unsupported odoo_version {shown(odoo)} in {workspace}; '
                            f'supported: {", ".join(versions().supported())}.')
    tooling = document.get('tooling')
    if not isinstance(tooling, dict):
        raise InvalidConfig('Invalid tooling configuration.')
    for key in ('version', 'python_version'):
        if key in tooling:
            raise InvalidConfig(f'[tooling].{key} is derived in a workspace; remove it from {workspace}.')
    if 'checkout_slug' in tooling:
        # One slug for every checkout would give them all one database namespace.
        raise InvalidConfig("[tooling].checkout_slug belongs in a checkout's oasis-checkout.toml, "
                            f'not in {workspace}.')
    if version == 2:
        if 'series_exceptions' in tooling:
            raise InvalidConfig(f'[tooling].series_exceptions belongs in a [series."<version>"] section of {workspace}.')
        series_sections(document, workspace)
    return document


def series_sections(document: dict, workspace: Path) -> dict[str, dict]:
    """The checked [series."<x.y>"] sections of a version 2 document, in file order ({} for version 1,
    which does not read them): supported series only, SERIES_KEYS only, series_exceptions a list of
    module names. Their values keep the [tooling] rules (resolve checks them once merged)."""
    if document['workspace_version'] == 1:
        return {}
    tables = document.get('series', {})
    if not isinstance(tables, dict):
        raise InvalidConfig(f'Invalid [series] in {workspace}.')
    for name, table in tables.items():
        if name not in versions().CAPABILITIES:
            raise InvalidConfig(f'Unknown series {shown(name)} in {workspace}; '
                                f'supported: {", ".join(versions().supported())}.')
        if not isinstance(table, dict):
            raise InvalidConfig(f'Invalid [series.{shown(name)}] in {workspace}.')
        for key in table:
            if key not in SERIES_KEYS:
                raise InvalidConfig(f'Unknown key series.{shown(name)}.{key} in {workspace}; '
                                    f'a series section may set: {", ".join(SERIES_KEYS)}.')
        exceptions = table.get('series_exceptions', [])
        if not isinstance(exceptions, list) or not all(isinstance(module, str) and MODULE_NAME.fullmatch(module)
                                                       for module in exceptions):
            raise InvalidConfig(f'Invalid series.{shown(name)}.series_exceptions in {workspace}: '
                                'use a list of module names.')
    return tables


def declared_series(document: dict, workspace: Path) -> list[str]:
    """Every series a checked document configures: odoo_version first, then its sections in file order."""
    default = document['odoo_version']
    return [default, *(name for name in series_sections(document, workspace) if name != default)]


def placed(value, series: str):
    """A version 2 path value with SERIES_PLACEHOLDER replaced by series; any other value unchanged."""
    return value.replace(SERIES_PLACEHOLDER, series) if isinstance(value, str) else value


def series_tooling(document: dict, workspace: Path, series: str) -> dict:
    """[tooling] of a checked document for series, before the derived keys and named environments:
    version 1 as written; version 2 with its [series."<series>"] values over it, SERIES_PLACEHOLDER
    replaced in SERIES_PATHS and series_exceptions (empty without one). Doctor reads every series of
    the workspace with it (series isolation)."""
    tooling = dict(document['tooling'])
    if document['workspace_version'] == 1:
        return tooling
    tooling.update(series_sections(document, workspace).get(series, {}))
    tooling.setdefault('series_exceptions', [])
    return {key: placed(value, series) if key in SERIES_PATHS else value for key, value in tooling.items()}


def series_document(document: dict, workspace: Path, selected, series: str) -> tuple[dict, str]:
    """workspace_document for a checked document and the checkout's series."""
    version2 = document['workspace_version'] == 2
    section = series_sections(document, workspace).get(series, {})
    # Derived: the Odoo series of the checkout, Python from the named environment, else the
    # series' default (tools/odoo_versions.py python_default).
    tooling = {**series_tooling(document, workspace, series), 'version': series,
               'python_version': versions().capability(series, 'python_default')}
    name = ''
    # Version 2: the checkout's named environment, else the section's environment path, else the
    # default named environment, else [tooling].environment.
    if selected is not None or ('environments' in document and 'environment' not in section):
        name, environment, python = named_environment(document, workspace, series, selected)
        # The selected path takes the place of [tooling].environment and keeps its rules.
        tooling['python_version'] = python
        if environment is not MISSING:
            tooling['environment'] = placed(environment, series) if version2 else environment
    document['tooling'] = tooling
    return document, name


def named_environment(document: dict, workspace: Path, odoo: str, selected) -> tuple[str, object, str]:
    """The selected [environments.<name>]: its name, path (MISSING when absent) and Python."""
    environments = document.get('environments', {})
    if not isinstance(environments, dict):
        raise InvalidConfig(f'Invalid [environments] in {workspace}.')
    if environments and 'environment' in document['tooling']:
        raise InvalidConfig(f'Set either [tooling].environment or [environments] in {workspace}, not both.')
    name = DEFAULT_ENVIRONMENT if selected is None else selected
    if not isinstance(name, str) or name not in environments:
        raise InvalidConfig(f'Unknown environment {shown(name)}; {workspace} declares: '
                            f'{", ".join(environments) or "(none)"}.')
    environment = environments[name]
    if not isinstance(environment, dict):
        raise InvalidConfig(f'Invalid environment {shown(name)} in {workspace}.')
    python = environment.get('python', MISSING)
    if not versions().python_supported(odoo, python):
        low, high = versions().capability(odoo, 'python')
        raise InvalidConfig(f'Unsupported python {shown(python)} for environment {shown(name)} in '
                            f'{workspace}; Odoo {odoo} supports {low} to {high}.')
    return name, environment.get('path', MISSING), python


CHECKOUT_KEYS = ('checkout_slug', 'environment')
CHECKOUT_ONLY = (f'{CHECKOUT_NAME} may only set odoo_version, '
                 + ' and '.join(f'[tooling].{key}' for key in CHECKOUT_KEYS))


def checkout_overrides(root: Path) -> dict:
    """[tooling] keys of the optional checkout file; only CHECKOUT_KEYS are accepted."""
    return dict(checkout_file(root).get('tooling', {}))


def checkout_file(root: Path) -> dict:
    """The optional checkout file ({} without one): [tooling] with only CHECKOUT_KEYS, and the
    checkout's series as a top-level odoo_version (checked by checkout_series)."""
    path = root / CHECKOUT_NAME
    if not path.is_file():
        return {}
    document = read_toml(trusted(path))
    for key, value in document.items():
        if key == 'odoo_version':
            continue
        if key != 'tooling' or not isinstance(value, dict):
            raise InvalidConfig(f'{CHECKOUT_ONLY}: {key}')
        for name in value:
            if name not in CHECKOUT_KEYS:
                raise InvalidConfig(f'{CHECKOUT_ONLY}: tooling.{name}')
    return document


def series_key(series: str) -> tuple[int, ...]:
    return tuple(int(part) for part in series.split('.'))


def checkout_series(root: Path, document: dict, workspace: Path, declared) -> tuple[str, str]:
    """The series of the checkout root and where it came from: `checkout` (declared, its
    oasis-checkout.toml odoo_version; MISSING when absent), `manifests` (version 2: detected_series)
    or `workspace` (the workspace odoo_version). A series other than the workspace odoo_version needs
    its section (MissingSeries, which names oasis setup)."""
    default = document['odoo_version']
    if declared is not MISSING:
        path = root / CHECKOUT_NAME
        if not isinstance(declared, str) or declared not in versions().CAPABILITIES:
            raise InvalidConfig(f'Unsupported odoo_version {shown(declared)} in {path}; '
                                f'supported: {", ".join(versions().supported())}.')
        series, origin, reason = declared, 'checkout', f'odoo_version in {path}'
    else:
        detected = detected_series(root, document, workspace) if document['workspace_version'] == 2 else None
        series, origin, reason = ((detected, 'manifests', 'the series of its module manifests') if detected
                                  else (default, 'workspace', ''))
    if series != default and series not in series_sections(document, workspace):
        raise MissingSeries(f'{root} is an Odoo {series} checkout ({reason}), but {workspace} has no '
                            f'[series.{json.dumps(series)}] section: run {program_name()} setup to add it.')
    return series, origin


def detected_series(root: Path, document: dict, workspace: Path, also_ignored=()) -> str | None:
    """The one supported series the module manifests of root's addons paths declare (manifest_series),
    the series_exceptions of every section left out (and the modules also_ignored: oasis setup's
    --exception); None without any (or with invalid addons paths, which resolve refuses). Several
    series are refused, naming each with its first module."""
    addons = document['tooling'].get('addons_paths')
    if not isinstance(addons, list) or not all(isinstance(path, str) and path and '\x00' not in path
                                               and '\n' not in path for path in addons):
        return None
    ignored = {module for table in series_sections(document, workspace).values()
               for module in table.get('series_exceptions', [])} | set(also_ignored)
    found = {}
    for manifest in addon_manifests(str((root / path).resolve()) for path in addons):
        if manifest.parent.name in ignored:
            continue
        declared = manifest_series(manifest, document['odoo_version'])
        if declared is not None and declared[0] in versions().CAPABILITIES:
            found.setdefault(declared[0], manifest.parent.name)
    if len(found) > 1:
        listed = ', '.join(f'{series} ({found[series]})' for series in sorted(found, key=series_key))
        raise InvalidConfig(f'The modules of {root} declare several Odoo series: {listed}; set odoo_version in '
                            f'{root / CHECKOUT_NAME} to the series of this checkout, or list the modules of the '
                            f'other series in series_exceptions under its [series."<version>"] in {workspace}.')
    return next(iter(found), None)


def configuration(root: Path) -> tuple[dict, Path, Path]:
    """The document that configures root, the directory its paths resolve from (the workspace
    directory) and the workspace file. workspace_configuration() also names the selected
    environment.

    The trusted workspace file root reads (workspace_file) with the checkout's overrides. Tools that read
    their own sections ([development], lint_rcfile) use this, so they see the same file and base
    as load().
    """
    document, base, workspace, _name = workspace_configuration(root)
    return document, base, workspace


def workspace_configuration(root: Path) -> tuple[dict, Path, Path, str]:
    """configuration() plus the selected environment name; a legacy profile in root is refused
    first, also next to a workspace file."""
    document, base, workspace, name, _origins, _refusal = layered_configuration(root)
    return document, base, workspace, name


def layered_configuration(root: Path, planned: dict | None = None) -> tuple[dict, Path, Path, str, dict[str, str], str]:
    """workspace_configuration() plus where its layered values came from (see origins) and the
    refusal resolve() gives when neither the workspace nor the machine file sets the community
    source (missing_source).

    The machine file's series values fill only the source keys the workspace does not set;
    `enterprise = false` in the workspace means no Enterprise, whatever the machine file says.
    planned, when given, is the checked document oasis setup is about to write to the workspace file,
    read in its place (it is changed).
    """
    profile = root / PROFILE_NAME
    if profile.is_file():
        raise InvalidConfig(legacy_profile_refusal(profile, program_name()))
    workspace = workspace_file(root)
    if workspace is None:
        raise InvalidConfig(missing_configuration(root))
    checkout = checkout_file(root)
    overrides = dict(checkout.get('tooling', {}))
    # The checkout's environment is a name of [environments], not the [tooling] path.
    selected = overrides.pop('environment', None)
    document = checked_workspace(workspace) if planned is None else planned
    series, series_from = checkout_series(root, document, workspace, checkout.get('odoo_version', MISSING))
    document, name = series_document(document, workspace, selected, series)
    document['tooling'].update(overrides)
    tooling = document['tooling']
    machine, defaults = machine_series(tooling['version'])
    origins = {'MACHINE_FILE': str(machine) if machine is not None else '',
               'MACHINE_ENVIRONMENTS_DIR': defaults.get('environments', '')}
    for key, variable in (('community', 'ODOO_SOURCE'), ('enterprise', 'ENTERPRISE_SOURCE')):
        if key not in tooling and key in defaults:
            tooling[key] = defaults[key]
            origins[f'{variable}_FROM'] = 'machine'
        else:
            origins[f'{variable}_FROM'] = 'workspace' if tooling.get(key) not in (None, False) else ''
    origins['PROJECT_ENVIRONMENT_FROM'] = 'checkout' if selected is not None else 'workspace'
    origins['CHECKOUT_SLUG_FROM'] = 'checkout' if 'checkout_slug' in overrides else ''
    if document['workspace_version'] == 2:
        origins['ODOO_VERSION_FROM'] = series_from
    refusal = missing_source(tooling['version'], machine, workspace)
    return document, workspace.parent, workspace, name, origins, refusal


def load(root: Path, *, series_guard: bool = True) -> dict[str, str]:
    """Validated assignments for root (see configuration), refused when a module of its addons paths
    declares another Odoo series (series_mismatch; v0.14.0 S11). Only doctor reads them without the
    guard (series_guard=False), to report it as one check."""
    document, base, workspace, name, _origins, refusal = layered_configuration(root)
    values = assignments(document, root, base, workspace, name, missing_source=refusal)
    if series_guard:
        mismatch = series_mismatch(values)
        if mismatch is not None:
            raise InvalidConfig(series_refusal(mismatch, values))
    return values


# A series-style module version: <major>.<minor>.<x>.<y>.<z> (<series>.1.0.0), no leading zeros in
# the series. tools/setup.py reads the series of a new checkout with manifest_series too.
SERIES_VERSION = re.compile(r'([1-9][0-9]*)\.(0|[1-9][0-9]*)\.[0-9]+\.[0-9]+\.[0-9]+')
# A series that is not in tools/odoo_versions.py still counts when it looks like an Odoo release:
# <major>.0 with a major from 8 (the first series whose modules carry series-style versions) to 99.
PLAUSIBLE_MAJORS = range(8, 100)
# The `version` key of a manifest, anywhere (VERSION_KEY), and as one plain string literal followed by
# the end of its entry (VERSION_ENTRY): what manifest_series reads before it parses a manifest.
VERSION_KEY = re.compile(r'''["']version["']\s*:''')
VERSION_ENTRY = re.compile(r'''["']version["']\s*:\s*(["'])([^"'\\\n]*)\1\s*[,}]''')


def manifest_series(manifest: Path, expected: str | None = None) -> tuple[str, str] | None:
    """(series, version) of a module manifest whose `version` is series-style for a known or
    plausible series, else None (also when it cannot be read or is not a literal dict). Read with
    ast.literal_eval, never imported; a file without any series-style number is not parsed.

    The version string is read with a narrow pattern first, when the manifest has the `version` key
    once, as one plain string: a version that is not series-style is None and one of the expected
    series (when given) is returned, both unparsed. Only another series, or a manifest the pattern
    cannot tell, is parsed, so a manifest with an unrelated syntax error of the right series is
    still read as that series, and the refusal of another series stays the literal dict's."""
    try:
        text = manifest.read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        return None
    if not SERIES_VERSION.search(text):
        return None
    entry = VERSION_ENTRY.search(text) if len(VERSION_KEY.findall(text)) == 1 else None
    if entry is not None:
        found = SERIES_VERSION.fullmatch(entry.group(2))
        if found is None:
            return None
        if f'{found.group(1)}.{found.group(2)}' == expected:
            return expected, entry.group(2)
    try:
        data = ast.literal_eval(text)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None
    version = data.get('version') if isinstance(data, dict) else None
    match = SERIES_VERSION.fullmatch(version) if isinstance(version, str) else None
    if match is None:
        return None
    series = f'{match.group(1)}.{match.group(2)}'
    if series not in versions().CAPABILITIES and not (match.group(2) == '0'
                                                      and int(match.group(1)) in PLAUSIBLE_MAJORS):
        return None
    return series, version


def addon_manifests(roots):
    """`<addons path>/<module>/__manifest__.py` of each addons path, in their order, then by module
    directory name; hidden directories skipped."""
    for addons in roots:
        for manifest in sorted(Path(addons).glob('*/__manifest__.py')):
            if not manifest.parent.name.startswith('.'):
                yield manifest


def series_mismatch(values: dict[str, str]) -> dict | None:
    """The first module of the addons paths (addon_manifests) whose manifest declares another series
    than ODOO_VERSION, SERIES_EXCEPTIONS left out (version 2, S4): its module, manifest, series and
    version; None when there is none."""
    expected = values['ODOO_VERSION']
    ignored = set(values.get('SERIES_EXCEPTIONS', '').splitlines())
    for manifest in addon_manifests(values['ADDON_ROOTS'].splitlines()):
        if manifest.parent.name in ignored:
            continue
        declared = manifest_series(manifest, expected)
        if declared is not None and declared[0] != expected:
            return {'module': manifest.parent.name, 'manifest': str(manifest), 'series': declared[0],
                    'version': declared[1]}
    return None


def series_fix(mismatch: dict, expected: str, values: dict[str, str] | None = None) -> str:
    """How to fix a series mismatch (doctor's fix line and the end of series_refusal). With the
    assignments of a version 2 checkout (values), the fix also names series_exceptions. For a
    supported series it ends with the series model (S3): the checkout file's odoo_version when the
    workspace configures that series, else oasis setup to add its section."""
    program, module, found = program_name(), mismatch['module'], mismatch['series']
    fix = (f'run {program} in a checkout of an Odoo {expected} branch, or set the version of {module} to '
           f'{expected}.x.y.z if it is an Odoo {expected} module')
    if values is None:
        workspace, configured = None, []
    else:
        workspace = Path(values['WORKSPACE_ROOT']) / WORKSPACE_NAME
        configured = workspace_series(workspace) if values.get('WORKSPACE_VERSION') == '2' else []
    if configured:
        fix += f', or list {module} in series_exceptions under [series.{json.dumps(expected)}] in {workspace}'
    if found not in versions().CAPABILITIES:
        return fix + f'; {program} does not support Odoo {found} (supported: {", ".join(versions().supported())})'
    if found in configured:
        return fix + (f"; for Odoo {found} here, set odoo_version = '{found}' in "
                      f'{Path(values["PROJECT_ROOT"]) / CHECKOUT_NAME}')
    return fix + (f'; for Odoo {found} here, run {program} setup to add a [series.{json.dumps(found)}] section to '
                  f'{workspace if workspace is not None else WORKSPACE_NAME}')


def workspace_series(workspace: Path) -> list[str]:
    """declared_series of a version 2 workspace file, [] when it cannot be read (a message only)."""
    try:
        document = checked_workspace(workspace)
    except InvalidConfig:
        return []
    return declared_series(document, workspace) if document['workspace_version'] == 2 else []


def series_refusal(mismatch: dict, values: dict[str, str]) -> str:
    """The refusal of a checkout with a module of another series: the module, both series, the fix."""
    expected = values['ODOO_VERSION']
    workspace = Path(values['WORKSPACE_ROOT']) / WORKSPACE_NAME
    return (f'The module {mismatch["module"]} declares Odoo {mismatch["series"]} (version {mismatch["version"]} '
            f'in {mismatch["manifest"]}), but {values["PROJECT_ROOT"]} is configured for Odoo {expected} by '
            f'{workspace}: {series_fix(mismatch, expected, values)}.')


def origins(root: Path) -> dict[str, str]:
    """Where root's layered values came from, once its whole configuration is valid (as load):
    MACHINE_FILE (the machine file read, empty without one), MACHINE_ENVIRONMENTS_DIR (its
    environments default for the series, empty when absent), then ODOO_SOURCE_FROM and
    ENTERPRISE_SOURCE_FROM (`machine` or `workspace`; empty without Enterprise),
    PROJECT_ENVIRONMENT_FROM (`checkout` when oasis-checkout.toml selects the named environment,
    else `workspace`) and CHECKOUT_SLUG_FROM (`checkout`, `derived` from a linked worktree's
    directory name, empty without a slug); version 2 adds ODOO_VERSION_FROM (checkout_series)."""
    document, base, workspace, name, found, refusal = layered_configuration(root)
    values = assignments(document, root, base, workspace, name, missing_source=refusal)
    if values['CHECKOUT_SLUG'] and not found['CHECKOUT_SLUG_FROM']:
        found['CHECKOUT_SLUG_FROM'] = 'derived'
    return found


def assignments(document: dict, root: Path, base: Path, workspace: Path | None, name: str, *,
                missing_source: str = '') -> dict[str, str]:
    """The assignments of a configuration document whose [tooling] carries version and
    python_version. workspace None (WORKSPACE_ROOT empty) is only tools/migrate.py's reading of
    a legacy profile, to compare a checkout before and after converting it. missing_source: see
    resolve."""
    output = resolve(document, root, base, missing_source=missing_source)
    # Appended last, so the previous assignments stay unchanged.
    output['WORKSPACE_ROOT'] = str(workspace.parent) if workspace is not None else ''
    # Appended after it: the Odoo series and the options that differ between series, which
    # tools render instead of writing them (odoo_versions.py), then the selected environment.
    version = document['tooling']['version']
    output['ODOO_VERSION'] = version
    output['ODOO_SECOND_PORT_OPTION'] = versions().capability(version, 'second_port_option')
    output['ODOO_DEMO_OFF_ARGS'] = shlex.join(versions().capability(version, 'demo_off_args'))
    output['ENVIRONMENT_NAME'] = name
    output['PYTHON_VERSION'] = document['tooling']['python_version']
    # Appended after them: Odoo's data directory, passed as --data-dir (empty when absent:
    # the odoo.conf data_dir, if any, applies as before).
    output['DATA_DIR'] = optional_path(document['tooling'], 'data_dir', base)
    # Appended after them: what the Gentle Shell layer does with the agent's destructive commands.
    output['AGENT_DESTRUCTIVE'] = agent_destructive(document['tooling'])
    # Appended last, only for workspace_version 2 (version 1 output is unchanged): the version and the
    # checkout series' exceptions (newline-separated module names), which series_mismatch leaves out.
    if document.get('workspace_version') == 2:
        output['WORKSPACE_VERSION'] = '2'
        output['SERIES_EXCEPTIONS'] = '\n'.join(document['tooling'].get('series_exceptions', []))
    return output


AGENT_DESTRUCTIVE = ('ask', 'deny', 'allow')


def agent_destructive(tooling: dict) -> str:
    """[tooling].agent_destructive, `ask` when absent. The user sets it in the workspace file;
    oasis-checkout.toml refuses it (CHECKOUT_KEYS)."""
    value = tooling.get('agent_destructive', 'ask')
    if not isinstance(value, str) or value not in AGENT_DESTRUCTIVE:
        raise InvalidConfig('Invalid tooling agent_destructive: use ask, deny or allow.')
    return value


def optional_path(tooling: dict, key: str, base: Path) -> str:
    """An optional tooling path resolved from base, or '' when absent."""
    if key not in tooling:
        return ''
    value = tooling[key]
    if not isinstance(value, str) or not value or '\x00' in value or '\n' in value:
        raise InvalidConfig(f'Invalid tooling path: {key}.')
    return str((base / value).resolve())


def resolve(document: dict, root: Path, base: Path, *, missing_source: str = '') -> dict[str, str]:
    """Validated assignments for the checkout root.

    Paths resolve from base (the workspace directory), except addons_paths, which always
    resolve from the checkout root. workspace_document has checked the version and Python.
    missing_source, when given, is the error of an absent community (the machine file gives
    none either); a declared but invalid one stays `Invalid tooling path: community.`
    """
    try:
        tooling = document['tooling']
    except (KeyError, TypeError) as exc:
        raise InvalidConfig('Invalid tooling configuration.') from exc
    if not isinstance(tooling, dict):
        raise InvalidConfig('Invalid tooling configuration.')
    for section, advisory, consumed in (
            ('odoo', 'version', 'version'), ('odoo', 'community', 'community'),
            ('environment', 'config', 'config'), ('database', 'test_prefix', 'test_prefix')):
        declared = document.get(section, {})
        if not isinstance(declared, dict) or (advisory in declared
                                              and declared[advisory] != tooling.get(consumed)):
            raise InvalidConfig(f'Conflicting advisory and tooling values: {section}.{advisory}.')
    environment = document.get('environment', {})
    if not isinstance(environment, dict):
        raise InvalidConfig('Invalid tooling configuration.')
    configured_env = tooling.get('environment')
    if ('python' in environment and isinstance(configured_env, str)
            and environment['python'] != str(Path(configured_env) / 'bin/python')):
        raise InvalidConfig('Conflicting advisory and tooling values: environment.python.')
    dev = tooling.get('dev_prefix')
    test = tooling.get('test_prefix')
    if (not isinstance(dev, str) or not isinstance(test, str)
            or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]+_dev_', dev)
            or test != dev[:-4] + 'test_'):
        raise InvalidConfig('Unsafe tooling database prefixes.')
    output = {'PROJECT_ROOT': str(root), 'PROJECT_NAME': root.name,
              'DEV_PREFIX': dev, 'TEST_PREFIX': test, 'TEST_DATABASE': ''}
    if 'test_database' in tooling:
        database = tooling['test_database']
        if (not isinstance(database, str)
                or not re.fullmatch(r'[A-Za-z0-9_]+', database)
                or not database.startswith(test) or database == test
                or len(database.encode('utf-8')) > 56):
            raise InvalidConfig('Unsafe tooling test database.')
        # Reserve seven bytes for verify-module's separate _update target.
        output['TEST_DATABASE'] = database
    for key, variable in PATHS.items():
        value = tooling.get(key)
        # Absent, or false (no Enterprise even when the machine file gives one): not emitted.
        if key == 'enterprise' and (value is None or value is False):
            continue
        if key == 'community' and key not in tooling and missing_source:
            raise InvalidConfig(missing_source)
        if not isinstance(value, str) or not value or '\x00' in value or '\n' in value:
            raise InvalidConfig(f'Invalid tooling path: {key}.')
        output[variable] = str((base / value).resolve())
    # Optional; emitted last (empty when absent) so the previous assignments stay unchanged.
    logs_dir = optional_path(tooling, 'logs', base)
    environment_target(Path(output['PROJECT_ENVIRONMENT']), root, Path(output['ODOO_SOURCE']))
    addons = tooling.get('addons_paths')
    if not isinstance(addons, list) or not addons or any(
            not isinstance(path, str) or not path or '\x00' in path or '\n' in path
            for path in addons):
        raise InvalidConfig('Invalid tooling addon roots.')
    # A newline-separated path list is safe because paths with newlines are rejected.
    output['ADDON_ROOTS'] = '\n'.join(str((root / path).resolve()) for path in addons)
    service = tooling.get('db_service')
    if not isinstance(service, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', service):
        raise InvalidConfig('Invalid tooling database service.')
    output['DB_SERVICE'] = service
    output['PYTHON'] = str(Path(output['PROJECT_ENVIRONMENT']) / 'bin/python')
    output['ODOO_BIN'] = str(Path(output['ODOO_SOURCE']) / 'odoo-bin')
    output['ENVIRONMENTS_DIR'] = str(Path(output['PROJECT_ENVIRONMENT']).parent)
    override = tooling.get('checkout_slug')
    if 'checkout_slug' in tooling and (not isinstance(override, str)
                                       or not SLUG.fullmatch(override)):
        raise InvalidConfig('Invalid tooling checkout slug.')
    kind, top, main = checkout_identity(root, override)
    # A checkout file's slug wins for every kind; only a linked worktree derives one.
    output['CHECKOUT_KIND'] = kind
    output['CHECKOUT_SLUG'] = (override if override is not None
                               else derived_slug(top, main) if kind == 'linked' else '')
    # The main checkout's work tree: a linked worktree may keep its dev/logs linked there.
    # Empty when git failed in a linked worktree with a checkout slug (main checkout unknown).
    output['CHECKOUT_MAIN_ROOT'] = (str(main) if kind == 'linked' and main is not None
                                    else str(root) if kind == 'main' else '')
    slug = output['CHECKOUT_SLUG']
    # common.sh inserts '<slug>_' after test_prefix; the result must still leave room for
    # verify-module's _update sibling.
    if output['TEST_DATABASE'] and slug and len(output['TEST_DATABASE'].encode('utf-8')) + len(slug) + 1 > 56:
        raise InvalidConfig(f'Tooling test database exceeds 56 bytes with checkout slug {slug}.')
    # Compact runs and browser evidence go to <LOGS_DIR>/<slug or main> when set.
    output['LOGS_DIR'] = logs_dir
    return output


def environment_target(target: Path, root: Path, source: Path) -> None:
    """Refuse an environment target (resolved) that is or contains the checkout root, is or contains
    the Odoo source, or exists without being a Python environment (no pyvenv.cfg). Any other
    directory is accepted, whatever its name or place (v0.14.0 S5)."""
    if root.is_relative_to(target):
        reason = f'is or contains the checkout {root}'
    elif source.is_relative_to(target):
        reason = f'is or contains the Odoo source {source}'
    elif os.path.lexists(target) and not os.path.isfile(target / 'pyvenv.cfg'):
        reason = 'exists and is not a Python environment (no pyvenv.cfg)'
    else:
        return
    raise InvalidConfig(f'Unsafe tooling environment target: {target} {reason}.')


def release_is(path: Path, version: str) -> bool:
    """Whether the release.py at path declares the Odoo series version ("<major>.<minor>")."""
    try:
        series = tuple(int(part) for part in version.split('.'))
    except ValueError:
        return False
    if len(series) != 2:
        return False
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, SyntaxError):
        return False
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == 'version_info'
                for target in node.targets):
            value = node.value
            if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) >= 2:
                return all(isinstance(item, ast.Constant) and type(item.value) is int
                           and item.value == expected
                           for item, expected in zip(value.elts[:2], series))
    return False


def main() -> int:
    # --release <release.py> <series>: whether that Odoo source declares the series.
    if len(sys.argv) == 4 and sys.argv[1] == '--release':
        return 0 if release_is(Path(sys.argv[2]), sys.argv[3]) else 2
    # --origins <root>: where the layered values came from (see origins), for doctor.
    arguments = sys.argv[2:] if len(sys.argv) > 1 and sys.argv[1] == '--origins' else sys.argv[1:]
    if len(arguments) != 1 or not Path(arguments[0]).is_absolute():
        print('ERROR: Usage: config.py <absolute-project-root>\n'
              '       config.py --origins <absolute-project-root>\n'
              '       config.py --release <release.py> <series>', file=sys.stderr)
        return 2
    reader = origins if len(arguments) != len(sys.argv) - 1 else load
    try:
        values = reader(Path(arguments[0]).resolve())
    except InvalidConfig as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    for variable, value in values.items():
        print(f'{variable}={shlex.quote(value)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
