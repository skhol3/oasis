"""Public test invocations isolate short-lived scratch and retain browser evidence."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
from pathlib import Path
import os
import shutil
import signal
import subprocess
import time
import unittest
import test_compact_guards as compact_guards
import test_lifecycle as lifecycle


class TestTemporaryTests(unittest.TestCase):
    setUp = lifecycle.LifecycleTests.setUp
    invoke = lifecycle.LifecycleTests.invoke

    def prepare_probe(self, exit_code=0):
        self.inherited = self.root / ('inherited-' + 'x' * 80) / ('nested-' + 'y' * 80)
        self.inherited.mkdir(parents=True)
        self.sentinel = self.inherited / 'unrelated'
        self.sentinel.write_text('keep caller data\n')
        self.observation = self.root / 'observations'
        self.env.update(TMPDIR=str(self.inherited), FAKE_OBSERVATION=str(self.observation),
                        FAKE_EXIT=str(exit_code))
        self.python.write_text(self.python.read_text() + '''
printf '%s\n' "$TMPDIR" >> "$FAKE_OBSERVATION"
stat -c '%a' "$TMPDIR" >> "$FAKE_OBSERVATION"
case " $* " in
  *" --test-tags "*)
    mkdir -p "$TMPDIR/odoo_tests/run/chrome_logs"
    printf 'fake browser diagnostic\n' > "$TMPDIR/odoo_tests/run/chrome_logs/browser.log"
    printf 'fake screenshot\n' > "$TMPDIR/odoo_tests/run/screenshot.png"
    ;;
esac
if [ -n "${FAKE_WAIT_SIGNAL:-}" ]; then
  printf 'waiting\n' >> "$FAKE_OBSERVATION"
  exec sleep 30
fi
printf 'test stdout\n'
printf 'test stderr\n' >&2
exit "$FAKE_EXIT"
''')

    def assert_caller_intact(self):
        self.assertEqual(self.env['TMPDIR'], str(self.inherited))
        self.assertEqual(self.sentinel.read_text(), 'keep caller data\n')
        self.assertEqual(os.environ.get('TMPDIR'), self.caller_tmpdir)

    def assert_short_private_cleaned(self, paths):
        self.assertEqual(len(set(paths)), len(paths), 'each test invocation needs unique scratch')
        observations = self.observation.read_text().splitlines()
        for index, path in enumerate(paths):
            with self.subTest(scratch=path):
                self.assertEqual(Path(path).parent, Path('/tmp'),
                                 'test TMPDIR must be short and independent of inherited nesting')
                self.assertLess(len(path), 80, 'test TMPDIR must leave room for browser sockets')
                self.assertEqual(observations[index * 2 + 1], '700', 'test scratch must be private')
                self.assertFalse(Path(path).exists(), 'owned test scratch must be cleaned after child')
        self.assertEqual(list(self.inherited.iterdir()), [self.sentinel],
                         'test artifacts must not leak into caller scratch')

    def assert_evidence_retained(self):
        logs = self.root / 'logs/main'
        files = [p for p in logs.rglob('*') if p.is_file()] if logs.exists() else []
        self.assertTrue(any(p.name == 'browser.log' and
                            p.read_text() == 'fake browser diagnostic\n' for p in files),
                        'browser diagnostics must survive cleanup under the logs directory')
        self.assertTrue(any(p.name == 'screenshot.png' and
                            p.read_text() == 'fake screenshot\n' for p in files),
                        'browser screenshot must survive cleanup under the logs directory')

    def test_long_inherited_tmpdir_success_is_unique_private_and_quiet(self):
        self.caller_tmpdir = os.environ.get('TMPDIR')
        self.prepare_probe()
        for _ in range(2):
            result = self.invoke('test-module', 'coffee')
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (0, 'test stdout\n', 'test stderr\n'))
        self.assert_caller_intact()
        self.assert_short_private_cleaned(self.observation.read_text().splitlines()[::2])
        self.assert_evidence_retained()

    def test_failure_preserves_status_streams_and_browser_evidence(self):
        self.caller_tmpdir = os.environ.get('TMPDIR')
        self.prepare_probe(exit_code=7)
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (7, 'test stdout\n', 'test stderr\n'))
        self.assert_caller_intact()
        # Check evidence first so baseline RED identifies this separate missing behavior.
        self.assert_evidence_retained()
        self.assert_short_private_cleaned(self.observation.read_text().splitlines()[::2])

    def test_compact_preserves_short_scratch_evidence_and_existing_log_contract(self):
        self.caller_tmpdir = os.environ.get('TMPDIR')
        self.prepare_probe(exit_code=7)
        result = self.invoke('test-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (7, ''))
        lines = result.stdout.splitlines()
        self.assertRegex(lines[0], r'^phase=tests database=cc_test_coffee_r[0-9a-f]{6} exit=7$')
        self.assertEqual(lines[1], 'database_lifecycle=disposable dropped=yes')
        logs = dict(line.split('=', 1) for line in lines[2:])
        self.assertEqual(set(logs), {'stdout_log', 'stderr_log'})
        for key, stream in (('stdout_log', 'test stdout\n'), ('stderr_log', 'test stderr\n')):
            path = Path(logs[key])
            self.assertTrue(path.is_relative_to(self.root / 'logs/main'))
            self.assertEqual(path.read_text(), stream)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assert_caller_intact()
        self.assert_evidence_retained()
        self.assert_short_private_cleaned(self.observation.read_text().splitlines()[::2])

    def test_retained_evidence_directories_are_private(self):
        self.caller_tmpdir = os.environ.get('TMPDIR')
        self.prepare_probe()
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, 'test stdout\n', 'test stderr\n'))
        self.assert_evidence_retained()
        logs = self.root / 'logs/main'
        retained = [p for p in logs.rglob('*') if p.is_dir() and 'odoo_tests' in p.parts]
        self.assertTrue(retained, 'retained evidence directories expected')
        for path in retained:
            with self.subTest(directory=path.relative_to(logs)):
                self.assertEqual(path.stat().st_mode & 0o777, 0o700)
        self.assert_caller_intact()
        self.assert_short_private_cleaned(self.observation.read_text().splitlines()[::2])

    def test_interrupt_reports_signal_status_retains_evidence_and_cleans_scratch(self):
        # A terminal delivers Ctrl-C or SIGTERM to the whole foreground process group.
        self.caller_tmpdir = os.environ.get('TMPDIR')
        self.prepare_probe()
        for signum, status in ((signal.SIGINT, 130), (signal.SIGTERM, 143)):
            with self.subTest(signal=signum.name):
                self.observation.write_text('')
                shutil.rmtree(self.root / 'logs', ignore_errors=True)
                self.env['FAKE_WAIT_SIGNAL'] = '1'
                path = self.root / 'dev/scripts/test-module'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((lifecycle.STAGE / 'project-wrappers/test-module').read_bytes())
                process = subprocess.Popen(
                    ['bash', str(path), 'coffee'], cwd=self.root, env=self.env, text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
                deadline = time.monotonic() + 20
                while 'waiting' not in self.observation.read_text().splitlines():
                    self.assertIsNone(process.poll(), 'test child exited before the signal')
                    self.assertLess(time.monotonic(), deadline, 'test child never started')
                    time.sleep(0.05)
                scratch = Path(self.observation.read_text().splitlines()[0])
                os.killpg(process.pid, signum)
                stdout, stderr = process.communicate(timeout=20)
                # The wrapper shell either exits 128+N or is itself ended by signal N;
                # a calling shell reports both as the same status.
                code = 128 - process.returncode if process.returncode < 0 else process.returncode
                self.assertEqual((code, stdout, stderr), (status, '', ''))
                deadline = time.monotonic() + 20
                while scratch.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertEqual(scratch.parent, Path('/tmp'))
                self.assertFalse(scratch.exists(), 'owned test scratch must be cleaned after a signal')
                self.assert_evidence_retained()
                self.assert_caller_intact()

    def test_retention_failure_reports_owned_scratch_without_deleting_evidence(self):
        self.caller_tmpdir = os.environ.get('TMPDIR')
        self.prepare_probe()
        outside = self.root.parent / 'outside-logs'
        outside.mkdir()
        (self.root / 'logs').mkdir()
        (self.root / 'logs/main').symlink_to(outside, target_is_directory=True)
        result = self.invoke('test-module', 'coffee')
        scratch = Path(self.observation.read_text().splitlines()[0])
        self.assertEqual(scratch.parent, Path('/tmp'))
        self.assertTrue(scratch.name.startswith('oasis-test-'))
        self.addCleanup(shutil.rmtree, scratch)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, 'test stdout\n')
        self.assertEqual(result.stderr, 'test stderr\n' +
                         f'Cannot retain browser evidence; test scratch kept at {scratch}. '
                         'Inspect it before manual removal.\n')
        self.assertEqual((scratch / 'odoo_tests/run/chrome_logs/browser.log').read_text(),
                         'fake browser diagnostic\n')
        self.assertEqual(list(outside.iterdir()), [])
        self.assert_caller_intact()

    def test_evidence_excludes_profiles_and_external_symlinks(self):
        self.caller_tmpdir = os.environ.get('TMPDIR')
        self.prepare_probe()
        self.env['FAKE_SENTINEL'] = str(self.sentinel)
        self.python.write_text(self.python.read_text().replace(
            'printf \'test stdout',
            'mkdir -p "$TMPDIR/odoo_tests/run/profile"\n'
            'printf private > "$TMPDIR/odoo_tests/run/profile/Cookies"\n'
            'ln -s "$FAKE_SENTINEL" "$TMPDIR/odoo_tests/run/chrome_logs/external.log"\n'
            'ln -s "$(dirname "$FAKE_SENTINEL")" "$TMPDIR/odoo_tests/run/external"\n'
            'printf \'test stdout'))
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, 'test stdout\n', 'test stderr\n'))
        self.assert_evidence_retained()
        logs = self.root / 'logs/main'
        self.assertEqual({p.name for p in logs.rglob('*') if p.is_file()},
                         {'browser.log', 'screenshot.png'})
        self.assert_caller_intact()
        self.assert_short_private_cleaned(self.observation.read_text().splitlines()[::2])

    def test_install_and_update_keep_inherited_environment_and_streams(self):
        self.caller_tmpdir = os.environ.get('TMPDIR')
        self.prepare_probe()
        self.env['FAKE_EXISTS'] = '1'
        for command, args, expected in (
                ('install-module', ('coffee',), '-d cc_dev_coffee -i coffee --without-demo --stop-after-init'),
                ('update-module', ('coffee', 'cc_dev_coffee'), '-d cc_dev_coffee -u coffee --stop-after-init')):
            with self.subTest(command=command):
                result = self.invoke(command, *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (0, 'test stdout\n', 'test stderr\n'))
                self.assertIn(expected, self.commands.read_text())
        observations = self.observation.read_text().splitlines()
        self.assertEqual(observations[::2], [str(self.inherited)] * 2)
        self.assertNotIn('--test-tags', self.commands.read_text())
        self.assert_caller_intact()
        self.assertEqual(list(self.inherited.iterdir()), [self.sentinel])


class LinkedWorktreeEvidenceTests(unittest.TestCase):
    """Without [tooling].logs, a linked worktree's browser evidence goes to logs/<slug> next to its workspace file."""
    setUp = compact_guards.LinkedWorktreeCompactTests.setUp
    setUp_fixture = lifecycle.LifecycleTests.setUp
    git = compact_guards.LinkedWorktreeCompactTests.git
    invoke = compact_guards.LinkedWorktreeCompactTests.invoke
    prepare_probe = TestTemporaryTests.prepare_probe
    assert_caller_intact = TestTemporaryTests.assert_caller_intact
    assert_short_private_cleaned = TestTemporaryTests.assert_short_private_cleaned

    def test_evidence_is_copied_under_the_worktree_logs(self):
        self.caller_tmpdir = os.environ.get('TMPDIR')
        self.prepare_probe()
        result = self.invoke(self.linked, 'coffee')
        scratch = Path(self.observation.read_text().splitlines()[0])
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, 'test stdout\n', 'test stderr\n'))
        runs = list((self.linked / 'logs/wt').iterdir())
        self.assertEqual(len(runs), 1)
        files = {p.relative_to(runs[0]): p.read_text() for p in runs[0].rglob('*') if p.is_file()}
        self.assertEqual(files, {
            Path('odoo_tests/run/chrome_logs/browser.log'): 'fake browser diagnostic\n',
            Path('odoo_tests/run/screenshot.png'): 'fake screenshot\n'})
        self.assert_caller_intact()
        self.assert_short_private_cleaned(self.observation.read_text().splitlines()[::2])



class ConfiguredLogsEvidenceTests(unittest.TestCase):
    """With [tooling].logs, browser evidence goes to <logs>/<main|slug>/run-*."""
    setUp = compact_guards.ConfiguredLogsCompactTests.setUp
    setUp_fixture = lifecycle.LifecycleTests.setUp
    git = compact_guards.LinkedWorktreeCompactTests.git
    invoke = compact_guards.ConfiguredLogsCompactTests.invoke
    prepare_probe = TestTemporaryTests.prepare_probe
    assert_caller_intact = TestTemporaryTests.assert_caller_intact
    assert_short_private_cleaned = TestTemporaryTests.assert_short_private_cleaned

    def test_evidence_is_copied_under_each_checkout_directory(self):
        self.caller_tmpdir = os.environ.get('TMPDIR')
        self.prepare_probe()
        for root in (self.main, self.linked):
            result = self.invoke(root, 'test-module', 'coffee')
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (0, 'test stdout\n', 'test stderr\n'))
        for checkout_id in ('main', 'wt'):
            with self.subTest(checkout=checkout_id):
                runs = list((self.logs / checkout_id).iterdir())
                self.assertEqual(len(runs), 1)
                self.assertTrue(runs[0].name.startswith('run-'))
                files = {p.relative_to(runs[0]): p.read_text() for p in runs[0].rglob('*') if p.is_file()}
                self.assertEqual(files, {
                    Path('odoo_tests/run/chrome_logs/browser.log'): 'fake browser diagnostic\n',
                    Path('odoo_tests/run/screenshot.png'): 'fake screenshot\n'})
        self.assertFalse((self.main / 'dev/logs').exists())
        self.assertFalse((self.linked / 'dev/logs').exists())
        self.assert_caller_intact()
        self.assert_short_private_cleaned(self.observation.read_text().splitlines()[::2])

    def test_escaping_checkout_directory_keeps_the_scratch(self):
        self.caller_tmpdir = os.environ.get('TMPDIR')
        self.prepare_probe()
        outside = self.main.parent.parent / 'outside'
        outside.mkdir()
        self.logs.mkdir()
        (self.logs / 'wt').symlink_to(outside, target_is_directory=True)
        result = self.invoke(self.linked, 'test-module', 'coffee')
        scratch = Path(self.observation.read_text().splitlines()[0])
        self.assertEqual(scratch.parent, Path('/tmp'))
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        self.assertEqual((result.returncode, result.stdout), (1, 'test stdout\n'))
        self.assertEqual(result.stderr, 'test stderr\n' +
                         f'Cannot retain browser evidence; test scratch kept at {scratch}. '
                         'Inspect it before manual removal.\n')
        self.assertEqual(list(outside.iterdir()), [])
        self.assert_caller_intact()


if __name__ == '__main__':
    unittest.main()
