"""tools/locks.py: why bootstrap compiles the locks, and the lock.sha256 it writes (S9).

Each test builds a requirements directory in a fresh temporary directory; bootstrap's use of
these commands is covered in test_environment.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
from pathlib import Path
import hashlib
import importlib.util
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

    def run_locks(self, *args, env=None):
        return subprocess.run([sys.executable, '-I', '-B', str(LOCKS), *map(str, args)],
                              text=True, capture_output=True, env=env)

    def fake_uv(self):
        """A PATH whose only program is a fake uv: it records its arguments and directory and writes
        `<lock>` for `pip compile ... -o <lock>` (with an echo on stdout, which compile drops)."""
        bindir = self.root.parent / 'bin'
        bindir.mkdir()
        (bindir / 'uv').write_text('#!/bin/sh\nprintf "%s (in %s)\\n" "$*" "$PWD" >> "$FAKE_LOG"\n'
                                   'for last; do :; done\nprintf "# compiled\\n" > "$last"\necho "# echo of the lock"\n')
        (bindir / 'uv').chmod(0o755)
        return {'PATH': str(bindir), 'FAKE_LOG': str(self.root.parent / 'uv.log')}

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
                   'fingerprint <requirements dir> | compile <requirements dir> <python> <command to rerun>\n'))

    def test_compile_writes_both_locks_then_the_fingerprint(self):
        # review-f6708244dde86835 R3-locks-compile-subcommand-untested-directly.
        (self.requirements / 'runtime.txt').unlink()
        (self.requirements / 'dev.txt').unlink()
        inputs = {name: (self.requirements / name).read_bytes() for name in ('runtime.in', 'dev.in')}
        env = self.fake_uv()
        result = self.run_locks('compile', self.requirements, '3.12', 'oasis bootstrap --apply', env=env)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(Path(env['FAKE_LOG']).read_text().splitlines(), [
            f'pip compile --python-version 3.12 runtime.in -o runtime.txt (in {self.requirements})',
            f'pip compile --python-version 3.12 dev.in -o dev.txt (in {self.requirements})'])
        for name in ('runtime.txt', 'dev.txt'):
            self.assertEqual((self.requirements / name).read_text(), '# compiled\n')
        self.assertEqual((self.requirements / 'lock.sha256').read_text(), ''.join(
            f'{hashlib.sha256((self.requirements / name).read_bytes()).hexdigest()}  {name}\n' for name in FILES))
        self.assertEqual({name: (self.requirements / name).read_bytes() for name in inputs}, inputs)

    def test_compile_without_uv_names_the_input_and_the_command_to_rerun(self):
        empty = self.root.parent / 'empty'
        empty.mkdir()
        self.write_lock()
        before = {path.name: path.read_bytes() for path in self.requirements.iterdir()}
        result = self.run_locks('compile', self.requirements, '3.12', 'oasis setup --apply', env={'PATH': str(empty)})
        # uv cannot run: reported as exit 127 (the shell's "command not found"); compile exits 2.
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
            'uv pip compile of runtime.in failed (exit 127); lock.sha256 was left as it was.\n'
            f'Fix {self.requirements / "runtime.in"} or its access to the package index, then run oasis setup '
            '--apply again.\n')))
        self.assertEqual({path.name: path.read_bytes() for path in self.requirements.iterdir()}, before)

    def test_current_accepts_what_sha256sum_check_accepts_from_either_base(self):
        spec = importlib.util.spec_from_file_location('oasis_locks_test', LOCKS)
        locks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(locks)
        self.assertFalse(locks.current(self.requirements, self.root))
        self.write_lock()
        self.assertTrue(locks.current(self.requirements, self.root))
        self.write_lock('dev/requirements/')
        self.assertTrue(locks.current(self.requirements, self.root))
        (self.requirements / 'dev.txt').write_text('# changed\n')
        self.assertFalse(locks.current(self.requirements, self.root))
        (self.requirements / 'lock.sha256').write_text('')
        self.assertFalse(locks.current(self.requirements, self.root))


if __name__ == '__main__':
    unittest.main()
