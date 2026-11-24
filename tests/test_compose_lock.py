"""`compose up` of the shared database service is serialized between checkouts (S6, S7).

Two synthetic checkouts share one compose file. The fake docker's `compose up` takes 2 s and
fails like Docker's container name conflict when another `up` is in progress, so overlapping
calls are visible. The lock lives in the private runtime root of each test (XDG_RUNTIME_DIR).
"""
from pathlib import Path
import fcntl
import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
import unittest

import test_lifecycle as lifecycle

TIMEOUT_MESSAGE = 'Timed out waiting for another checkout to start the database service.\n'
NO_FLOCK_WARNING = ('WARNING: flock not found; starting the database service without the '
                    'cross-checkout lock.\n')
# `compose up` records its begin and end; a concurrent one fails like Docker's name conflict.
DOCKER = '''#!/bin/sh
case "$*" in
  *" up -d --wait "*)
    if ! mkdir "$FAKE_LOG.up" 2>/dev/null; then
      printf "conflict %s\\n" "$$" >> "$FAKE_LOG"
      echo 'Error response from daemon: Conflict. The container name "/db" is already in use.' >&2
      exit 1
    fi
    printf "docker %s\\n" "$*" >> "$FAKE_LOG"
    printf "up-begin %s\\n" "$$" >> "$FAKE_LOG"
    sleep "${FAKE_UP_SECONDS:-2}"
    printf "up-end %s\\n" "$$" >> "$FAKE_LOG"
    rmdir "$FAKE_LOG.up" ;;
  *) printf "docker %s\\n" "$*" >> "$FAKE_LOG" ;;
esac
exit 0
'''
# Appended to the fake python: Odoo must not inherit the lock's file descriptor.
HOLDS_LOCK = '''for fd in /proc/$$/fd/*; do
  case "$(readlink "$fd")" in *compose-*.lock) echo "odoo holds the compose lock" >> "$FAKE_LOG" ;; esac
done
'''


class ComposeLockTests(unittest.TestCase):
    setUp_fixture = lifecycle.LifecycleTests.setUp
    unchanged = lifecycle.LifecycleTests.unchanged

    def setUp(self):
        self.setUp_fixture()
        (self.bindir / 'docker').write_text(DOCKER)
        self.python.write_text(self.python.read_text() + HOLDS_LOCK)
        self.compose_file = self.root / 'dev/compose.yml'
        # A second checkout of the same project whose profile names the first one's compose file.
        self.other = self.root.parent / 'b project'
        for name in ('dev/odoo.conf', 'dev/.env', 'coffee/__manifest__.py'):
            path = self.other / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        (self.other / 'oasis-workspace.toml').write_text(lifecycle.WORKSPACE.replace(
            "compose = 'dev/compose.yml'", "compose = '../a project/dev/compose.yml'"))
        self.lock = (Path(self.env['XDG_RUNTIME_DIR']) / f'oasis-{os.getuid()}' /
                     ('compose-' + hashlib.sha256(
                         os.path.realpath(self.compose_file).encode()).hexdigest()[:16] + '.lock'))

    def wrapper(self, root, command):
        path = root / 'dev/scripts' / command
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((lifecycle.STAGE / 'project-wrappers' / command).read_bytes())
        return path

    def run_in(self, root, command, *args, env=None):
        return subprocess.run(['bash', str(self.wrapper(root, command)), *args], text=True,
                              cwd=root, env=env or self.env, capture_output=True)

    def up_line(self):
        return (f'docker compose --env-file {self.root / "dev/.env"} -f {self.compose_file} '
                'up -d --wait --wait-timeout 60 db')

    def test_concurrent_starts_in_two_checkouts_do_not_overlap_compose_up(self):
        processes = [subprocess.Popen(['bash', str(self.wrapper(root, 'start')), '--stop-after-init'],
                                      text=True, cwd=root, env=self.env, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE)
                     for root in (self.root, self.other)]
        results = [(process.wait(timeout=60), *process.communicate()) for process in processes]
        self.assertEqual(results, [(0, '', ''), (0, '', '')])
        log = self.commands.read_text().splitlines()
        self.assertNotIn('odoo holds the compose lock', log)
        events = [line.split() for line in log if line.startswith(('up-begin ', 'up-end ', 'conflict '))]
        self.assertEqual([event for event, _pid in events], ['up-begin', 'up-end', 'up-begin', 'up-end'])
        self.assertEqual((events[0][1], events[2][1]), (events[1][1], events[3][1]))
        self.assertNotEqual(events[0][1], events[2][1])
        # The compose call itself is unchanged; the other checkout names the same file.
        ups = [line for line in log if ' up -d --wait ' in line]
        self.assertEqual(sorted(ups), sorted([self.up_line(), self.up_line().replace(
            str(self.root / 'dev/.env'), str(self.other / 'dev/.env'))]))
        self.assertEqual(len([line for line in log if line.startswith('odoo ')]), 2)
        self.assertEqual(stat.S_IMODE(self.lock.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.lock.parent.stat().st_mode), 0o700)

    def test_lock_timeout_fails_before_compose_up(self):
        self.lock.parent.mkdir(mode=0o700)
        descriptor = os.open(self.lock, os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        result = self.run_in(self.root, 'list-databases',
                             env={**self.env, 'ODOO19_COMPOSE_LOCK_TIMEOUT': '0.3'})
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', TIMEOUT_MESSAGE))
        self.unchanged()
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        self.env['FAKE_UP_SECONDS'] = '0'
        result = self.run_in(self.other, 'list-databases')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertIn(' up -d --wait --wait-timeout 60 db\n', self.commands.read_text())

    def test_lock_timeout_is_read_as_oasis_compose_lock_timeout_first(self):
        self.lock.parent.mkdir(mode=0o700)
        descriptor = os.open(self.lock, os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        # The legacy name would wait 60 s; the default 120 s. The OASIS_ name wins when set.
        env = {**self.env, 'OASIS_COMPOSE_LOCK_TIMEOUT': '0.3', 'ODOO19_COMPOSE_LOCK_TIMEOUT': '60'}
        result = subprocess.run(['bash', str(self.wrapper(self.root, 'list-databases'))], text=True,
                                cwd=self.root, env=env, capture_output=True, timeout=30)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', TIMEOUT_MESSAGE))
        self.unchanged()

    def test_without_flock_warns_and_still_starts_the_service(self):
        farm = Path(tempfile.mkdtemp(prefix='oasis-no-flock-'))
        self.addCleanup(shutil.rmtree, farm, ignore_errors=True)
        for directory in self.env['PATH'].split(':'):
            if not directory or not os.path.isdir(directory):
                continue
            for entry in os.scandir(directory):
                target = farm / entry.name
                if entry.name != 'flock' and not os.path.lexists(target):
                    target.symlink_to(entry.path)
        env = {**self.env, 'PATH': str(farm), 'FAKE_UP_SECONDS': '0'}
        self.assertIsNone(shutil.which('flock', path=env['PATH']))
        result = self.run_in(self.root, 'list-databases', env=env)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', NO_FLOCK_WARNING))
        self.assertIn(self.up_line() + '\n', self.commands.read_text())
        self.assertFalse(self.lock.exists())


if __name__ == '__main__':
    unittest.main()
