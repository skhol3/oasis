"""Adopted environments and the lock comparison (v0.17.0 S1).

The lock comparison (tools/check_environment.py) normalizes distribution names on both sides (PEP 503:
lowercase, runs of `-`, `_` and `.` become `-`), so `zope.event-5.0.dist-info` satisfies `zope-event==5.0`
on every Python an environment may have (the current one, and 3.9 and 3.8 when `uv python find` has one). A drift
exits 3 (DRIFT_EXIT), apart from a crash (a traceback exits 1) and an unreadable lock (2); a dist-info or egg-info
without usable metadata (no name or version, or undecodable) is left out, never a crash.

An environment oasis created (bootstrap --apply or setup --apply ran `uv venv`) carries the mark
`<environment>/.oasis-created`; any other environment is adopted. A drift from the locks is FAIL for the first
and `WARN locked_environment=drifted` with the fix `oasis --project <checkout> bootstrap --apply` for an adopted
one, in `doctor --environment --full` and bootstrap's final checks, never counted
as a failure; no check writes the environment.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import importlib.util
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

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
# The exit status of check_environment.py for a drift: 1 is a crash (an uncaught exception), 2 an unreadable lock.
DRIFT_EXIT = 3


def distribution(site, directory, metadata, name, version):
    path = site / directory
    path.mkdir(parents=True)
    (path / metadata).write_text(f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n')


def write_site(site):
    """zope.event as pip installs it (a dotted dist-info), zope.interface as an egg-info, psycopg2 2.9.5."""
    distribution(site, 'zope.event-5.0.dist-info', 'METADATA', 'zope.event', '5.0')
    distribution(site, 'zope.interface-5.4.0-py3.8.egg-info', 'PKG-INFO', 'zope.interface', '5.4.0')
    distribution(site, 'psycopg2-2.9.5.dist-info', 'METADATA', 'psycopg2', '2.9.5')


def write_broken_site(site):
    """Next to the site of write_site: a dist-info without METADATA, an egg-info without PKG-INFO, one whose
    metadata has no Version, and one whose METADATA is not UTF-8. None of them counts as installed."""
    (site / 'nometa-1.0.dist-info').mkdir()
    (site / 'noinfo-1.0-py3.8.egg-info').mkdir()
    (site / 'noversion-1.0.dist-info').mkdir()
    (site / 'noversion-1.0.dist-info/METADATA').write_text('Metadata-Version: 2.1\nName: noversion\n')
    (site / 'undecodable-1.0.dist-info').mkdir()
    (site / 'undecodable-1.0.dist-info/METADATA').write_bytes(b'\xff\xfeName: undecodable\nVersion: 1.0\n')


BROKEN_LOCK = LOCK + 'nometa==1.0\nnoinfo==1.0\nnoversion==1.0\nundecodable==1.0\n'
BROKEN_COMPARED = ('locked_packages=8\nmissing_package=absent-pkg==1.0\nmissing_package=noinfo==1.0\n'
                   'missing_package=nometa==1.0\nmissing_package=noversion==1.0\nmissing_package=undecodable==1.0\n'
                   'version_mismatch=psycopg2: expected=2.9.9 actual=2.9.5\nmissing_packages=5\nversion_mismatches=1\n')


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
        self.assertEqual(self.compare(sys.executable), (DRIFT_EXIT, COMPARED, ''))

    def test_names_are_normalized_on_both_sides_on_python_39_and_38(self):
        for minor in ('3.9', '3.8'):
            with self.subTest(python=minor):
                python = test_audit_dependencies.find_python(minor)
                if python is None:
                    self.skipTest(f'uv python find {minor} found no interpreter')
                self.assertEqual(self.compare(python), (DRIFT_EXIT, COMPARED, ''))

    def test_a_distribution_without_usable_metadata_is_left_out_on_the_current_python(self):
        write_broken_site(self.site)
        self.lock.write_text(BROKEN_LOCK)
        self.assertEqual(self.compare(sys.executable), (DRIFT_EXIT, BROKEN_COMPARED, ''))

    def test_a_distribution_without_usable_metadata_is_left_out_on_python_39_and_38(self):
        write_broken_site(self.site)
        self.lock.write_text(BROKEN_LOCK)
        for minor in ('3.9', '3.8'):
            with self.subTest(python=minor):
                python = test_audit_dependencies.find_python(minor)
                if python is None:
                    self.skipTest(f'uv python find {minor} found no interpreter')
                self.assertEqual(self.compare(python), (DRIFT_EXIT, BROKEN_COMPARED, ''))

    def test_metadata_that_is_missing_or_cannot_be_read_is_left_out(self):
        # What importlib.metadata may give for a distribution without metadata on some Pythons: None, or an error
        # when it is read (the TypeError of email.message_from_string(None)).
        spec = importlib.util.spec_from_file_location('oasis_check_environment_under_test', HELPER)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)

        class Distribution:
            def __init__(self, metadata):
                self._metadata = metadata

            @property
            def metadata(self):
                if isinstance(self._metadata, Exception):
                    raise self._metadata
                return self._metadata

        found = [Distribution(None), Distribution(TypeError('initial_value must be str or None, not NoneType')),
                 Distribution(UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'invalid start byte')),
                 Distribution({'Name': 'Zope.Event', 'Version': '5.0'}), Distribution({'Name': 'nover'})]
        with unittest.mock.patch.object(helper, 'distributions', return_value=found):
            self.assertEqual(helper.installed_versions(), {'zope-event': '5.0'})

    def test_a_drift_and_a_crash_have_distinct_exit_codes(self):
        self.assertEqual(self.compare(sys.executable)[0], DRIFT_EXIT)
        # An uncaught exception exits 1, never the drift's code: a sitecustomize that breaks distributions().
        (self.site / 'sitecustomize.py').write_text(
            'import importlib.metadata\n'
            'def broken():\n'
            '    raise RuntimeError("broken site")\n'
            'importlib.metadata.distributions = broken\n')
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONPATH': str(self.site),
               'PYTHONDONTWRITEBYTECODE': '1', 'LC_ALL': 'C.UTF-8'}
        result = subprocess.run([sys.executable, '-B', '-c',
                                 'import sitecustomize, runpy, sys; sys.argv = sys.argv[1:]; '
                                 'runpy.run_path(sys.argv[0], run_name="__main__")', str(HELPER), str(self.lock)],
                                text=True, capture_output=True, cwd=self.scratch, env=env)
        self.assertEqual((result.returncode, result.stdout), (1, ''))
        self.assertIn('RuntimeError: broken site', result.stderr)

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
        for args in (('doctor', '--environment', '--full'),):
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
        for args in (('doctor', '--environment', '--full'),):
            with self.subTest(args=args):
                code, stdout, stderr = self.cli(*args)
                self.assertEqual((code, stderr), (1, 'FAIL locked_environment=drifted\n'))
                self.assertIn('PASS package_compatibility=valid\n' + DRIFT + 'scope=all\n', stdout)
                self.assertNotIn('WARN', stdout)
                self.assertTrue(stdout.endswith('environment_mode=full\nenvironment_failures=1\n'), stdout)

    def test_a_crash_of_the_comparison_fails_for_an_adopted_environment(self):
        # A traceback (exit 1) is no drift: FAIL, never the WARN of an adopted environment.
        self.python.write_text(self.python.read_text().replace(REAL_COMPARISON, (
            "*/check_environment.py) echo 'Traceback (most recent call last):' >&2; "
            "echo 'TypeError: broken' >&2; exit 1 ;;")))
        for args in (('doctor', '--environment', '--full'),):
            with self.subTest(args=args):
                code, stdout, stderr = self.cli(*args)
                self.assertEqual((code, stderr), (1, 'Traceback (most recent call last):\nTypeError: broken\n'
                                                     'FAIL locked_environment=drifted\n'))
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

    def test_bootstrap_apply_warns_when_it_cannot_mark_the_environment_it_creates(self):
        # The mark is written right after `uv venv`; when it cannot be (here a directory is in its place), bootstrap
        # warns and goes on: the environment is reported as adopted.
        environment = self.missing_environment()
        template = self.root / 'fake-python-template'
        template.write_text(template.read_text().replace(
            "*/check_environment.py) printf 'locked_packages=0\\nmissing_packages=0\\nversion_mismatches=0\\n'; "
            'exit 0 ;;', REAL_COMPARISON))
        uv = self.bindir / 'uv'
        uv.write_text(uv.read_text().replace('    chmod +x "$FAKE_PYTHON" ;;',
                                             '    chmod +x "$FAKE_PYTHON"\n    mkdir "$FAKE_ENV/.oasis-created" ;;'))
        code, stdout, stderr = self.cli('bootstrap', '--apply')
        self.assertEqual((code, stderr), (0, mark_warning(environment)), stdout)
        self.assertIn(self.warned(environment), stdout)
        self.assertTrue(stdout.endswith('environment_mode=full\nenvironment_failures=0\n'), stdout)
        self.assertIn(f'uv pip sync --python {self.python}', self.commands.read_text())
        self.assertEqual(list((environment / MARK).iterdir()), [])

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


def mark_warning(environment):
    """What bootstrap --apply and setup --apply print when the mark cannot be written (here: a directory)."""
    return (f'WARNING: cannot mark {environment} as created by oasis ({environment / MARK}: Is a directory): its '
            'drift from the locks is reported as a WARN, as for an adopted environment; create that file to have it '
            'reported as a FAIL.\n')


class SetupMarkTests(unittest.TestCase):
    setUp = test_setup.SetupTests.setUp
    git = test_setup.SetupTests.git
    odoo_source = test_setup.SetupTests.odoo_source
    module = test_setup.SetupTests.module
    setup_cmd = test_setup.SetupTests.setup_cmd
    existing_environment = test_setup.SetupTests.existing_environment

    def test_setup_marks_the_environment_it_creates(self):
        result = self.setup_cmd('--apply', '--community', str(self.source), '--no-enterprise', *test_setup.CREATE)
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertTrue((self.checkout / '.oasis/venv' / MARK).is_file())

    def test_setup_warns_when_it_cannot_mark_the_environment_it_creates(self):
        uv = self.bindir / 'uv'
        uv.write_text(uv.read_text().replace('    chmod +x "$4/bin/python" ;;',
                                             '    chmod +x "$4/bin/python"\n    mkdir "$4/.oasis-created" ;;'))
        result = self.setup_cmd('--apply', '--community', str(self.source), '--no-enterprise', *test_setup.CREATE)
        environment = self.checkout / '.oasis/venv'
        self.assertEqual((result.returncode, result.stderr), (0, mark_warning(environment)), result.stdout)
        self.assertIn(f'created the environment {environment}\n', result.stdout)
        self.assertIn('uv pip sync', self.log.read_text())
        self.assertEqual(list((environment / MARK).iterdir()), [])

    def test_setup_never_marks_an_adopted_environment(self):
        environment = self.existing_environment('shop', '3.12.3')
        result = self.setup_cmd('--apply', '--environment', str(environment), '--community', str(self.source),
                                '--no-enterprise')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertFalse((environment / MARK).exists())


if __name__ == '__main__':
    unittest.main()
