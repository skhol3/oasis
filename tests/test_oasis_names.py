"""oasis names in what the harness reads, sets and prints (v0.8.0 S2, S4). Since v0.17.0 (S3) only the
OASIS_* names are read: a legacy ODOO19_* variable is ignored, and the entry point sets none. v0.21.0 (S11)
removed the project wrapper templates (a project's own copy is tests/test_lifecycle.py's).

The lifecycle fixture (fake docker/python, private runtime directory) and the public tools,
run directly with the variables the entry point sets.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

import test_lifecycle as lifecycle

ROOT = lifecycle.STAGE
TOOLS = ROOT / 'tools'
VARIABLES = ('PROJECT_ROOT', 'ENTRYPOINT', 'TOOLS_DIR', 'COMPOSE_LOCK_TIMEOUT', 'RUN_RESULT', 'REUSE_RESULT')
ROOT_ERROR_SHELL = 'OASIS_PROJECT_ROOT must name an existing project directory.\n'
ROOT_ERROR = 'ERROR: OASIS_PROJECT_ROOT must name an absolute existing project directory.\n'
# Python tools that read the project root, with arguments that reach that check.
PYTHON_TOOLS = (('model-info', ('sale.order',)), ('module-info', ('sale',)), ('view-info', ('sale.order',)),
                ('xmlid-info', ('sale.view_order_form',)), ('lint-module', ('coffee',)),
                ('worktree-init', ('feat', 'feature/x', '--dry-run')), ('doctor', ()))


class OasisVariableTests(unittest.TestCase):
    setUp_fixture = lifecycle.LifecycleTests.setUp

    def setUp(self):
        self.setUp_fixture()
        for prefix in ('OASIS_', 'ODOO19_'):
            for name in VARIABLES:
                self.env.pop(prefix + name, None)
        self.wrong = str(self.root / 'absent')

    def tool(self, command, *args, **variables):
        return subprocess.run(['bash', str(TOOLS / command), *args], text=True, cwd=self.root,
                              env={**self.env, **variables}, capture_output=True)

    def observed(self, result):
        return result.returncode, result.stdout, result.stderr

    def test_shell_tools_read_oasis_names_first(self):
        result = self.tool('environment_checks.sh', '--bogus', OASIS_PROJECT_ROOT=str(self.root),
                           OASIS_ENTRYPOINT='/opt/bin/oasis', ODOO19_PROJECT_ROOT=self.wrong,
                           ODOO19_ENTRYPOINT='/opt/old/oasis')
        self.assertEqual(self.observed(result), (2, '', 'Usage: /opt/bin/oasis [--quick|--full]\n'))

    def test_shell_tools_ignore_the_legacy_variable_names(self):
        # v0.17.0 S3: ODOO19_PROJECT_ROOT, ODOO19_ENTRYPOINT and ODOO19_COMPOSE_LOCK_TIMEOUT are not read.
        result = self.tool('environment_checks.sh', '--bogus', ODOO19_PROJECT_ROOT=str(self.root),
                           ODOO19_ENTRYPOINT='/opt/old/oasis')
        self.assertEqual(self.observed(result), (2, '', ROOT_ERROR_SHELL))
        result = self.tool('environment_checks.sh', '--bogus', OASIS_PROJECT_ROOT=str(self.root),
                           ODOO19_ENTRYPOINT='/opt/old/oasis')
        self.assertEqual(self.observed(result), (2, '', f'Usage: {TOOLS / "environment_checks.sh"} [--quick|--full]\n'))
        result = self.tool('environment_checks.sh', '--bogus', OASIS_PROJECT_ROOT=self.wrong,
                           ODOO19_PROJECT_ROOT=str(self.root))
        self.assertEqual(self.observed(result), (2, '', ROOT_ERROR_SHELL))

    def test_shell_tools_name_oasis_project_root_when_neither_is_set(self):
        self.assertEqual(self.observed(self.tool('environment_checks.sh')), (2, '', ROOT_ERROR_SHELL))

    def test_python_tools_name_oasis_project_root_when_neither_is_set(self):
        for command, args in PYTHON_TOOLS:
            with self.subTest(command=command):
                self.assertEqual(self.observed(self.tool(command, *args)), (2, '', ROOT_ERROR))

    def test_python_tools_read_only_oasis_project_root(self):
        for command, args in PYTHON_TOOLS:
            with self.subTest(command=command):
                oasis = self.tool(command, *args, OASIS_PROJECT_ROOT=str(self.root),
                                  ODOO19_PROJECT_ROOT=self.wrong)
                self.assertNotIn('PROJECT_ROOT', oasis.stderr)
                legacy = self.tool(command, *args, ODOO19_PROJECT_ROOT=str(self.root))
                self.assertEqual(self.observed(legacy), (2, '', ROOT_ERROR))
                wins = self.tool(command, *args, OASIS_PROJECT_ROOT=self.wrong,
                                 ODOO19_PROJECT_ROOT=str(self.root))
                self.assertEqual(self.observed(wins), (2, '', ROOT_ERROR))

    def test_doctor_reads_the_project_of_oasis_project_root_only(self):
        result = self.tool('doctor', OASIS_PROJECT_ROOT=str(self.root))
        self.assertEqual(result.stdout.splitlines()[0], 'PASS configuration=workspace')
        self.assertEqual(self.observed(self.tool('doctor', ODOO19_PROJECT_ROOT=str(self.root))), (2, '', ROOT_ERROR))

    def test_python_usage_names_the_oasis_entry_point_first(self):
        for command in ('doctor', 'setup'):
            for variables, program in (
                    ({'OASIS_ENTRYPOINT': '/opt/bin/oasis', 'ODOO19_ENTRYPOINT': '/opt/old/oasis'}, '/opt/bin/oasis'),
                    ({'ODOO19_ENTRYPOINT': '/opt/old/oasis'}, 'oasis'),
                    ({}, 'oasis')):
                with self.subTest(command=command, variables=variables):
                    result = self.tool(command, '--bogus', **variables)
                    self.assertEqual((result.returncode, result.stdout), (2, ''))
                    self.assertEqual(result.stderr.split()[:3], ['Usage:', program, command],
                                     result.stderr)

    def test_run_results_pass_only_under_the_oasis_names(self):
        # RUN_RESULT and REUSE_RESULT pass between test-module --compact and the run it starts;
        # a legacy name in the caller's environment is not read.
        for args, name in ((('coffee',), 'RUN_RESULT'), (('--reuse', 'coffee'), 'REUSE_RESULT')):
            with self.subTest(name=name):
                written = self.root / f'written-{name}'
                result = self.tool('test-module', *args, OASIS_PROJECT_ROOT=str(self.root),
                                   **{f'OASIS_{name}': str(written)})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(written.read_text(), 'yes\n' if name == 'RUN_RESULT' else 'install\n')
                stale = self.root / f'stale-{name}'
                result = self.tool('test-module', *args, OASIS_PROJECT_ROOT=str(self.root),
                                   **{f'ODOO19_{name}': str(stale)})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(stale.exists())


class EntryPointHelpTests(unittest.TestCase):
    """Help that tells the user to run a command names the invoked entry point (S4)."""

    def setUp(self):
        fixture_root = Path(__file__).resolve().parent / 'fixturesroot'
        fixture_root.mkdir(exist_ok=True)
        self.addCleanup(fixture_root.rmdir)
        self.scratch = tempfile.TemporaryDirectory(dir=fixture_root)
        self.addCleanup(self.scratch.cleanup)
        self.project = Path(self.scratch.name)
        (self.project / 'oasis-workspace.toml').write_text('[tooling]\nversion = "19.0"\n')

    def run_help(self, program, *args):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('OASIS_', 'ODOO19_'))}
        return subprocess.run([sys.executable, '-B', str(ROOT / program), *args], text=True,
                              cwd=self.project, env={**env, 'PYTHONDONTWRITEBYTECODE': '1'},
                              capture_output=True)

    def test_gc_hints_name_the_invoked_entry_point(self):
        for program in ('oasis',):
            for command, hint in (
                    ('test-module', f'behind: {program} gc lists such databases and {program} gc --apply drops them.\n'),
                    ('verify-module', f'Ctrl+C; {program} gc drops what a killed run left behind.')):
                with self.subTest(program=program, command=command):
                    result = self.run_help(program, '--project', str(self.project), command, '--help')
                    self.assertEqual((result.returncode, result.stderr), (0, ''))
                    self.assertIn(hint, result.stdout)

    def test_an_entry_point_file_named_odoo19_still_makes_hints_name_oasis(self):
        # v0.17.0 S3: the program a hint names is `oasis`, whatever the entry point's file name.
        for variables in ({'OASIS_ENTRYPOINT': '/opt/old/odoo19'},):
            for command, hint in (
                    ('test-module', 'behind: oasis gc lists such databases and oasis gc --apply drops them.\n'),
                    ('verify-module', 'Ctrl+C; oasis gc drops what a killed run left behind.')):
                with self.subTest(variables=variables, command=command):
                    env = {key: value for key, value in os.environ.items()
                           if not key.startswith(('OASIS_', 'ODOO19_'))}
                    result = subprocess.run(['bash', str(TOOLS / command), '--help'], text=True,
                                            cwd=self.project, capture_output=True,
                                            env={**env, 'PYTHONDONTWRITEBYTECODE': '1',
                                                 'OASIS_PROJECT_ROOT': str(self.project), **variables})
                    self.assertEqual((result.returncode, result.stderr), (0, ''))
                    self.assertIn(hint, result.stdout)
                    self.assertNotIn('odoo19 gc', result.stdout)

    def test_no_help_names_odoo_19_or_a_fixed_odoo19_command(self):
        commands = ('test-module', 'verify-module', 'update-module', 'odoo-shell', 'gc', 'stop',
                    'doctor', 'model-info', 'module-info', 'view-info', 'xmlid-info', 'lint-module',
                    'worktree-init')
        outputs = [self.run_help('oasis', '--help')]
        outputs += [self.run_help('oasis', '--project', str(self.project), command, '--help')
                    for command in commands]
        for command, result in zip(('--help', *commands), outputs):
            with self.subTest(command=command):
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertNotIn('Odoo 19', result.stdout)
                self.assertNotIn('odoo19 ', result.stdout)
                self.assertNotIn('odoo19/<', result.stdout)


if __name__ == '__main__':
    unittest.main()
