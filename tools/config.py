#!/usr/bin/env python3
"""Parse project-owned tooling paths into literal shell assignments, not shell code.

The caller must supply the project (checkout) root; this module never discovers it from its
own (global installation) location. A checkout without `.odoo19-agent.toml` reads the nearest
`oasis-workspace.toml` above it. Path declarations do not grant access consent.
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


PROFILE_NAME = '.odoo19-agent.toml'
WORKSPACE_NAME = 'oasis-workspace.toml'
CHECKOUT_NAME = 'oasis-checkout.toml'
WORKSPACE_VERSION = 1
# The Python of a profile, and of a workspace that sets [tooling].environment instead of
# named [environments]; a named environment declares its own within the Odoo series' range.
LEGACY_PYTHON = '3.12'
LEGACY_VERSION = '19.0'
DEFAULT_ENVIRONMENT = 'default'
MISSING = object()


class InvalidConfig(ValueError):
    pass


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
    only a profile slug lets it continue (kind `linked`, main checkout unknown). A `.git`
    directory (or anything else) stops with the reason.
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

    Searched like git searches `.git`, up to the filesystem root. A directory that holds a
    legacy profile (root included) ends the search: that profile's checkout owns the tree.
    """
    for directory in (root, *root.parents):
        if (directory / PROFILE_NAME).is_file():
            return None
        candidate = directory / WORKSPACE_NAME
        if candidate.is_file():
            return candidate
    return None


def trusted(path: Path) -> Path:
    """path, refused unless it and its directory are owned by the current user or root and are
    not group- or other-writable: a file found above the checkout must not be one someone else
    could write. A symlinked file is checked at its target too."""
    targets = [path.resolve(), path.resolve().parent]
    if path.parent.resolve() not in targets:
        targets.append(path.parent.resolve())
    for target in targets:
        try:
            info = target.stat()
        except OSError as exc:
            raise InvalidConfig(f'Refusing untrusted workspace file {path}: cannot inspect {target}.') from exc
        if info.st_uid not in (os.getuid(), 0):
            raise InvalidConfig(f'Refusing untrusted workspace file {path}: '
                                f'{target} is not owned by the current user or root.')
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise InvalidConfig(f'Refusing untrusted workspace file {path}: '
                                f'{target} is writable by group or others.')
    return path


def shown(value) -> str:
    """A TOML value for a message: JSON form (strings quoted), `(missing)` when absent."""
    return '(missing)' if value is MISSING else json.dumps(value, default=str)


def read_toml(path: Path) -> dict:
    try:
        with path.open('rb') as stream:
            return tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise InvalidConfig(f'Invalid TOML in {path}.') from exc


def workspace_document(workspace: Path, selected=None) -> tuple[dict, str]:
    """The workspace document, trusted and versions checked, with the derived [tooling] keys,
    and the name of its environment (empty without named [environments]).

    selected is the checkout's environment name (None: the default one).
    """
    document = read_toml(trusted(workspace))
    version = document.get('workspace_version', MISSING)
    if type(version) is not int or version != WORKSPACE_VERSION:
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
    # Derived: the Odoo series from odoo_version, Python from the named environment.
    tooling = {**tooling, 'version': odoo, 'python_version': LEGACY_PYTHON}
    name = ''
    if 'environments' in document or selected is not None:
        name, environment, python = named_environment(document, workspace, odoo, selected)
        # The selected path takes the place of [tooling].environment and keeps its rules.
        tooling['python_version'] = python
        if environment is not MISSING:
            tooling['environment'] = environment
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
CHECKOUT_ONLY = f'{CHECKOUT_NAME} may only set ' + ' and '.join(f'[tooling].{key}' for key in CHECKOUT_KEYS)


def checkout_overrides(root: Path) -> dict:
    """[tooling] keys of the optional checkout file; only CHECKOUT_KEYS are accepted."""
    path = root / CHECKOUT_NAME
    if not path.is_file():
        return {}
    document = read_toml(trusted(path))
    for key, value in document.items():
        if key != 'tooling' or not isinstance(value, dict):
            raise InvalidConfig(f'{CHECKOUT_ONLY}: {key}')
        for name in value:
            if name not in CHECKOUT_KEYS:
                raise InvalidConfig(f'{CHECKOUT_ONLY}: tooling.{name}')
    return dict(document.get('tooling', {}))


def configuration(root: Path) -> tuple[dict, Path, Path | None]:
    """The document that configures root, the directory its paths resolve from, and the
    workspace file (None for a legacy profile). workspace_configuration() also names the
    selected environment.

    Legacy profile in root, read as before; otherwise the trusted workspace file above root
    with the checkout's overrides. Tools that read their own sections ([development],
    lint_rcfile) use this, so they see the same file and base as load().
    """
    profile = root / PROFILE_NAME
    if profile.is_file():
        try:
            with profile.open('rb') as stream:
                document = tomllib.load(stream)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            # Kept generic by design: legacy profiles keep their exact messages; only the new
            # workspace and checkout files name the file in read_toml.
            raise InvalidConfig('Invalid tooling configuration.') from exc
        return document, root, None
    document, base, workspace, _name = workspace_configuration(root)
    return document, base, workspace


def workspace_configuration(root: Path) -> tuple[dict, Path, Path, str]:
    """configuration() for a checkout without a profile, plus the selected environment name."""
    profile = root / PROFILE_NAME
    workspace = find_workspace(root)
    if workspace is None:
        raise InvalidConfig(f'Missing tooling configuration: {profile}')
    overrides = checkout_overrides(root)
    # The checkout's environment is a name of [environments], not the [tooling] path.
    selected = overrides.pop('environment', None)
    document, name = workspace_document(workspace, selected)
    document['tooling'].update(overrides)
    return document, workspace.parent, workspace, name


def load(root: Path) -> dict[str, str]:
    """Validated assignments for root (see configuration)."""
    if (root / PROFILE_NAME).is_file():
        document, base, workspace = configuration(root)
        name = ''
    else:
        document, base, workspace, name = workspace_configuration(root)
    output = resolve(document, root, base, legacy=workspace is None)
    # Appended last, so the previous assignments stay unchanged; empty for a profile.
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
    return output


def optional_path(tooling: dict, key: str, base: Path) -> str:
    """An optional tooling path resolved from base, or '' when absent."""
    if key not in tooling:
        return ''
    value = tooling[key]
    if not isinstance(value, str) or not value or '\x00' in value or '\n' in value:
        raise InvalidConfig(f'Invalid tooling path: {key}.')
    return str((base / value).resolve())


def resolve(document: dict, root: Path, base: Path, legacy: bool = True) -> dict[str, str]:
    """Validated assignments for the checkout root.

    Paths resolve from base (the profile's checkout, or the workspace directory), except
    addons_paths, which always resolve from the checkout root. A workspace document
    (legacy=False) has its version and Python checked by workspace_document already.
    """
    try:
        tooling = document['tooling']
    except (KeyError, TypeError) as exc:
        raise InvalidConfig('Invalid tooling configuration.') from exc
    if not isinstance(tooling, dict):
        raise InvalidConfig('Invalid tooling configuration.')
    if legacy and (tooling.get('version') != LEGACY_VERSION or tooling.get('python_version') != LEGACY_PYTHON):
        raise InvalidConfig(f'Tooling requires Odoo {LEGACY_VERSION} and Python {LEGACY_PYTHON}.')
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
        if key == 'enterprise' and value is None:
            continue
        if not isinstance(value, str) or not value or '\x00' in value or '\n' in value:
            raise InvalidConfig(f'Invalid tooling path: {key}.')
        output[variable] = str((base / value).resolve())
    # Optional; emitted last (empty when absent) so the previous assignments stay unchanged.
    logs_dir = optional_path(tooling, 'logs', base)
    target = Path(output['PROJECT_ENVIRONMENT'])
    source = Path(output['ODOO_SOURCE'])
    if (target == root or target in root.parents or target == source
            or target in source.parents or source.is_relative_to(target)
            or (not target.is_relative_to(root)
                and not target.parent.name.endswith('environments'))):
        raise InvalidConfig('Unsafe tooling environment target.')
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
    # A profile slug wins for every kind; only a linked worktree derives one.
    output['CHECKOUT_KIND'] = kind
    output['CHECKOUT_SLUG'] = (override if override is not None
                               else derived_slug(top, main) if kind == 'linked' else '')
    # The main checkout's work tree: a linked worktree may keep its dev/logs linked there.
    # Empty when git failed in a linked worktree with a profile slug (main checkout unknown).
    output['CHECKOUT_MAIN_ROOT'] = (str(main) if kind == 'linked' and main is not None
                                    else str(root) if kind == 'main' else '')
    slug = output['CHECKOUT_SLUG']
    # common.sh inserts '<slug>_' after test_prefix; the result must still leave room for
    # verify-module's _update sibling.
    if output['TEST_DATABASE'] and slug and len(output['TEST_DATABASE'].encode('utf-8')) + len(slug) + 1 > 56:
        raise InvalidConfig(f'Tooling test database exceeds 56 bytes with checkout slug {slug}.')
    # Compact runs and browser evidence go to <LOGS_DIR>/odoo19/<slug or main> when set.
    output['LOGS_DIR'] = logs_dir
    return output


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
    # --release <release.py> [<series>]: the series defaults to the legacy profile's.
    if len(sys.argv) in (3, 4) and sys.argv[1] == '--release':
        return 0 if release_is(Path(sys.argv[2]), sys.argv[3] if len(sys.argv) == 4 else LEGACY_VERSION) else 2
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_absolute():
        print('ERROR: Usage: config.py <absolute-project-root>', file=sys.stderr)
        return 2
    try:
        values = load(Path(sys.argv[1]).resolve())
    except InvalidConfig as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    for variable, value in values.items():
        print(f'{variable}={shlex.quote(value)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
