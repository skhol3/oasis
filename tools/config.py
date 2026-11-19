#!/usr/bin/env python3
"""Parse project-owned tooling paths into literal shell assignments, not shell code.

The caller must supply the project root; this module never discovers it from its own
(global installation) location. Path declarations do not grant access consent.
"""
import ast
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tomllib

PATHS = {
    'community': 'ODOO_SOURCE', 'enterprise': 'ENTERPRISE_SOURCE',
    'environment': 'PROJECT_ENVIRONMENT', 'config': 'ODOO_CONFIG',
    'env_file': 'ENV_FILE', 'compose': 'COMPOSE_FILE',
    'requirements': 'REQUIREMENTS_DIR',
}


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


def load(root: Path) -> dict[str, str]:
    profile = root / '.odoo19-agent.toml'
    if not profile.is_file():
        raise InvalidConfig(f'Missing tooling configuration: {profile}')
    try:
        with profile.open('rb') as stream:
            document = tomllib.load(stream)
        tooling = document['tooling']
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        raise InvalidConfig('Invalid tooling configuration.') from exc
    if not isinstance(tooling, dict):
        raise InvalidConfig('Invalid tooling configuration.')
    if tooling.get('version') != '19.0' or tooling.get('python_version') != '3.12':
        raise InvalidConfig('Tooling requires Odoo 19.0 and Python 3.12.')
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
        output[variable] = str((root / value).resolve())
    # Optional; emitted last (empty when absent) so the previous assignments stay unchanged.
    logs = tooling.get('logs')
    if 'logs' in tooling and (not isinstance(logs, str) or not logs or '\x00' in logs
                              or '\n' in logs):
        raise InvalidConfig('Invalid tooling path: logs.')
    logs_dir = str((root / logs).resolve()) if logs is not None else ''
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


def release_is_19(path: Path) -> bool:
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
                           for item, expected in zip(value.elts[:2], (19, 0)))
    return False


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == '--release':
        return 0 if release_is_19(Path(sys.argv[2])) else 2
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
