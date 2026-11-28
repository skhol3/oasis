"""bootstrap --apply exits with the result of its own work, the locks and the sync (v0.20.0 S4).

It ends with `doctor --environment --full` (check-environment --full); a failure there, such as
PostgreSQL not running yet, is printed as the doctor's results with the command to run next, and
the exit stays 0 once the sync succeeded. A failure of bootstrap's own work keeps its exit code, and so does
the doctor's `FAIL locked_environment=drifted` for the environment bootstrap just synced: the sync did not
produce the locked environment (exit 1, nothing added, as before). Exit 0 needs a doctor that completed: exit 1
and its `environment_failures=<n>` summary on stdout; a doctor that did not run or died (127, a traceback, a
signal) keeps its exit with one stderr line saying so.
The fixture harness is test_environment's: fake uv, docker and environment Python.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import shlex
import unittest
from pathlib import Path

import test_environment
import test_lifecycle as lifecycle


class BootstrapExitTests(unittest.TestCase):
    setUp = lifecycle.LifecycleTests.setUp
    invoke = lifecycle.LifecycleTests.invoke
    prepare = test_environment.EnvironmentTests.prepare
    running_database = test_environment.EnvironmentTests.running_database
    expected_apply_output = test_environment.EnvironmentTests.expected_apply_output

    def command(self, *args):
        return shlex.join(['oasis', '--project', str(self.root), *args])

    def drifted_created_environment(self):
        """The prepared environment, marked as created by oasis, whose lock comparison reports a drift (exit 3)."""
        (self.python.parent.parent / '.oasis-created').write_text('created by oasis\n')
        self.python.write_text(self.python.read_text().replace(
            '*/check_environment.py) echo "locked_packages=0"; echo "missing_packages=0"; '
            'echo "version_mismatches=0"; exit 0 ;;',
            '*/check_environment.py) echo "locked_packages=1"; echo "version_mismatch=psycopg2: expected=2.9.9 '
            'actual=2.9.5"; echo "missing_packages=0"; echo "version_mismatches=1"; exit 3 ;;'))

    def fake_doctor(self, script):
        """The tools with check-environment (the trailing doctor) replaced by script: links to the others."""
        tools = Path(self.scratch.name) / 'tools'
        tools.mkdir()
        for entry in (lifecycle.STAGE / 'tools').iterdir():
            if entry.name not in ('check-environment', '__pycache__'):
                (tools / entry.name).symlink_to(entry)
        doctor = tools / 'check-environment'
        doctor.write_text('#!/bin/sh\n' + script)
        doctor.chmod(0o755)
        self.env['OASIS_TOOLS_DIR'] = str(tools)

    def header(self):
        return (f'mode=apply\nproject=a project\nenvironment={self.python.parent.parent}\n'
                'lockfile=dev/requirements/dev.txt\nmutation=isolated_project_virtualenv\n')

    def incomplete(self, code, cause='no environment_failures= summary line'):
        return (f'doctor=incomplete exit={code}: the trailing doctor --environment --full did not complete ({cause}); '
                f'the sync succeeded; run {self.command("doctor", "--environment", "--full")}\n')

    def test_a_doctor_that_did_not_run_keeps_its_exit_127(self):
        self.prepare()
        self.running_database()
        self.fake_doctor('exit 127\n')
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (127, self.header(), self.incomplete(127)))
        self.assertIn(f'uv pip sync --python {self.python}', self.commands.read_text())

    def test_a_doctor_that_crashed_without_its_summary_keeps_exit_1(self):
        self.prepare()
        self.running_database()
        self.fake_doctor('echo "PASS file:dev/requirements/runtime.in"\n'
                         'echo "Traceback (most recent call last):" >&2\n'
                         'echo "KeyError: \'python\'" >&2\nexit 1\n')
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            1, self.header() + 'PASS file:dev/requirements/runtime.in\n',
            "Traceback (most recent call last):\nKeyError: 'python'\n" + self.incomplete(1)))

    def test_a_doctor_killed_by_a_signal_keeps_exit_143(self):
        self.prepare()
        self.running_database()
        self.fake_doctor('echo "PASS file:dev/requirements/runtime.in"\nkill -TERM $$\n')
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            143, self.header() + 'PASS file:dev/requirements/runtime.in\n', self.incomplete(143)))

    def test_a_summary_with_an_exit_other_than_1_is_not_a_completed_doctor(self):
        self.prepare()
        self.running_database()
        self.fake_doctor('echo "environment_failures=1"\nexit 2\n')
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, self.header() + 'environment_failures=1\n',
                          self.incomplete(2, 'it printed its summary but exited 2, not a check result')))

    def drifted_output(self, failures):
        return self.expected_apply_output(self.python.parent.parent).replace(
            'locked_packages=0\nmissing_packages=0\nversion_mismatches=0\nPASS locked_environment=exact\n',
            'locked_packages=1\nversion_mismatch=psycopg2: expected=2.9.9 actual=2.9.5\nmissing_packages=0\n'
            'version_mismatches=1\n').replace('environment_failures=0\n', f'environment_failures={failures}\n')

    def test_a_failed_trailing_doctor_is_reported_as_such_and_the_synced_apply_exits_0(self):
        # The field run: PostgreSQL is not running yet, the sync itself succeeded.
        self.prepare()
        result = self.invoke('bootstrap', '--apply')
        environment = self.python.parent.parent
        doctor = self.expected_apply_output(environment).replace(
            'PASS postgres_service=running\nPASS postgres_connection=ready\n', '').replace(
            'environment_failures=0\n', 'environment_failures=1\n')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            0,
            doctor + 'sync=succeeded\n'
            'doctor=failed exit=1: the checks above are the results of the trailing doctor --environment '
            '--full; the sync succeeded\n'
            f'  next: fix what they report (their fix: lines), then run '
            f'{self.command("doctor", "--environment", "--full")}\n',
            'FAIL postgres_service=not_running\n'
            f'  fix: {self.command("setup-postgres")}\n'))
        self.assertIn(f'uv pip sync --python {self.python}', self.commands.read_text())
        self.assertTrue((self.root / 'logs/main/bootstrap-before.txt').is_file())

    def test_a_drift_of_the_environment_bootstrap_created_and_synced_keeps_exit_1(self):
        # Right after its own sync, a marked environment that still drifts is bootstrap's own result.
        self.prepare()
        self.running_database()
        self.drifted_created_environment()
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (1, self.drifted_output(1), 'FAIL locked_environment=drifted\n'))
        self.assertIn(f'uv pip sync --python {self.python}', self.commands.read_text())

    def test_a_drift_with_postgresql_not_running_keeps_exit_1_and_adds_no_doctor_lines(self):
        self.prepare()
        self.drifted_created_environment()
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            1, self.drifted_output(2).replace('PASS postgres_service=running\nPASS postgres_connection=ready\n', ''),
            'FAIL locked_environment=drifted\nFAIL postgres_service=not_running\n'
            f'  fix: {self.command("setup-postgres")}\n'))

    def test_a_passing_trailing_doctor_keeps_the_output_and_exit_0(self):
        self.prepare()
        self.running_database()
        result = self.invoke('bootstrap', '--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.expected_apply_output(self.python.parent.parent), ''))

    def test_a_failed_sync_keeps_its_exit_code_and_runs_no_doctor(self):
        self.prepare()
        self.running_database()
        uv = self.bindir / 'uv'
        uv.write_text(uv.read_text() + 'if [ "$1 $2" = "pip sync" ]; then echo "error: sync broke" >&2; exit 3; fi\n')
        result = self.invoke('bootstrap', '--apply')
        environment = self.python.parent.parent
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            3, f'mode=apply\nproject=a project\nenvironment={environment}\n'
               'lockfile=dev/requirements/dev.txt\nmutation=isolated_project_virtualenv\n',
            'error: sync broke\n'))
        self.assertNotIn('environment_failures', result.stdout)


if __name__ == '__main__':
    unittest.main()
