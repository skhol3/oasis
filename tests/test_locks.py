"""tools/locks.py: why bootstrap compiles the locks, and the lock.sha256 it writes (S9).

Each test builds a requirements directory in a fresh temporary directory; bootstrap's use of
these commands is covered in test_environment.
"""
from pathlib import Path
import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest

LOCKS = Path(__file__).resolve().parents[1] / 'tools/locks.py'
FILES = ('runtime.in', 'runtime.txt', 'dev.in', 'dev.txt')


class LocksTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix='oasis-locks-')
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name) / 'checkout'
        self.requirements = self.root / 'dev/requirements'
        self.requirements.mkdir(parents=True)
        for name in FILES:
            (self.requirements / name).write_text(f'# {name}\n')

    def run_locks(self, *args):
        return subprocess.run([sys.executable, '-I', '-B', str(LOCKS), *map(str, args)],
                              text=True, capture_output=True)

    def write_lock(self, prefix=''):
        (self.requirements / 'lock.sha256').write_text(''.join(
            f'{hashlib.sha256((self.requirements / name).read_bytes()).hexdigest()}  {prefix}{name}\n'
            for name in FILES))

    def assert_state(self, expected):
        result = self.run_locks('state', self.requirements, self.root)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected + '\n', ''))

    def test_a_missing_lock_or_fingerprint_is_missing(self):
        self.write_lock()
        for name in ('runtime.txt', 'dev.txt', 'lock.sha256'):
            with self.subTest(name=name):
                saved = (self.requirements / name).read_bytes()
                (self.requirements / name).unlink()
                self.assert_state('missing')
                (self.requirements / name).write_bytes(saved)

    def test_a_changed_input_is_stale_in_both_forms_of_the_fingerprint(self):
        for prefix in ('', 'dev/requirements/'):
            for name in ('runtime.in', 'dev.in'):
                with self.subTest(prefix=prefix, name=name):
                    self.write_lock(prefix)
                    (self.requirements / name).write_text('# changed\n')
                    self.assert_state('stale')
                    (self.requirements / name).write_text(f'# {name}\n')

    def test_an_unreadable_fingerprint_is_stale(self):
        (self.requirements / 'lock.sha256').write_text('# not a fingerprint\n')
        self.assert_state('stale')

    def test_a_lock_changed_under_current_inputs_is_edited_in_both_forms(self):
        for prefix in ('', 'dev/requirements/'):
            with self.subTest(prefix=prefix):
                self.write_lock(prefix)
                (self.requirements / 'dev.txt').write_text('pylint==3.0.0\n')
                self.assert_state('edited')
                (self.requirements / 'dev.txt').write_text('# dev.txt\n')

    def test_fingerprint_writes_what_sha256sum_writes_and_leaves_the_inputs_alone(self):
        inputs = {name: (self.requirements / name).read_bytes() for name in ('runtime.in', 'dev.in')}
        result = self.run_locks('fingerprint', self.requirements)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        expected = ''.join(
            f'{hashlib.sha256((self.requirements / name).read_bytes()).hexdigest()}  {name}\n'
            for name in FILES)
        self.assertEqual((self.requirements / 'lock.sha256').read_text(), expected)
        if shutil.which('sha256sum'):
            check = subprocess.run(['sha256sum', *FILES], cwd=self.requirements, text=True,
                                   capture_output=True)
            self.assertEqual((check.returncode, check.stdout), (0, expected))
        self.assertEqual({name: (self.requirements / name).read_bytes() for name in inputs}, inputs)

    def test_usage(self):
        result = self.run_locks('compile', self.requirements)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            2, '', 'Usage: locks.py state <requirements dir> <project root> | '
                   'fingerprint <requirements dir>\n'))


if __name__ == '__main__':
    unittest.main()
