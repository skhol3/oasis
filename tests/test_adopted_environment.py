"""Adopted environments and the lock comparison (v0.17.0 S1).

The lock comparison (tools/check_environment.py) normalizes distribution names on both sides (PEP 503:
lowercase, runs of `-`, `_` and `.` become `-`), so `zope.event-5.0.dist-info` satisfies `zope-event==5.0`
on every Python an environment may have (the current one, and 3.9 and 3.8 when `uv python find` has one).

An environment oasis created (bootstrap --apply or setup --apply ran `uv venv`) carries the mark
`<environment>/.oasis-created`; any other environment is adopted. A drift from the locks is FAIL for the first
and `WARN locked_environment=drifted` with the fix `oasis --project <checkout> bootstrap --apply` for an adopted
one, in `doctor --environment --full`, `check-environment --full` and bootstrap's final checks, never counted
as a failure; no check writes the environment.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

import test_audit_dependencies
import test_environment
import test_lifecycle as lifecycle
import test_setup

HELPER = lifecycle.STAGE / 'tools' / 'check_environment.py'
CLI = lifecycle.STAGE / 'oasis'
MARK = '.oasis-created'

LOCK = 'zope-event==5.0\nZope_Interface==5.4.0\npsycopg2==2.9.9\nabsent-pkg==1.0\n'
COMPARED = ('locked_packages=4\nmissing_package=absent-pkg==1.0\n'
            'version_mismatch=psycopg2: expected=2.9.9 actual=2.9.5\nmissing_packages=1\nversion_mismatches=1\n')
# The lock of the environment checks: zope.event is installed as pip names it, psycopg2 at another version.
DRIFT_LOCK = 'zope-event==5.0\npsycopg2==2.9.9\n'
DRIFT = ('locked_packages=2\nversion_mismatch=psycopg2: expected=2.9.9 actual=2.9.5\n'
         'missing_packages=0\nversion_mismatches=1\n')
# The fake environment Python runs the real lock comparison with the host Python on the synthetic site only.
REAL_COMPARISON = '*/check_environment.py) PYTHONPATH="$FAKE_SITE" exec "$FAKE_HOST_PYTHON" -B -S "$@" ;;'


def distribution(site, directory, metadata, name, version):
    path = site / directory
    path.mkdir(parents=True)
    (path / metadata).write_text(f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n')


def write_site(site):
    """zope.event as pip installs it (a dotted dist-info), zope.interface as an egg-info, psycopg2 2.9.5."""
    distribution(site, 'zope.event-5.0.dist-info', 'METADATA', 'zope.event', '5.0')
    distribution(site, 'zope.interface-5.4.0-py3.8.egg-info', 'PKG-INFO', 'zope.interface', '5.4.0')
    distribution(site, 'psycopg2-2.9.5.dist-info', 'METADATA', 'psycopg2', '2.9.5')


def snapshot(directory):
    """Every path below directory with its content (None for a directory)."""
    return {str(path.relative_to(directory)): (None if path.is_dir() else path.read_bytes())
            for path in sorted(directory.rglob('*'))}


class LockComparisonTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix='oasis-locked-'))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.site = self.scratch / 'site'
        write_site(self.site)
        self.lock = self.scratch / 'dev.txt'
        self.lock.write_text(LOCK)

    def compare(self, python):
        # -S: no site-packages, so only the synthetic site directory (PYTHONPATH) is installed.
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONPATH': str(self.site),
               'PYTHONDONTWRITEBYTECODE': '1', 'LC_ALL': 'C.UTF-8'}
        result = subprocess.run([python, '-B', '-S', str(HELPER), str(self.lock)], text=True,
                                capture_output=True, cwd=self.scratch, env=env)
        return result.returncode, result.stdout, result.stderr

    def test_names_are_normalized_on_both_sides_on_the_current_python(self):
        self.assertEqual(self.compare(sys.executable), (1, COMPARED, ''))

    def test_names_are_normalized_on_both_sides_on_python_39_and_38(self):
        for minor in ('3.9', '3.8'):
            with self.subTest(python=minor):
                python = test_audit_dependencies.find_python(minor)
                if python is None:
                    self.skipTest(f'uv python find {minor} found no interpreter')
                self.assertEqual(self.compare(python), (1, COMPARED, ''))

    def test_an_exact_environment_still_passes(self):
        self.lock.write_text('Zope.Event==5.0\nzope-interface==5.4.0\npsycopg2==2.9.5\n')
        self.assertEqual(self.compare(sys.executable),
                         (0, 'locked_packages=3\nmissing_packages=0\nversion_mismatches=0\n', ''))


class AdoptedEnvironmentTests(unittest.TestCase):
    setUp_fixture = lifecycle.LifecycleTests.setUp
    prepare = test_environment.EnvironmentTests.prepare
    running_database = test_environment.EnvironmentTests.running_database
    missing_environment = test_environment.EnvironmentTests.missing_environment

    def setUp(self):
        self.setUp_fixture()
        self.requirements = self.prepare()
        self.running_database()
        (self.requirements / 'dev.txt').write_text(DRIFT_LOCK)
        site = self.root / 'site'
        write_site(site)
        self.env['FAKE_SITE'] = str(site)
        self.python.write_text(self.python.read_text().replace(
            '*/check_environment.py) echo "locked_packages=0"; echo "missing_packages=0"; '
            'echo "version_mismatches=0"; exit 0 ;;', REAL_COMPARISON))
        self.environment = self.python.parent.parent

    def cli(self, *args):
        result = subprocess.run([sys.executable, '-B', str(CLI), '--project', str(self.root), *args], text=True,
                                capture_output=True, cwd=self.root, env=self.env)
        return result.returncode, result.stdout, result.stderr

    def warned(self, environment):
        command = shlex.join(['oasis', '--project', str(self.root), 'bootstrap', '--apply'])
        return (f'{DRIFT}WARN locked_environment=drifted\n'
                f'  fix: {command} (syncs the adopted environment {environment} to the locks: it changes the '
                'packages installed there)\n')

    def test_an_adopted_environment_that_drifted_is_a_warning_and_is_left_as_it_is(self):
        before = snapshot(self.environment)
        for args in (('doctor', '--environment', '--full'), ('check-environment', '--full')):
            with self.subTest(args=args):
                code, stdout, stderr = self.cli(*args)
                self.assertEqual((code, stderr), (0, ''), stdout)
                self.assertIn('PASS package_compatibility=valid\n' + self.warned(self.environment)
                              + 'scope=all\n', stdout)
                self.assertNotIn('locked_environment=exact', stdout)
                self.assertTrue(stdout.endswith('environment_mode=full\nenvironment_failures=0\n'), stdout)
                self.assertEqual(snapshot(self.environment), before)

    def test_an_environment_oasis_created_that_drifted_still_fails(self):
        (self.environment / MARK).write_text('created by oasis\n')
        for args in (('doctor', '--environment', '--full'), ('check-environment', '--full')):
            with self.subTest(args=args):
                code, stdout, stderr = self.cli(*args)
                self.assertEqual((code, stderr), (1, 'FAIL locked_environment=drifted\n'))
                self.assertIn('PASS package_compatibility=valid\n' + DRIFT + 'scope=all\n', stdout)
                self.assertNotIn('WARN', stdout)
                self.assertTrue(stdout.endswith('environment_mode=full\nenvironment_failures=1\n'), stdout)

    def test_an_unreadable_lock_still_fails_for_an_adopted_environment(self):
        (self.requirements / 'dev.txt').write_text('# no pins\n')
        code, stdout, stderr = self.cli('doctor', '--environment', '--full')
        self.assertEqual(code, 1)
        self.assertEqual(stderr, f'ERROR: Lockfile contains no pinned packages: {self.requirements / "dev.txt"}\n'
                                 'FAIL locked_environment=drifted\n')
        self.assertNotIn('WARN', stdout)
        self.assertTrue(stdout.endswith('environment_failures=1\n'), stdout)

    def test_an_exact_adopted_environment_passes(self):
        (self.requirements / 'dev.txt').write_text('zope-event==5.0\npsycopg2==2.9.5\n')
        code, stdout, stderr = self.cli('doctor', '--environment', '--full')
        self.assertEqual((code, stderr), (0, ''), stdout)
        self.assertIn('locked_packages=2\nmissing_packages=0\nversion_mismatches=0\nPASS locked_environment=exact\n',
                      stdout)

    def test_bootstrap_apply_syncs_an_adopted_environment_without_marking_it_and_warns_of_a_drift(self):
        code, stdout, stderr = self.cli('bootstrap', '--apply')
        self.assertEqual((code, stderr), (0, ''), stdout)
        self.assertIn('mutation=isolated_project_virtualenv\n', stdout)
        self.assertIn(self.warned(self.environment), stdout)
        self.assertTrue(stdout.endswith('environment_mode=full\nenvironment_failures=0\n'), stdout)
        self.assertIn(f'uv pip sync --python {self.python}', self.commands.read_text())
        self.assertFalse((self.environment / MARK).exists())

    def test_bootstrap_apply_marks_the_environment_it_creates_and_fails_its_drift(self):
        environment = self.missing_environment()
        template = self.root / 'fake-python-template'
        template.write_text(template.read_text().replace(
            "*/check_environment.py) printf 'locked_packages=0\\nmissing_packages=0\\nversion_mismatches=0\\n'; "
            'exit 0 ;;', REAL_COMPARISON))
        code, stdout, stderr = self.cli('bootstrap', '--apply')
        self.assertEqual((code, stderr), (1, 'FAIL locked_environment=drifted\n'), stdout)
        self.assertIn('PASS package_compatibility=valid\n' + DRIFT + 'scope=all\n', stdout)
        self.assertTrue(stdout.endswith('environment_failures=1\n'), stdout)
        self.assertTrue((environment / MARK).is_file())


class SetupMarkTests(unittest.TestCase):
    setUp = test_setup.SetupTests.setUp
    git = test_setup.SetupTests.git
    odoo_source = test_setup.SetupTests.odoo_source
    module = test_setup.SetupTests.module
    setup_cmd = test_setup.SetupTests.setup_cmd
    existing_environment = test_setup.SetupTests.existing_environment

    def test_setup_marks_the_environment_it_creates(self):
        result = self.setup_cmd('--apply', '--community', str(self.source), '--no-enterprise')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertTrue((self.checkout / '.oasis/venv' / MARK).is_file())

    def test_setup_never_marks_an_adopted_environment(self):
        environment = self.existing_environment('shop', '3.12.3')
        result = self.setup_cmd('--apply', '--environment', str(environment), '--community', str(self.source),
                                '--no-enterprise')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertFalse((environment / MARK).exists())


if __name__ == '__main__':
    unittest.main()
