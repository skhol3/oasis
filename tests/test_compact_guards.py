"""Compact execution must preserve fail-closed behavior and evidence."""
from pathlib import Path
import hashlib
import unittest
import test_lifecycle as lifecycle


class CompactGuardTests(unittest.TestCase):
    setUp = lifecycle.LifecycleTests.setUp
    invoke = lifecycle.LifecycleTests.invoke
    unchanged = lifecycle.LifecycleTests.unchanged

    def test_compact_wait_failure_stops_before_reset(self):
        docker = self.bindir / 'docker'
        docker.write_text(docker.read_text().replace(
            'case "$*" in',
            'case "$*" in\n *"up -d --wait"*) '
            'echo "database unavailable" >&2; exit 41 ;;', 1))
        result = self.invoke('test-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (41, ''))
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], 'phase=tests database=cc_test_coffee exit=41')
        logs = dict(line.split('=', 1) for line in lines[1:])
        self.assertEqual(Path(logs['stdout_log']).read_text(), '')
        self.assertEqual(Path(logs['stderr_log']).read_text(), 'database unavailable\n')
        self.assertNotIn('dropdb ', self.commands.read_text())
        self.assertNotIn('odoo ', self.commands.read_text())

    def test_outside_log_symlink_rejected_before_effects(self):
        outside = self.root.parent / 'outside'
        outside.mkdir()
        sentinel = outside / 'sentinel'
        sentinel.write_bytes(b'unchanged')
        (self.root / 'dev/logs').symlink_to(outside, target_is_directory=True)
        profile = self.root / '.odoo19-agent.toml'
        before = hashlib.sha256(profile.read_bytes()).digest()
        for command in ('test-module', 'verify-module'):
            with self.subTest(command=command):
                result = self.invoke(command, '--compact', 'coffee')
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (1, '', 'Compact logs must remain inside the project.\n'))
                self.assertEqual(hashlib.sha256(profile.read_bytes()).digest(), before)
                self.assertEqual(sentinel.read_bytes(), b'unchanged')
                self.assertEqual(list(outside.iterdir()), [sentinel])
                self.unchanged()

    def test_compact_verify_update_failure_retains_streams(self):
        self.python.write_text(self.python.read_text() +
            'case " $* " in *" -u "*) echo "update out"; '
            'echo "update err" >&2; exit 7 ;; esac\n')
        result = self.invoke('verify-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (1, ''))
        self.assertIn('phase=current_code_update database=cc_test_coffee_update exit=7\n',
                      result.stdout)
        self.assertIn('current_code_update_exit=7\n', result.stdout)
        paths = [Path(line.split('=', 1)[1]) for line in result.stdout.splitlines()
                 if line.startswith(('stdout_log=', 'stderr_log='))]
        self.assertEqual(len(paths), 8)
        self.assertTrue(any(p.read_text() == 'update out\n' for p in paths))
        self.assertTrue(any(p.read_text() == 'update err\n' for p in paths))
