"""Lint CLI contracts use isolated projects and a fake project interpreter only."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROFILE = (ROOT / 'tests/fixture-workspace.toml').read_text()


class LintModuleTests(unittest.TestCase):
    def setUp(self):
        fixtures = ROOT / 'tests/fixturesroot'
        fixtures.mkdir(exist_ok=True)
        self.addCleanup(fixtures.rmdir)
        scratch = tempfile.TemporaryDirectory(dir=fixtures)
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name) / 'a project'
        self.root.mkdir()
        self.profile = self.root / 'oasis-workspace.toml'
        self.profile.write_text(PROFILE.replace("environment = '../../environments/example'",
                                                "environment = '.venv'").replace(
                                                    "addons_paths = ['.']", "addons_paths = ['addons']")
                                + "lint_rcfile = 'lint rules/.pylintrc'\n")
        self.rcfile = self.root / 'lint rules/.pylintrc'
        self.rcfile.parent.mkdir()
        self.rcfile.write_text('[MAIN]\nload-plugins=pylint_odoo\npersistent=yes\npy-version=3.8\n')
        self.module = self.root / 'addons/coffee'
        self.module.mkdir(parents=True)
        (self.module / '__manifest__.py').write_text("{'name': 'Coffee'}\n")
        (self.module / 'models.py').write_text('value = 1\n')
        self.python = self.root / '.venv/bin/python'
        self.python.parent.mkdir(parents=True)
        (self.python.parent.parent / 'pyvenv.cfg').write_text('home = /usr/bin\n')  # an environment (S5)
        self.python.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
from pathlib import Path

# Workspace files must not be group-writable (trust rule); keep test results independent of the caller's umask.
os.umask(0o022)
args = sys.argv[1:]
if '-c' in args:
    Path(os.environ['PROBE_CALL']).write_text(json.dumps(args))
    if os.environ.get('EXECUTE_PROBE') == '1':
        import importlib.metadata as metadata
        import types
        values = json.loads(os.environ['PROBE_RESULT'])
        metadata.version = lambda name: values['pylint' if name == 'pylint' else 'pylint_odoo']
        package = types.ModuleType('pylint_odoo')
        module = types.ModuleType('pylint_odoo.misc')
        module.DFTL_VALID_ODOO_VERSIONS = values['odoo_versions']
        sys.modules['pylint_odoo'] = package
        sys.modules['pylint_odoo.misc'] = module
        sys.version_info = tuple(int(part) for part in values['python'].split('.'))
        sys.prefix, sys.base_prefix = values['prefix'], values['base_prefix']
        exec(args[args.index('-c') + 1])
    else:
        print(os.environ['PROBE_RESULT'])
    raise SystemExit(0)
Path(os.environ['ANALYZER_CALL']).write_text(json.dumps({
    'argv': args, 'bytecode': os.environ.get('PYTHONDONTWRITEBYTECODE')}))
sys.stdout.write('pylint diagnostic\\n')
sys.stderr.write('pylint stderr\\n')
raise SystemExit(int(os.environ.get('LINT_EXIT', '0')))
''')
        self.python.chmod(0o755)
        self.probe = self.root / 'probe.json'
        self.analyzer = self.root / 'analyzer.json'
        self.effects = self.root / 'external.log'
        bindir = self.root / 'fake bin'
        bindir.mkdir()
        for name in ('docker', 'odoo', 'uv', 'pip'):
            trap = bindir / name
            trap.write_text('#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$EXTERNAL_CALL"\nexit 99\n')
            trap.chmod(0o755)
        self.metadata = {'python': '3.12', 'prefix': str(self.root / '.venv'),
                         'base_prefix': '/base-python', 'pylint': '4.0.10',
                         'pylint_odoo': '10.0.12', 'odoo_versions': ['18.0', '19.0']}
        self.env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
                    'PROBE_CALL': str(self.probe), 'ANALYZER_CALL': str(self.analyzer),
                    'EXTERNAL_CALL': str(self.effects), 'PROBE_RESULT': json.dumps(self.metadata),
                    'PATH': str(bindir) + os.pathsep + os.environ['PATH']}
        self.before = {p: p.read_bytes() for p in (self.profile, self.rcfile,
                       self.module / '__manifest__.py', self.module / 'models.py')}

    def invoke(self, *args):
        result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'odoo19'),
                                 '--project', str(self.root), 'lint-module', *args],
                                cwd=self.root, env=self.env, text=True, capture_output=True)
        self.assertFalse(self.effects.exists(), 'Unexpected external service/install command')
        self.assertFalse(list(self.root.rglob('__pycache__')))
        return result

    def rejected(self, args, message, *, probe=False):
        self.probe.unlink(missing_ok=True)
        self.analyzer.unlink(missing_ok=True)
        result = self.invoke(*args)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'ERROR: ' + message + '\n'))
        self.assertEqual(self.probe.exists(), probe)
        self.assertFalse(self.analyzer.exists())

    def test_help_is_public_and_does_not_require_lint_configuration(self):
        self.profile.write_text('[tooling]\n')
        result = self.invoke('--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn('Usage: lint-module <module>', result.stdout)
        self.assertIn('lint_rcfile', result.stdout)
        self.assertFalse(self.probe.exists())
        self.assertFalse(self.analyzer.exists())

    def test_whole_module_argv_targets_streams_status_and_no_mutation(self):
        self.env['LINT_EXIT'] = '28'
        result = self.invoke('coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (28, 'pylint diagnostic\n', 'pylint stderr\n'))
        self.assertEqual(json.loads(self.analyzer.read_text()), {
            'argv': ['-I', '-B', '-m', 'pylint', '--rcfile=' + str(self.rcfile),
                     '--valid-odoo-versions=19.0', '--py-version=3.12',
                     '--persistent=no', '--', str(self.module)], 'bytecode': '1'})
        for path, original in self.before.items():
            self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.root / 'dev').exists())

    def test_project_probe_reads_supported_versions_from_installed_plugin(self):
        self.env['EXECUTE_PROBE'] = '1'
        result = self.invoke('coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, 'pylint diagnostic\n', 'pylint stderr\n'))
        self.assertTrue(self.analyzer.is_file())

    def test_module_and_argument_guards_precede_interpreter(self):
        for args, message in (((), 'Usage: lint-module <module>'),
                              (('coffee', '--fix'), 'Usage: lint-module <module>'),
                              (('../coffee',), 'Module must use only letters, numbers, and underscores.'),
                              (('coffee;touch injected',), 'Module must use only letters, numbers, and underscores.'),
                              (('missing',), 'Module not found in this repository: missing')):
            with self.subTest(args=args):
                self.rejected(args, message)
        self.assertFalse((self.root / 'injected').exists())

    def test_missing_or_invalid_rcfile_is_local_to_lint(self):
        original = self.profile.read_text()
        for declaration in ('', 'lint_rcfile = 42\n', 'lint_rcfile = ""\n',
                            'lint_rcfile = "bad\\nname"\n'):
            self.profile.write_text(original.replace("lint_rcfile = 'lint rules/.pylintrc'\n", declaration))
            with self.subTest(declaration=declaration):
                self.rejected(('coffee',), 'Declare a nonempty tooling.lint_rcfile without control characters.')
        self.profile.write_text(original.replace("lint rules/.pylintrc", 'absent'))
        self.rejected(('coffee',), 'Lint rcfile not found: ' + str(self.root / 'absent'))

    def test_external_rcfile_can_be_explicitly_declared_without_rewriting_it(self):
        external = self.root.parent / 'shared lint/.pylintrc'
        external.parent.mkdir()
        external.write_bytes(self.rcfile.read_bytes())
        self.profile.write_text(self.profile.read_text().replace('lint rules/.pylintrc', '../shared lint/.pylintrc'))
        result = self.invoke('coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, 'pylint diagnostic\n', 'pylint stderr\n'))
        self.assertIn('--rcfile=' + str(external), json.loads(self.analyzer.read_text())['argv'])
        self.assertEqual(external.read_bytes(), self.before[self.rcfile])

    # Workspace mode: no profile; lint_rcfile resolves from the workspace file's directory.
    WORKSPACE = '''workspace_version = 1
odoo_version = '19.0'

[tooling]
community = 'source/odoo'
environment = 'a project/.venv'
config = 'a project/dev/odoo.conf'
env_file = 'a project/dev/.env'
compose = 'a project/dev/compose.yml'
requirements = 'a project/dev/requirements'
addons_paths = ['addons']
db_service = 'db'
dev_prefix = 'cc_dev_'
test_prefix = 'cc_test_'
'''

    def use_workspace(self, declaration="lint_rcfile = 'shared lint/.pylintrc'\n"):
        self.profile.unlink()
        workspace = self.root.parent / 'oasis-workspace.toml'
        workspace.write_text(self.WORKSPACE + declaration)
        rcfile = self.root.parent / 'shared lint/.pylintrc'
        rcfile.parent.mkdir(exist_ok=True)
        rcfile.write_bytes(self.before[self.rcfile])
        return workspace, rcfile

    def test_workspace_whole_module_argv_uses_the_workspace_rcfile(self):
        workspace, rcfile = self.use_workspace()
        self.env['LINT_EXIT'] = '28'
        result = self.invoke('coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (28, 'pylint diagnostic\n', 'pylint stderr\n'))
        self.assertEqual(json.loads(self.analyzer.read_text()), {
            'argv': ['-I', '-B', '-m', 'pylint', '--rcfile=' + str(rcfile),
                     '--valid-odoo-versions=19.0', '--py-version=3.12',
                     '--persistent=no', '--', str(self.module)], 'bytecode': '1'})
        self.assertEqual(rcfile.read_bytes(), self.before[self.rcfile])
        for path, original in self.before.items():
            if path != self.profile:
                self.assertEqual(path.read_bytes(), original)
        self.assertFalse(self.profile.exists())

    def test_workspace_missing_or_invalid_rcfile_is_local_to_lint(self):
        for declaration in ('', 'lint_rcfile = 42\n', 'lint_rcfile = ""\n'):
            with self.subTest(declaration=declaration):
                if not self.profile.exists():
                    self.profile.write_text('')
                self.use_workspace(declaration)
                self.rejected(('coffee',), 'Declare a nonempty tooling.lint_rcfile without control characters.')
        self.profile.write_text('')
        # Relative to the workspace directory, not to the checkout.
        self.use_workspace("lint_rcfile = 'lint rules/.pylintrc'\n")
        self.rejected(('coffee',), 'Lint rcfile not found: ' + str(self.root.parent / 'lint rules/.pylintrc'))

    def test_addon_and_module_symlink_escape_is_rejected(self):
        outside = self.root / 'not configured'
        outside.mkdir()
        (outside / '__manifest__.py').touch()
        (self.module.parent / 'escaped').symlink_to(outside, target_is_directory=True)
        self.rejected(('escaped',), 'Lint module must stay inside its configured project addon root.')
        self.profile.write_text(self.profile.read_text().replace("addons_paths = ['addons']",
                                                                "addons_paths = ['..']"))
        self.rejected(('coffee',), 'Lint addon roots must stay inside the project.')

    def test_missing_interpreter_fails_without_fallback(self):
        self.python.unlink()
        self.rejected(('coffee',), 'Project Python is not executable: ' + str(self.python))

    def test_wrong_python_nonisolated_environment_and_missing_dependencies(self):
        cases = (({'python': '3.11'}, 'Lint requires the declared Python 3.12.'),
                 ({'prefix': '/base-python'}, 'Lint requires the configured isolated project environment.'),
                 ({'pylint': None}, 'Project environment must provide pylint and pylint-odoo.'),
                 ({'pylint_odoo': None}, 'Project environment must provide pylint and pylint-odoo.'),
                 ({'odoo_versions': ['18.0']}, 'Installed pylint-odoo does not support Odoo 19.0.'))
        for changes, message in cases:
            self.env['PROBE_RESULT'] = json.dumps({**self.metadata, **changes})
            with self.subTest(changes=changes):
                self.rejected(('coffee',), message, probe=True)


if __name__ == '__main__':
    unittest.main()
