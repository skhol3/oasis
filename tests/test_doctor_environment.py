"""`doctor --environment [--quick|--full]` runs the environment checks, and `check-environment` is its
deprecated alias (v0.16.0 S5): the same lines, exit codes and commands, through both entry points.

The fake harness of test_environment (fake uv, sha256sum, docker and environment Python) decides every
check; the command log (FAKE_LOG) records what each run executed, compared too.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_environment
import test_lifecycle as lifecycle

ROOT = lifecycle.STAGE
PROGRAMS = ('oasis',)
MODES = ((), ('--quick',), ('--full',))


class DoctorEnvironmentTests(unittest.TestCase):
    setUp = lifecycle.LifecycleTests.setUp
    prepare = test_environment.EnvironmentTests.prepare
    running_database = test_environment.EnvironmentTests.running_database
    expected_quick_output = test_environment.EnvironmentTests.expected_quick_output

    def cli(self, program, *args, project=None):
        """The entry point with --project; the observed exit code, stdout, stderr and command log."""
        self.commands.unlink(missing_ok=True)
        result = subprocess.run([sys.executable, '-B', str(ROOT / program), '--project', str(project or self.root),
                                 *args], text=True, capture_output=True, cwd=self.root, env=self.env)
        log = self.commands.read_text() if self.commands.exists() else ''
        return result.returncode, result.stdout, result.stderr, log

    def assert_same(self, *modes):
        """doctor --environment <mode> observes exactly what check-environment <mode> does; returns the latter."""
        observed = {}
        for program in PROGRAMS:
            for mode in modes:
                with self.subTest(program=program, mode=mode):
                    alias = self.cli(program, 'check-environment', *mode)
                    observed[program, mode] = alias
                    self.assertEqual(self.cli(program, 'doctor', '--environment', *mode), alias)
        return observed

    def test_quick_checks_are_the_same_lines_as_check_environment(self):
        self.prepare()
        observed = self.assert_same((), ('--quick',))
        # The alias still prints exactly today's report.
        self.assertEqual(observed['oasis', ()][:3], (0, self.expected_quick_output(), ''))
        self.assertEqual(observed['oasis', ('--quick',)][:3], (0, self.expected_quick_output(), ''))

    def test_failures_and_the_python_mismatch_keep_their_exit_codes(self):
        self.prepare()
        self.env['FAKE_LOCK_STATUS'] = '1'
        observed = self.assert_same(*MODES)
        self.assertEqual(observed['oasis', ()][0], 1)
        self.assertEqual(observed['oasis', ()][2], 'FAIL dependency_locks=stale_or_modified\n')
        self.env['FAKE_LOCK_STATUS'] = '0'
        self.python.write_text(self.python.read_text().replace('echo 3.12', 'echo 3.11'))
        observed = self.assert_same(*MODES)
        self.assertEqual(observed['oasis', ()][:3], (2, '', (
            'Python 3.12 is required; found 3.11.\n'
            f'Move {self.python.parent.parent} away and run oasis bootstrap --apply to recreate it with Python 3.12.\n')))

    def test_full_checks_are_the_same_lines_as_check_environment(self):
        self.prepare()
        self.running_database()
        (self.root / 'dev/compose.yml').write_text("name: cc-shop\nservices:\n  db:\n    image: postgres:17\n"
                                                   "    ports:\n      - '127.0.0.1:6001:5432'\n")
        (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text('db_host = 127.0.0.1\ndb_port = 6001\n'))
        observed = self.assert_same(('--full',))
        code, stdout, stderr, log = observed['oasis', ('--full',)]
        self.assertEqual((code, stderr), (0, ''), stdout)
        self.assertTrue(stdout.endswith('PASS postgres_connection=ready\nenvironment_mode=full\n'
                                        'environment_failures=0\n'), stdout)
        self.assertIn('uv pip check', log)
        self.env['FAKE_CONNECTION'] = 'authentication_failed'
        observed = self.assert_same(('--full',))
        code, _stdout, stderr, _log = observed['oasis', ('--full',)]
        self.assertEqual(code, 1)
        command = shlex.join(['oasis', '--project', str(self.root), 'recreate-postgres-volume', '--confirm', 'cc-shop'])
        self.assertIn(command, stderr)

    def test_a_stopped_database_service_names_start_database(self):
        # v0.16.0 S6: the fix is the oasis command, which names no env file (a harness may refuse one that does).
        self.prepare()
        observed = self.assert_same(('--full',))
        for program in PROGRAMS:
            code, _stdout, stderr, _log = observed[program, ('--full',)]
            start = shlex.join([program, '--project', str(self.root), 'setup-postgres'])
            self.assertEqual(code, 1)
            self.assertIn(f'FAIL postgres_service=not_running\n  fix: {start}\n', stderr)
            self.assertNotIn(str(self.root / 'dev/.env'), stderr)

    def test_usage_errors_name_doctor_and_run_nothing(self):
        self.prepare()
        for program in PROGRAMS:
            usage = f'Usage: {(ROOT / program).resolve()} doctor [--environment [--quick|--full]]\n'
            for args in (('--bogus',), ('--quick',), ('--full',), ('--environment', '--bogus'),
                         ('--environment', '--quick', '--full'), ('--environment', '--environment')):
                with self.subTest(program=program, args=args):
                    self.assertEqual(self.cli(program, 'doctor', *args), (2, '', usage, ''))
            # The alias keeps its own usage line, byte for byte.
            with self.subTest(program=program, alias=True):
                self.assertEqual(self.cli(program, 'check-environment', '--bogus'),
                                 (2, '', f'Usage: {(ROOT / program).resolve()} [--quick|--full]\n', ''))

    def test_help_names_the_environment_checks_and_the_deprecated_alias(self):
        self.prepare()
        code, stdout, stderr, _log = self.cli('oasis', 'doctor', '--help')
        self.assertEqual((code, stderr), (0, ''))
        self.assertTrue(stdout.startswith(f'Usage: {ROOT / "oasis"} doctor [--environment [--quick|--full]]\n'), stdout)
        text = ' '.join(stdout.split())
        self.assertIn('--environment runs the environment checks instead', text)
        self.assertIn('check-environment [--quick|--full] is a deprecated alias of doctor --environment', text)
        for program in PROGRAMS:
            with self.subTest(program=program):
                result = subprocess.run([sys.executable, '-B', str(ROOT / program), '--help'], text=True,
                                        capture_output=True, env=self.env)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                # v0.20.0 S13: the aliases of setup-postgres and recreate-postgres-volume follow it.
                self.assertIn('Deprecated aliases (they keep working): check-environment runs doctor --environment, ',
                              result.stdout)

    def test_refused_where_check_environment_is_refused(self):
        with tempfile.TemporaryDirectory(dir=self.scratch.name) as plain:
            for program in PROGRAMS:
                with self.subTest(program=program, where='no workspace file'):
                    alias = self.cli(program, 'check-environment', project=plain)
                    self.assertEqual(alias[0], 2)
                    self.assertIn('Missing tooling configuration', alias[2])
                    self.assertEqual(self.cli(program, 'doctor', '--environment', project=plain), alias)
                    # doctor itself still runs there (one FAIL configuration).
                    self.assertTrue(self.cli(program, 'doctor', project=plain)[1].startswith('FAIL configuration='))

    def test_the_docs_mark_the_alias_deprecated_and_say_which_setup_command_to_use(self):
        readme = ' '.join((ROOT / 'README.md').read_text(encoding='utf-8').split())
        self.assertIn('Contract note in v0.16.0 (S5): `check-environment [--quick|--full]` is a deprecated alias of '
                      '`doctor --environment [--quick|--full]`.', readme)
        guide = (ROOT / 'docs/checking-environment.md').read_text(encoding='utf-8')
        self.assertIn('\n## check-environment, a deprecated alias\n', guide)
        setup = (ROOT / 'docs/setup.md').read_text(encoding='utf-8')
        self.assertIn('\n## setup or bootstrap\n', setup)
        self.assertIn('neither is an alias of the other\n(v0.16.0 S5)', setup)


if __name__ == '__main__':
    unittest.main()
