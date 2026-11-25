"""check-environment and bootstrap read lock.sha256 from its own directory, then from the project root.

A lock written by `oasis migrate` (or by hand from the requirements directory) lists its files
relative to that directory; a legacy lock lists them relative to the project root (the checkout),
also when the requirements directory lies outside it. The real sha256sum checks them; the rest of
the environment comes from the fake harness of test_environment.
"""
import hashlib
import shutil
import subprocess
import sys
import unittest

import test_environment
import test_lifecycle as lifecycle

CLI = lifecycle.STAGE / 'oasis'
FILES = ('runtime.in', 'runtime.txt', 'dev.in', 'dev.txt')


@unittest.skipUnless(shutil.which('sha256sum'), 'sha256sum is required')
class DependencyLockTests(unittest.TestCase):
    setUp = lifecycle.LifecycleTests.setUp
    prepare = test_environment.EnvironmentTests.prepare

    def requirements(self, outside=False):
        """The prepared requirements directory with the real sha256sum; outside the checkout when asked."""
        requirements = self.prepare()
        (self.bindir / 'sha256sum').unlink()
        if outside:
            shared = self.root.parent / 'config' / 'requirements'
            shared.parent.mkdir()
            requirements.rename(shared)
            profile = self.root / 'oasis-workspace.toml'
            profile.write_text(profile.read_text().replace("requirements = 'dev/requirements'",
                                                           "requirements = '../config/requirements'"))
            requirements = shared
        return requirements

    def write_lock(self, requirements, prefix):
        (requirements / 'lock.sha256').write_text(''.join(
            f'{hashlib.sha256((requirements / name).read_bytes()).hexdigest()}  {prefix}{name}\n' for name in FILES))

    def run_tool(self, *args):
        return subprocess.run([sys.executable, '-B', str(CLI), '--project', str(self.root), *args],
                              text=True, capture_output=True, cwd=self.root, env=self.env)

    def assert_locks(self, expected):
        result = self.run_tool('check-environment', '--quick')
        if expected == 'current':
            self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
            self.assertIn('PASS dependency_locks=current\n', result.stdout)
            self.assertTrue(result.stdout.endswith('environment_failures=0\n'))
        else:
            self.assertEqual(result.returncode, 1)
            self.assertIn('FAIL dependency_locks=stale_or_modified\n', result.stderr)
            self.assertTrue(result.stdout.endswith('environment_failures=1\n'))

    def test_lock_relative_to_its_directory_is_current(self):
        self.write_lock(self.requirements(), '')
        self.assert_locks('current')

    def test_legacy_lock_relative_to_the_project_root_is_current(self):
        self.write_lock(self.requirements(), 'dev/requirements/')
        self.assert_locks('current')

    def test_lock_outside_the_checkout_in_both_forms_is_current(self):
        requirements = self.requirements(outside=True)
        self.write_lock(requirements, '../config/requirements/')
        self.assert_locks('current')
        self.write_lock(requirements, '')
        self.assert_locks('current')

    def test_modified_input_is_stale_in_both_forms(self):
        requirements = self.requirements()
        for prefix in ('', 'dev/requirements/'):
            with self.subTest(prefix=prefix):
                self.write_lock(requirements, prefix)
                (requirements / 'dev.in').write_text('# changed\n')
                self.assert_locks('stale')
                (requirements / 'dev.in').write_text('# fixture\n')

    def test_bootstrap_preview_accepts_a_lock_relative_to_its_directory(self):
        requirements = self.requirements()
        self.write_lock(requirements, '')
        result = self.run_tool('bootstrap', '--preview')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith('mode=preview\n'), result.stdout)
        # v0.14.0 (S9): a stale input is no longer refused; bootstrap plans to compile the locks.
        (requirements / 'dev.in').write_text('# changed\n')
        result = self.run_tool('bootstrap', '--preview')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn('mutation=none\nlocks=stale\n', result.stdout)
        self.assertTrue(result.stdout.endswith('planned_action=compile_locks_then_sync_lock\n'), result.stdout)


if __name__ == '__main__':
    unittest.main()
