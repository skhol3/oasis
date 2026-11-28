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
from unittest import mock

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
        # `uv --version` prints FAKE_UV_VERSION (0.9.0 by default) and is not recorded; a compile records
        # UV_LEGACY_TAR_BACKEND when it is set, and FAKE_STDERR makes it fail with that message.
        (bindir / 'uv').write_text('#!/bin/sh\n'
                                   'if [ "$1" = --version ]; then echo "uv ${FAKE_UV_VERSION:-0.9.0} (fake)"; exit 0; fi\n'
                                   'printf "%s (in %s)%s\\n" "$*" "$PWD" "${UV_LEGACY_TAR_BACKEND:+ legacy}" >> "$FAKE_LOG"\n'
                                   'if [ -n "${FAKE_STDERR:-}" ]; then echo "$FAKE_STDERR" >&2; exit 1; fi\n'
                                   'for last; do :; done\nprintf "# compiled\\n" > "$last"\necho "# echo of the lock"\n')
        (bindir / 'uv').chmod(0o755)
        return {'PATH': str(bindir), 'FAKE_LOG': str(self.root.parent / 'uv.log')}

    def write_lock(self, prefix=''):
        (self.requirements / 'lock.sha256').write_text(''.join(
            f'{hashlib.sha256((self.requirements / name).read_bytes()).hexdigest()}  {prefix}{name}\n'
            for name in FILES))

    def assert_state(self, expected):
        result = self.run_locks('state', self.requirements)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected + '\n', ''))

    def test_a_missing_lock_or_fingerprint_is_missing(self):
        self.write_lock()
        for name in ('runtime.txt', 'dev.txt', 'lock.sha256'):
            with self.subTest(name=name):
                saved = (self.requirements / name).read_bytes()
                (self.requirements / name).unlink()
                self.assert_state('missing')
                (self.requirements / name).write_bytes(saved)

    def test_a_changed_input_is_stale(self):
        for name in ('runtime.in', 'dev.in'):
            with self.subTest(name=name):
                self.write_lock()
                (self.requirements / name).write_text('# changed\n')
                self.assert_state('stale')
                (self.requirements / name).write_text(f'# {name}\n')

    def test_a_lock_relative_to_the_project_root_is_stale_and_not_current(self):
        # v0.21.0 S6: the lock format before v0.12.0 (entries relative to the checkout) is no longer read:
        # compiling again (bootstrap --apply) writes lock.sha256 relative to its own directory.
        spec = importlib.util.spec_from_file_location('oasis_locks_root_test', LOCKS)
        locks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(locks)
        self.write_lock('dev/requirements/')
        self.assert_state('stale')
        self.assertFalse(locks.current(self.requirements))

    def test_an_unreadable_fingerprint_is_stale(self):
        (self.requirements / 'lock.sha256').write_text('# not a fingerprint\n')
        self.assert_state('stale')

    def test_a_lock_changed_under_current_inputs_is_edited(self):
        self.write_lock()
        (self.requirements / 'dev.txt').write_text('pylint==3.0.0\n')
        self.assert_state('edited')

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
            2, '', 'Usage: locks.py state <requirements dir> | '
                   'fingerprint <requirements dir> | compile <requirements dir> <python> <command to rerun> | '
                   'recorded <requirements dir> | uv-env\n'))

    # -- overrides.txt (v0.15.0 S7) -------------------------------------------------------------

    def test_without_overrides_the_fingerprint_is_byte_identical_to_earlier_versions(self):
        # The digests of these exact inputs, as lock.sha256 recorded them before overrides.txt existed.
        result = self.run_locks('fingerprint', self.requirements)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual((self.requirements / 'lock.sha256').read_text(), (
            '9ed86bb7d542ca99d69cfd1208d2bd37dcff833dbbe98c0d91d60cb1ede1f27f  runtime.in\n'
            '01e308c75d9532d9919f602d57a1686b07d716eb83e399b1420ef9effaa97e06  runtime.txt\n'
            'adc9689d3b0d81dbf01ead6b4be3e43a158bb3019aa5b69663070c495972b440  dev.in\n'
            '0b1ba697667bcf55c7164481b690e64f197547f691d98cd7725cec97618e6218  dev.txt\n'))
        self.assertEqual(sorted(path.name for path in self.requirements.iterdir()), sorted([*FILES, 'lock.sha256']))

    def test_overrides_go_to_both_compiles_and_into_the_fingerprint(self):
        overrides = self.requirements / 'overrides.txt'
        overrides.write_text('-r ../requirements-overrides.txt\n')
        env = self.fake_uv()
        result = self.run_locks('compile', self.requirements, '3.8', 'oasis bootstrap --apply', env=env)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(Path(env['FAKE_LOG']).read_text().splitlines(), [
            f'pip compile --python-version 3.8 --override overrides.txt runtime.in -o runtime.txt (in {self.requirements})',
            f'pip compile --python-version 3.8 --override overrides.txt dev.in -o dev.txt (in {self.requirements})'])
        expected = ''.join(f'{hashlib.sha256((self.requirements / name).read_bytes()).hexdigest()}  {name}\n'
                           for name in (*FILES, 'overrides.txt'))
        self.assertEqual((self.requirements / 'lock.sha256').read_text(), expected)
        self.assertEqual(overrides.read_text(), '-r ../requirements-overrides.txt\n')
        if shutil.which('sha256sum'):
            check = subprocess.run(['sha256sum', '--check', '--strict', 'lock.sha256'], cwd=self.requirements,
                                   capture_output=True)
            self.assertEqual(check.returncode, 0)
        self.assert_state('edited')
        self.assertEqual(self.run_locks('recorded', self.requirements).returncode, 0)

    def test_an_added_changed_or_removed_overrides_file_makes_the_locks_stale(self):
        spec = importlib.util.spec_from_file_location('oasis_locks_overrides_test', LOCKS)
        locks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(locks)
        overrides = self.requirements / 'overrides.txt'
        # Added after the locks: lock.sha256 does not record it, so the locks are stale and not current.
        self.write_lock()
        overrides.write_text('cryptography==3.4.8\n')
        self.assert_state('stale')
        self.assertFalse(locks.current(self.requirements))
        recorded = self.run_locks('recorded', self.requirements)
        self.assertEqual((recorded.returncode, recorded.stdout, recorded.stderr), (1, '', ''))
        # Recorded, then changed.
        (self.requirements / 'lock.sha256').write_text(''.join(
            f'{hashlib.sha256((self.requirements / name).read_bytes()).hexdigest()}  {name}\n'
            for name in (*FILES, 'overrides.txt')))
        self.assertTrue(locks.current(self.requirements))
        self.assertEqual(self.run_locks('recorded', self.requirements).returncode, 0)
        overrides.write_text('cryptography==3.4.7\n')
        self.assert_state('stale')
        self.assertFalse(locks.current(self.requirements))
        # Recorded, then removed.
        overrides.unlink()
        self.assert_state('stale')
        self.assertFalse(locks.current(self.requirements))
        # Without overrides.txt nothing needs recording.
        self.write_lock()
        recorded = self.run_locks('recorded', self.requirements)
        self.assertEqual((recorded.returncode, recorded.stdout, recorded.stderr), (0, '', ''))

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

    # -- old source archives (v0.16.0 S3, docs/setup.md#old-source-archives) ------------------------

    def test_uv_0_13_and_later_compile_with_the_legacy_tar_backend(self):
        env = self.fake_uv()
        log = Path(env['FAKE_LOG'])
        for version, mark in (('0.12.9', ''), ('0.13.0', ' legacy'), ('1.2.3', ' legacy')):
            with self.subTest(version=version):
                result = self.run_locks('compile', self.requirements, '3.9', 'oasis setup --apply',
                                        env={**env, 'FAKE_UV_VERSION': version})
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
                self.assertEqual(log.read_text().splitlines(), [
                    f'pip compile --python-version 3.9 runtime.in -o runtime.txt (in {self.requirements}){mark}',
                    f'pip compile --python-version 3.9 dev.in -o dev.txt (in {self.requirements}){mark}'])
                log.unlink()
        # A value the caller set is kept, whatever the version.
        result = self.run_locks('compile', self.requirements, '3.9', 'oasis setup --apply',
                                env={**env, 'UV_LEGACY_TAR_BACKEND': '', 'FAKE_UV_VERSION': '0.13.0'})
        self.assertEqual(result.returncode, 0)
        self.assertFalse(log.read_text().splitlines()[0].endswith(' legacy'))
        exported = self.run_locks('uv-env', env={**env, 'FAKE_UV_VERSION': '0.13.0'})
        self.assertEqual((exported.returncode, exported.stdout, exported.stderr),
                         (0, 'export UV_LEGACY_TAR_BACKEND=1\n', ''))
        quiet = self.run_locks('uv-env', env={**env, 'FAKE_UV_VERSION': '0.12.0'})
        self.assertEqual((quiet.returncode, quiet.stdout, quiet.stderr), (0, '', ''))

    def test_uv_env_exports_nothing_when_the_variable_is_set_or_the_version_cannot_be_read(self):
        env = self.fake_uv()
        for value in ('1', '0', ''):
            with self.subTest(value=value):
                result = self.run_locks('uv-env', env={**env, 'FAKE_UV_VERSION': '0.13.0', 'UV_LEGACY_TAR_BACKEND': value})
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        uv = Path(env['PATH']) / 'uv'
        for name, script in (
                ('unparseable', '#!/bin/sh\necho "uv (development build)"\n'),
                ('failing', '#!/bin/sh\necho "error: broken" >&2\nexit 3\n'),
                ('silent', '#!/bin/sh\nexit 0\n'),
                ('not executable', None)):
            with self.subTest(uv=name):
                if script is None:
                    uv.chmod(0o644)
                else:
                    uv.write_text(script)
                result = self.run_locks('uv-env', env=env)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        uv.unlink()
        result = self.run_locks('uv-env', env=env)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))

    def test_compile_streams_uv_messages_while_uv_runs(self):
        # uv prints a line, then waits until the test has read it: compile passes it on before uv ends.
        env = self.fake_uv()
        release = self.root.parent / 'release'
        uv = Path(env['PATH']) / 'uv'
        uv.write_text('#!/bin/sh\n'
                      'if [ "$1" = --version ]; then echo "uv 0.9.0 (fake)"; exit 0; fi\n'
                      'echo "Resolved 3 packages" >&2\n'
                      f'i=0; while [ ! -e "$FAKE_RELEASE" ] && [ $i -lt 300 ]; do {shutil.which("sleep")} 0.05; '
                      'i=$((i+1)); done\n'
                      '[ -e "$FAKE_RELEASE" ] || exit 9\n'
                      'for last; do :; done\nprintf "# compiled\\n" > "$last"\n')
        process = subprocess.Popen([sys.executable, '-I', '-B', str(LOCKS), 'compile', str(self.requirements), '3.12',
                                    'oasis bootstrap --apply'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env={**env, 'FAKE_RELEASE': str(release)})
        try:
            first = process.stderr.readline()
            self.assertIsNone(process.poll())
            release.touch()
            rest = process.stderr.read()
            self.assertEqual(process.wait(timeout=30), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
            process.stderr.close()
        self.assertEqual((first, rest), (b'Resolved 3 packages\n', b'Resolved 3 packages\n'))

    def test_compile_passes_uv_messages_on_as_uv_wrote_them(self):
        # Undecodable bytes are replaced and line ends translated, as before; the remedy follows uv's last line.
        env = self.fake_uv()
        (Path(env['PATH']) / 'uv').write_text('#!/bin/sh\n'
                                              'if [ "$1" = --version ]; then echo "uv 0.9.0 (fake)"; exit 0; fi\n'
                                              "printf 'caf\\303\\251 \\377\\r\\nline\\rend' >&2\nexit 1\n")
        result = subprocess.run([sys.executable, '-I', '-B', str(LOCKS), 'compile', str(self.requirements), '3.12',
                                 'oasis bootstrap --apply'], capture_output=True, env=env)
        self.assertEqual((result.returncode, result.stdout), (2, b''))
        self.assertEqual(result.stderr, (
            'café �\nline\nenduv pip compile of runtime.in failed (exit 1); lock.sha256 was left as it was.\n'
            f'Fix {self.requirements / "runtime.in"} or its access to the package index, then run oasis bootstrap '
            '--apply again.\n').encode())

    def test_an_invalid_tar_identity_names_its_remedy(self):
        env = {**self.fake_uv(), 'FAKE_STDERR': 'error: Failed to extract archive: PyPDF2-1.26.0.tar.gz: invalid tar '
                                                'identity'}
        self.write_lock()
        before = {path.name: path.read_bytes() for path in self.requirements.iterdir()}
        for version, remedy in (
                ('0.12.0', 'uv could not read an old source archive (invalid tar identity): set UV_LEGACY_TAR_BACKEND=1 '
                           '(docs/setup.md#old-source-archives), then run oasis setup --apply again.\n'),
                ('0.13.2', 'uv could not read an old source archive (invalid tar identity) even with '
                           f'UV_LEGACY_TAR_BACKEND=1: pin a version of that package with a wheel in '
                           f'{self.requirements / "overrides.txt"} (uv pip compile --override), then run oasis setup '
                           '--apply again.\n')):
            with self.subTest(version=version):
                result = self.run_locks('compile', self.requirements, '3.9', 'oasis setup --apply',
                                        env={**env, 'FAKE_UV_VERSION': version})
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
                    f'{env["FAKE_STDERR"]}\nuv pip compile of runtime.in failed (exit 1); lock.sha256 was left as it '
                    f'was.\n{remedy}')))
                self.assertEqual({path.name: path.read_bytes() for path in self.requirements.iterdir()}, before)

    def test_current_accepts_what_sha256sum_check_accepts_from_the_requirements_directory(self):
        spec = importlib.util.spec_from_file_location('oasis_locks_test', LOCKS)
        locks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(locks)
        self.assertFalse(locks.current(self.requirements))
        self.write_lock()
        self.assertTrue(locks.current(self.requirements))
        (self.requirements / 'dev.txt').write_text('# changed\n')
        self.assertFalse(locks.current(self.requirements))
        (self.requirements / 'lock.sha256').write_text('')
        self.assertFalse(locks.current(self.requirements))

    def test_a_failed_relay_kills_and_waits_for_the_child_before_raising(self):
        spec = importlib.util.spec_from_file_location('oasis_locks_streamed_test', LOCKS)
        locks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(locks)
        # A child that writes to stderr, then keeps running: the relay of its first line fails.
        child = [sys.executable, '-c', 'import sys, time; sys.stderr.write("resolving\\n"); sys.stderr.flush(); '
                                       'time.sleep(60)']
        started = []
        popen = subprocess.Popen

        def record(*args, **kwargs):
            started.append(popen(*args, **kwargs))
            return started[-1]

        for error in (BrokenPipeError, KeyboardInterrupt):
            with self.subTest(error=error.__name__):
                started.clear()
                with mock.patch.object(locks.subprocess, 'Popen', record), \
                        mock.patch.object(locks.sys, 'stderr', mock.Mock(write=mock.Mock(side_effect=error()))):
                    with self.assertRaises(error):
                        locks.streamed(child)
                [process] = started
                self.addCleanup(lambda p=process: p.poll() is None and (p.kill(), p.wait()))
                # Waited for: its exit status is known without waiting again.
                self.assertIsNotNone(process.returncode)
                self.assertEqual(process.returncode, -9)


if __name__ == '__main__':
    unittest.main()
