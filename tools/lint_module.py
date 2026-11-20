"""Run project-selected Pylint without Odoo runtime or database operations."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

USAGE = 'Usage: lint-module <module>'
HELP = USAGE + '''

Lint one whole module from the configured project addon roots.
Requires tooling.lint_rcfile and the configured isolated Python environment
with pylint and pylint-odoo supporting the declared Odoo version.
The rcfile and plugins must be trusted and their paths authorized.
Odoo/Python targets and no-persistence override rcfile settings; rules do not.
No package installs, service/database operations or automatic fixes.
Python bytecode and Pylint persistence are disabled; plugins are not sandboxed.
Pylint stdout, stderr and exit status are returned unchanged.
'''
PROBE = '''import importlib.metadata as metadata
import json
import sys
result = {'python': '%s.%s' % sys.version_info[:2],
          'prefix': sys.prefix, 'base_prefix': sys.base_prefix,
          'pylint': None, 'pylint_odoo': None, 'odoo_versions': []}
for distribution, key in (('pylint', 'pylint'), ('pylint-odoo', 'pylint_odoo')):
    try:
        result[key] = metadata.version(distribution)
    except metadata.PackageNotFoundError:
        pass
if result['pylint'] and result['pylint_odoo']:
    try:
        from pylint_odoo.misc import DFTL_VALID_ODOO_VERSIONS
        result['odoo_versions'] = list(DFTL_VALID_ODOO_VERSIONS)
    except ImportError:
        pass
print(json.dumps(result))
'''


def fail(message):
    print('ERROR: ' + message, file=sys.stderr)
    return 2


def main():
    arguments = sys.argv[1:]
    if arguments in (['--help'], ['-h']):
        print(HELP, end='')
        return 0
    if len(arguments) != 1:
        return fail(USAGE)
    module_name = arguments[0]
    if not re.fullmatch(r'[A-Za-z0-9_]+', module_name):
        return fail('Module must use only letters, numbers, and underscores.')
    selected = os.environ.get('ODOO19_PROJECT_ROOT', '')
    if not selected or not Path(selected).is_absolute() or not Path(selected).is_dir():
        return fail('ODOO19_PROJECT_ROOT must name an absolute existing project directory.')
    root = Path(selected).resolve()
    # Load the packaged parser by its own path; never import project Python code.
    spec = importlib.util.spec_from_file_location('odoo19_config', Path(__file__).with_name('config.py'))
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    try:
        values = config.load(root)
        module = None
        for declared in values['ADDON_ROOTS'].splitlines():
            addon_root = Path(declared)
            if not addon_root.is_relative_to(root):
                return fail('Lint addon roots must stay inside the project.')
            candidate = (addon_root / module_name).resolve()
            if not candidate.is_relative_to(addon_root):
                return fail('Lint module must stay inside its configured project addon root.')
            if (candidate / '__manifest__.py').is_file() and module is None:
                module = candidate
        if module is None:
            return fail('Module not found in this repository: ' + module_name)
        for path in module.rglob('*'):
            if path.is_symlink() and not path.resolve().is_relative_to(module):
                return fail('Lint module sources must stay inside its module directory.')
        # The profile's [tooling], or the workspace file's when the checkout has no profile;
        # lint_rcfile resolves from the file's directory like the other tooling paths.
        document, base, _workspace = config.configuration(root)
        tooling = document['tooling']
        rcvalue = tooling.get('lint_rcfile')
        if not isinstance(rcvalue, str) or not rcvalue.strip() or any(
                ord(char) < 32 or ord(char) == 127 for char in rcvalue):
            return fail('Declare a nonempty tooling.lint_rcfile without control characters.')
        rcfile = (base / rcvalue).resolve()
        if not rcfile.is_file():
            return fail('Lint rcfile not found: ' + str(rcfile))
        python = values['PYTHON']
        if not Path(python).is_file() or not os.access(python, os.X_OK):
            return fail('Project Python is not executable: ' + python)
        env = os.environ.copy()
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        probe = subprocess.run([python, '-I', '-B', '-c', PROBE],
                               cwd=root, env=env, text=True, capture_output=True, timeout=20)
        if probe.returncode:
            return fail('Unable to inspect project lint dependencies.')
        try:
            installed = json.loads(probe.stdout)
        except (ValueError, TypeError):
            return fail('Unable to inspect project lint dependencies.')
        if not isinstance(installed, dict):
            return fail('Unable to inspect project lint dependencies.')
        if installed.get('python') != tooling['python_version']:
            return fail('Lint requires the declared Python 3.12.')
        prefix = installed.get('prefix')
        if (not isinstance(prefix, str) or Path(prefix).resolve() != Path(values['PROJECT_ENVIRONMENT'])
                or prefix == installed.get('base_prefix')):
            return fail('Lint requires the configured isolated project environment.')
        if not installed.get('pylint') or not installed.get('pylint_odoo'):
            return fail('Project environment must provide pylint and pylint-odoo.')
        versions = installed.get('odoo_versions')
        if not isinstance(versions, list) or tooling['version'] not in versions:
            return fail(f"Installed pylint-odoo does not support Odoo {tooling['version']}.")
        argv = [python, '-I', '-B', '-m', 'pylint', '--rcfile=' + str(rcfile),
                '--valid-odoo-versions=' + tooling['version'],
                '--py-version=' + tooling['python_version'], '--persistent=no', '--', str(module)]
        os.chdir(root)
        os.execve(python, argv, env)
    except config.InvalidConfig as exc:
        return fail(str(exc))
    except (OSError, ValueError, RuntimeError, tomllib.TOMLDecodeError, subprocess.TimeoutExpired):
        return fail('Unable to prepare project lint; check declared paths and installed tools.')
    return 2  # execve replaces this process


if __name__ == '__main__':
    raise SystemExit(main())
