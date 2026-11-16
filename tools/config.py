#!/usr/bin/env python3
"""Parse project-owned tooling paths into literal shell assignments, not shell code.

The caller must supply the project root; this module never discovers it from its own
(global installation) location. Path declarations do not grant access consent.
"""
import ast
from pathlib import Path
import re
import shlex
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
