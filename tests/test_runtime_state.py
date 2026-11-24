"""Per-checkout Odoo server state: HTTP ports, start, stop, status and test-run ports (S6, S7).

The lifecycle fixture (fake docker/python recording every argv) with a private
XDG_RUNTIME_DIR per test; the linked checkout comes from the shared-conf fixture. Every
socket a test binds uses 127.0.0.1 only, and every spawned process is killed in cleanup.
"""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import test_lifecycle as lifecycle
import test_shared_conf as shared

STATE = lifecycle.STAGE / 'tools' / 'runtime_state.py'
# Appended to the fake python: with FAKE_SERVE=1 the "server" becomes `<python> <odoo-bin> ...`
# (the shape of a real Odoo launch) and stays alive until killed; odoo-bin is a sleeping script.
SERVE = f'if [ -n "${{FAKE_SERVE:-}}" ]; then exec "{sys.executable}" "$@"; fi\n'
SLEEPER = 'import time\nwhile True:\n    time.sleep(0.1)\n'
# A fake odoo-bin for stop --force: FAKE_TERM=ignore makes it ignore SIGTERM (exit: it dies of it),
# and it starts a child (`<odoo-bin> --fake-child`) that always ignores SIGTERM and writes its pid
# to FAKE_CHILD once it does.
STUBBORN = '''import os, signal, subprocess, sys, time
if sys.argv[1:] == ['--fake-child']:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with open(os.environ['FAKE_CHILD'], 'w') as stream:
        stream.write(str(os.getpid()))
    while True:
        time.sleep(0.1)
if os.environ.get('FAKE_TERM') == 'ignore':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
subprocess.Popen([sys.executable, sys.argv[0], '--fake-child'])
while True:
    time.sleep(0.1)
'''
# A fake prefork master for stop --force: it ignores SIGTERM (FAKE_TERM=ignore) and forks a worker
# again each time the last one ended. Each worker appends its pid to FAKE_WORKERS and ends a few
# milliseconds later while its master lives, so new workers keep appearing; once the master is gone
# a worker stays until it is killed.
PREFORK = '''import os, signal, time
if os.environ.get('FAKE_TERM') == 'ignore':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
master = os.getpid()
while True:
    worker = os.fork()
    if worker == 0:
        with open(os.environ['FAKE_WORKERS'], 'a') as stream:
            stream.write(f'{os.getpid()}\\n')
        born = time.monotonic()
        while os.getppid() == master:
            if time.monotonic() - born > 0.005:
                os._exit(0)
            time.sleep(0.001)
        while True:
            time.sleep(0.1)
    os.waitpid(worker, 0)
'''


bindable = lifecycle.bindable


def free_ports(count):
    """A port P such that P .. P+count-1 are free on 127.0.0.1 (outside the ephemeral range:
    lifecycle.quiet_ports)."""
    return lifecycle.quiet_ports(count)


@contextmanager
def busy(*ports):
    """Hold listening sockets on 127.0.0.1 for the given ports."""
    sockets = []
    try:
        for port in ports:
            holder = socket.socket()
            sockets.append(holder)
            holder.bind(('127.0.0.1', port))
            holder.listen()
        yield
    finally:
        for holder in sockets:
            holder.close()


def state_dir(xdg, root):
    digest = hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:16]
    return Path(xdg) / f'oasis-{os.getuid()}' / digest


def load_state_module():
    spec = importlib.util.spec_from_file_location('runtime_state_under_test', STATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ago(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(timespec='seconds')


def privileged_port_is_refused():
    """Port 1 is refused with EACCES for an unprivileged user (not root, default sysctl)."""
    return os.geteuid() != 0 and not bindable(1)


class RuntimeStateHelperTests(unittest.TestCase):
    """tools/runtime_state.py on its own."""

    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix='oasis-state-')).resolve()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.xdg = self.scratch / 'xdg'
        self.xdg.mkdir(mode=0o700)
        self.root = self.scratch / 'checkout'
        self.root.mkdir()
        self.odoo_bin = self.scratch / 'source' / 'odoo-bin'
        self.odoo_bin.parent.mkdir()
        self.odoo_bin.write_text(SLEEPER)
        self.env = {**os.environ, 'XDG_RUNTIME_DIR': str(self.xdg)}

    def helper(self, *args):
        return subprocess.run([sys.executable, '-B', str(STATE), *args], capture_output=True,
                              text=True, env=self.env)

    def spawn(self, *argv):
        """A process shaped like the Odoo launch (`<python> <odoo-bin>`) unless argv is given."""
        process = subprocess.Popen(list(argv) or [sys.executable, str(self.odoo_bin)])
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        return process

    def dummy(self, last):
        """A python process that only names `last` as a later argument."""
        return self.spawn(sys.executable, '-c', 'import time; time.sleep(30)', str(last))

    def record_path(self):
        return state_dir(self.xdg, self.root) / 'server.json'

    def write(self, pid, started_at, port=8070):
        """A record for pid with the given started_at (written by `record`, then adjusted)."""
        result = self.helper('record', str(self.root), str(pid), str(port), str(self.odoo_bin))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(self.record_path().read_text())
        data['started_at'] = started_at
        self.record_path().write_text(json.dumps(data))
        return data

    def assert_show(self, stdout):
        result = self.helper('show', str(self.root))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, stdout, ''))

    def test_record_creates_private_state_per_checkout(self):
        process = self.spawn()
        result = self.helper('record', str(self.root), str(process.pid), '8069', str(self.odoo_bin))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        directory = state_dir(self.xdg, self.root)
        self.assertEqual(directory.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        record = directory / 'server.json'
        self.assertEqual(record.stat().st_mode & 0o777, 0o600)
        data = json.loads(record.read_text())
        self.assertEqual((data['pid'], data['port'], data['project_root']),
                         (process.pid, 8069, str(self.root)))
        self.assertTrue(data['started_at'])
        self.assertEqual([path.name for path in directory.iterdir()], ['server.json'])

    def test_live_and_stale_records(self):
        process = self.spawn()
        self.helper('record', str(self.root), str(process.pid), '8070', str(self.odoo_bin))
        result = self.helper('show', str(self.root))
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'pid={process.pid} port=8070\n', ''))
        process.kill()
        process.wait()
        result = self.helper('show', str(self.root))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertFalse((state_dir(self.xdg, self.root) / 'server.json').exists())

    def test_a_process_without_the_odoo_bin_path_is_stale(self):
        other = self.scratch / 'other-bin'
        other.write_text(SLEEPER)
        process = self.spawn(sys.executable, str(other))
        self.write(process.pid, ago(60))
        self.assert_show('')
        self.assertFalse(self.record_path().exists())

    def test_a_fresh_record_is_live_during_the_start_to_exec_grace(self):
        # This test process exists but is not Odoo: live within 10 s of started_at, stale after.
        self.write(os.getpid(), ago(0))
        self.assert_show(f'pid={os.getpid()} port=8070\n')
        self.assertTrue(self.record_path().exists())
        self.write(os.getpid(), ago(60))
        self.assert_show('')
        self.assertFalse(self.record_path().exists())

    def test_liveness_requires_the_odoo_launch_shape(self):
        # Past the grace period only `<python> <odoo-bin>` (or argv[0] == odoo-bin) is live.
        later = self.dummy(self.odoo_bin)
        self.write(later.pid, ago(60))
        self.assert_show('')
        self.assertFalse(self.record_path().exists())
        launched = self.spawn()
        deadline = time.monotonic() + 10
        while Path(f'/proc/{launched.pid}/cmdline').read_bytes().split(b'\0')[1:2] != [
                os.fsencode(self.odoo_bin)]:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        self.write(launched.pid, ago(60))
        self.assert_show(f'pid={launched.pid} port=8070\n')
        self.assertTrue(self.record_path().exists())

    def test_argv0_equal_to_the_recorded_python_is_the_odoo_launch(self):
        # An interpreter whose name does not start with `python` (pypy3, a renamed venv
        # binary) is live when it is the python recorded by start (realpaths compared).
        pypy = self.scratch / 'bin' / 'pypy3'
        pypy.parent.mkdir()
        pypy.symlink_to(sys.executable)
        launched = self.spawn(str(pypy), str(self.odoo_bin))
        deadline = time.monotonic() + 10
        while Path(f'/proc/{launched.pid}/cmdline').read_bytes().split(b'\0')[1:2] != [
                os.fsencode(self.odoo_bin)]:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        # Without the recorded python the basename rule alone does not accept pypy3.
        self.write(launched.pid, ago(60))
        self.assert_show('')
        self.assertFalse(self.record_path().exists())
        result = self.helper('record', str(self.root), str(launched.pid), '8070', str(self.odoo_bin), str(pypy))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        data = json.loads(self.record_path().read_text())
        self.assertEqual(data['python'], str(pypy))
        self.record_path().write_text(json.dumps({**data, 'started_at': ago(60)}))
        self.assert_show(f'pid={launched.pid} port=8070\n')
        # A recorded python that is not argv[0] does not make another interpreter live.
        other = self.scratch / 'bin' / 'other-python-name'
        other.write_text('')
        self.record_path().write_text(json.dumps({**data, 'started_at': ago(60), 'python': str(other)}))
        self.assert_show('')
        # A wrongly typed python makes the record invalid.
        self.write(launched.pid, ago(0))
        data = json.loads(self.record_path().read_text())
        self.record_path().write_text(json.dumps({**data, 'python': 3}))
        self.assert_show('')
        self.assertFalse(self.record_path().exists())

    def test_run_locks_are_created_exclusively_and_private(self):
        database = 'cc_test_coffee_r123456'
        process = self.spawn()
        result = self.helper('run-lock', str(self.root), database, str(process.pid))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        path = state_dir(self.xdg, self.root) / 'runs' / f'{database}.json'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        before = path.read_bytes()
        self.assertEqual(json.loads(before)['pid'], process.pid)
        # A second lock for the same database is refused, whoever holds it, live or not.
        other = self.spawn()
        for pid in (other.pid, process.pid):
            result = self.helper('run-lock', str(self.root), database, str(pid))
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (2, '', f'Disposable test database is locked: {database}\n'))
            self.assertEqual(path.read_bytes(), before)
        process.kill()
        process.wait()
        result = self.helper('run-lock', str(self.root), database, str(other.pid))
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'Disposable test database is locked: {database}\n'))
        self.assertEqual(path.read_bytes(), before)
        # No temporary file is left next to the lock.
        self.assertEqual([entry.name for entry in path.parent.iterdir()], [path.name])

    def test_wrongly_typed_records_are_stale_without_traceback(self):
        process = self.spawn()
        valid = {'pid': process.pid, 'port': 8070, 'started_at': ago(0),
                 'project_root': str(self.root), 'odoo_bin': str(self.odoo_bin)}
        for text in ('[1, 2]', 'null', '"server"', '42',
                     json.dumps({**valid, 'pid': str(process.pid)}),
                     json.dumps({**valid, 'port': '8070'}),
                     json.dumps({**valid, 'pid': True}),
                     json.dumps({key: value for key, value in valid.items() if key != 'port'})):
            with self.subTest(text=text):
                self.write(process.pid, ago(0))
                self.record_path().write_text(text)
                self.assert_show('')
                self.assertFalse(self.record_path().exists())

    def test_a_record_replaced_while_judged_stale_survives(self):
        module = load_state_module()
        stale = self.write(os.getpid(), ago(60))
        directory = self.record_path().parent
        fresh = {**stale, 'pid': os.getpid(), 'port': 8071, 'started_at': ago(0)}
        judged = []

        def replaced_before_unlink(record):
            # Another start writes its record between read_live's read and its unlink.
            judged.append(record['port'])
            (directory / 'fresh.json').write_text(json.dumps(fresh))
            os.replace(directory / 'fresh.json', self.record_path())
            return False

        module.is_live = replaced_before_unlink
        self.assertIsNone(module.read_live(directory))
        self.assertEqual(judged, [8070])
        self.assertEqual(json.loads(self.record_path().read_text()), fresh)
        # Unchanged stale bytes are still removed.
        module = load_state_module()
        self.write(os.getpid(), ago(60))
        self.assertIsNone(module.read_live(directory))
        self.assertFalse(self.record_path().exists())

    @unittest.skipUnless(privileged_port_is_refused(), 'port 1 is bindable here (root or sysctl)')
    def test_an_unbindable_port_is_reported_without_traceback(self):
        result = self.helper('port', '127.0.0.1', '1', '1')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Cannot bind port 1: permission denied.\n'))

    def test_show_without_state_prints_nothing_and_creates_nothing(self):
        result = self.helper('show', str(self.root))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(list(self.xdg.iterdir()), [])

    def test_symlinked_state_directories_are_refused(self):
        target = self.scratch / 'elsewhere'
        target.mkdir(mode=0o700)
        user_root = self.xdg / f'oasis-{os.getuid()}'
        user_root.symlink_to(target, target_is_directory=True)
        for command in (('show', str(self.root)), ('record', str(self.root), '1', '8069', str(self.odoo_bin))):
            with self.subTest(command=command[0]):
                result = self.helper(*command)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, '', f'ERROR: Runtime state directory is a symlink: {user_root}\n'))
                self.assertEqual(list(target.iterdir()), [])
        user_root.unlink()
        user_root.mkdir(mode=0o700)
        checkout = state_dir(self.xdg, self.root)
        checkout.symlink_to(target, target_is_directory=True)
        result = self.helper('record', str(self.root), '1', '8069', str(self.odoo_bin))
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'ERROR: Runtime state directory is a symlink: {checkout}\n'))
        self.assertEqual(list(target.iterdir()), [])

    def test_compose_lock_is_private_per_compose_file_and_never_follows_a_symlink(self):
        compose = self.root / 'compose.yml'
        compose.touch()
        alias = self.scratch / 'alias.yml'
        alias.symlink_to(compose)
        digest = hashlib.sha256(str(compose.resolve()).encode()).hexdigest()[:16]
        lock = self.xdg / f'oasis-{os.getuid()}' / f'compose-{digest}.lock'
        for path in (compose, alias):
            result = self.helper('compose-lock', str(path))
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, f'{lock}\n', ''))
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(lock.parent.stat().st_mode), 0o700)
        lock.chmod(0o644)
        self.assertEqual(self.helper('compose-lock', str(compose)).returncode, 0)
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)
        lock.unlink()
        target = self.scratch / 'elsewhere.lock'
        lock.symlink_to(target)
        result = self.helper('compose-lock', str(compose))
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'ERROR: Cannot open the compose lock: {lock}\n'))
        self.assertFalse(target.exists())

    def test_free_and_ephemeral_ports(self):
        port = free_ports(3)
        with busy(port):
            result = self.helper('port', '127.0.0.1', str(port), str(port + 2))
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, f'{port + 1}\n', ''))
            result = self.helper('port', '127.0.0.1', str(port), str(port + 2), str(port + 1))
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, f'{port + 2}\n', ''))
            result = self.helper('port', '', str(port), str(port))
            self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', ''))
        result = self.helper('ephemeral-port')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(bindable(int(result.stdout)))
        # Excluded ports (a test run's HTTP port) are never handed out as its second port.
        first = int(result.stdout)
        result = self.helper('ephemeral-port', str(first))
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertNotEqual(int(result.stdout), first)
        self.assertTrue(bindable(int(result.stdout)))
        result = self.helper('ephemeral-port', 'http')
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.assertTrue(result.stderr.startswith('ERROR: Usage: runtime_state.py '), result.stderr)

    def fake_git(self, name, body):
        """A directory holding only a `git` script with body (none when body is None)."""
        directory = self.scratch / name
        directory.mkdir()
        if body is not None:
            git = directory / 'git'
            git.write_text(f'#!/bin/sh\n{body}\n')
            git.chmod(0o755)
        return str(directory)

    def test_servers_reports_a_git_failure_instead_of_no_servers(self):
        for name, body, message in (
                ('missing', None, 'Cannot run git worktree list: No such file or directory'),
                ('failing', 'echo "warning: first" >&2; echo "fatal: boom" >&2; exit 128',
                 'git worktree list failed: fatal: boom'),
                ('silent', 'exit 5', 'git worktree list exited with status 5')):
            with self.subTest(git=name):
                self.env['PATH'] = self.fake_git(name, body)
                result = self.helper('servers', str(self.root))
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', f'ERROR: {message}\n'))
        # A repository without servers still lists none.
        self.env['PATH'] = self.fake_git('working', f'printf "worktree {self.root}\\nHEAD 0\\n"')
        result = self.helper('servers', str(self.root))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))

    def in_process_stop(self, module, kill, process_info=None):
        """module.stop(force=True) with os.kill replaced by kill (and process_info when given):
        (exit code, stdout, stderr)."""
        stdout, stderr = io.StringIO(), io.StringIO()
        patches = [mock.patch.dict(os.environ, {'XDG_RUNTIME_DIR': str(self.xdg), 'OASIS_STOP_TIMEOUT': '0.3'}),
                   mock.patch.object(module.os, 'kill', kill), mock.patch.object(module, 'KILL_WAIT', 0.3)]
        if process_info is not None:
            patches.append(mock.patch.object(module, 'process_info', process_info))
        for patch in patches:
            patch.start()
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                status = module.stop(str(self.root), force=True)
        finally:
            for patch in reversed(patches):
                patch.stop()
        return status, stdout.getvalue(), stderr.getvalue()

    def test_stop_force_keeps_the_record_of_a_server_still_running_after_sigkill(self):
        process = self.spawn()
        self.write(process.pid, ago(0))
        before = self.record_path().read_bytes()
        sent = []
        # Every signal to the server is dropped: it outlives SIGTERM and SIGKILL.
        real_kill = os.kill
        def kill(pid, number):
            sent.append((pid, number))
            if pid != process.pid:
                real_kill(pid, number)
        result = self.in_process_stop(load_state_module(), kill)
        self.assertEqual(result, (1, '', f'Odoo is still running after SIGKILL: pid {process.pid}, port 8070.\n'))
        self.assertEqual(sent, [(process.pid, signal.SIGTERM), (process.pid, signal.SIGKILL)])
        self.assertIsNone(process.poll())
        self.assertEqual(self.record_path().read_bytes(), before)

    def test_stop_force_kills_the_server_alone_when_its_processes_cannot_be_read(self):
        process = self.spawn()
        self.write(process.pid, ago(0))
        sent = []
        real_kill = os.kill
        def kill(pid, number):
            # SIGTERM is dropped (a server that ignores it); SIGKILL reaches it.
            sent.append((pid, number))
            if number != signal.SIGTERM:
                real_kill(pid, number)
        result = self.in_process_stop(load_state_module(), kill, process_info=lambda pid: None)
        self.assertEqual(result, (0, (
            'Killed Odoo for this checkout after 0.3 s (SIGKILL; its other processes could not be read): '
            f'pid {process.pid}, port 8070.\n'), ''))
        self.assertEqual(sent, [(process.pid, signal.SIGTERM), (process.pid, signal.SIGKILL)])
        self.assertEqual(process.wait(5), -signal.SIGKILL)
        self.assertFalse(self.record_path().exists())

    def test_kill_all_kills_the_leader_first_then_rescans_its_processes(self):
        module = load_state_module()
        killed, appeared = [], {300: 3}
        def running(processes):
            return {pid: started for pid, started in processes.items() if pid not in killed}
        def scan(leader, started):
            # The leader's processes: a worker it started just before it was killed appears once.
            return {pid: s for pid, s in {100: 1, 200: 2, **appeared}.items() if pid != 300 or 100 in killed}
        with mock.patch.object(module, 'running', running), mock.patch.object(module, 'server_processes', scan), \
                mock.patch.object(module.os, 'kill', lambda pid, number: killed.append(pid)):
            module.kill_all({200: 2, 100: 1}, 100, 1)
        self.assertEqual(killed, [100, 200, 300])


class ServerLifecycleTests(unittest.TestCase):
    """start, stop and status of the main checkout (outside git: kind none) and a linked one."""
    setUp_fixture = lifecycle.LifecycleTests.setUp
    unchanged = lifecycle.LifecycleTests.unchanged

    def setUp(self):
        self.setUp_fixture()
        self.xdg = Path(self.env['XDG_RUNTIME_DIR'])
        self.python.write_text(self.python.read_text() + SERVE)
        (self.source / 'odoo-bin').write_text(SLEEPER)
        self.port = free_ports(4)
        self.write_conf(self.root / 'dev/odoo.conf')

    def write_conf(self, path, extra=''):
        path.write_text(lifecycle.conf_text(f'http_port = {self.port}\n{extra}'))

    def invoke(self, root, command, *args, input=None):
        path = root / 'dev/scripts' / command
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((lifecycle.STAGE / 'project-wrappers' / command).read_bytes())
        return subprocess.run(['bash', str(path), *args], text=True, input=input, cwd=root,
                              env=self.env, capture_output=True)

    def odoo_lines(self):
        if not self.commands.exists():
            return []
        return [line for line in self.commands.read_text().splitlines() if line.startswith('odoo ')]

    def odoo_call(self, root, *args):
        return ' '.join(['odoo', str(self.source / 'odoo-bin'), '-c', str(root / 'dev/odoo.conf'), *args])

    def record(self, root):
        path = state_dir(self.xdg, root) / 'server.json'
        return json.loads(path.read_text()) if path.exists() else None

    def started(self, result, port):
        match = re.fullmatch(rf'oasis start: http://localhost:{port} \(pid (\d+)\)\n', result.stderr)
        self.assertIsNotNone(match, result.stderr)
        return int(match.group(1))

    def serve(self, root, *args):
        """Start a long-running fake server; return it once Odoo has been exec'd."""
        lines = len(self.odoo_lines())
        path = root / 'dev/scripts/start'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((lifecycle.STAGE / 'project-wrappers/start').read_bytes())
        process = subprocess.Popen(['bash', str(path), *args], cwd=root, text=True,
                                   env={**self.env, 'FAKE_SERVE': '1'}, start_new_session=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.reap, process)
        deadline = time.monotonic() + 20
        while len(self.odoo_lines()) == lines:
            self.assertIsNone(process.poll(), process.stderr.read() if process.poll() is not None else '')
            self.assertLess(time.monotonic(), deadline, 'fake server never started')
            time.sleep(0.05)
        return process

    @staticmethod
    def reap(process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()

    def test_main_start_uses_the_conf_port_and_records_it(self):
        result = self.invoke(self.root, 'start', '--workers=0')
        self.assertEqual((result.returncode, result.stdout), (0, ''))
        pid = self.started(result, self.port)
        self.assertEqual(self.odoo_lines(), [self.odoo_call(self.root, f'--http-port={self.port}',
                                                            '--workers=0')])
        record = self.record(self.root)
        self.assertEqual((record['pid'], record['port'], record['project_root']),
                         (pid, self.port, str(self.root.resolve())))

    def test_main_start_without_conf_port_defaults_to_8069(self):
        (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text())
        if not bindable(8069):
            self.skipTest('8069 is in use on this host')
        result = self.invoke(self.root, 'start')
        self.assertEqual((result.returncode, result.stdout), (0, ''), result.stderr)
        self.started(result, 8069)
        self.assertEqual(self.odoo_lines(), [self.odoo_call(self.root, '--http-port=8069')])

    def test_main_start_refuses_a_busy_conf_port_before_anything_runs(self):
        with busy(self.port):
            result = self.invoke(self.root, 'start')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'Port {self.port} is in use by another process; pass --http-port or stop that process.\n'))
        self.unchanged()
        self.assertIsNone(self.record(self.root))

    def test_explicit_http_port_is_honored_in_every_form(self):
        explicit = self.port + 2
        for args in (('-p', str(explicit)), (f'-p{explicit}',), ('--http-port', str(explicit)),
                     (f'--http-port={explicit}',)):
            with self.subTest(args=args), busy(self.port):
                self.commands.unlink(missing_ok=True)
                result = self.invoke(self.root, 'start', *args)
                self.assertEqual((result.returncode, result.stdout), (0, ''), result.stderr)
                self.started(result, explicit)
                self.assertEqual(self.odoo_lines(), [self.odoo_call(self.root, *args)])
                self.assertEqual(self.record(self.root)['port'], explicit)
        with busy(explicit):
            self.commands.unlink()
            result = self.invoke(self.root, 'start', '--http-port', str(explicit))
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'Port {explicit} is in use by another process; pass another --http-port or stop that '
                          'process.\n'))
        self.unchanged()

    def test_start_help_goes_straight_to_odoo(self):
        with busy(self.port):
            result = self.invoke(self.root, 'start', '--help')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(self.odoo_lines(), [self.odoo_call(self.root, '--help')])
        self.assertIsNone(self.record(self.root))

    def test_second_start_while_live_is_refused(self):
        process = self.serve(self.root)
        record = self.record(self.root)
        self.assertEqual((record['pid'], record['port']), (process.pid, self.port))
        before = self.commands.read_text()
        result = self.invoke(self.root, 'start', '--http-port', str(self.port + 1))
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'Odoo is already running for this checkout: pid {process.pid}, '
                          f'port {self.port}; run oasis stop first.\n'))
        self.assertEqual(self.commands.read_text(), before)

    def test_status_shows_this_checkout_server(self):
        result = self.invoke(self.root, 'status')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, 'server: stopped\n', ''))
        self.assertTrue(self.commands.read_text().endswith(' ps\n'))
        process = self.serve(self.root)
        result = self.invoke(self.root, 'status')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'server: running pid {process.pid} port {self.port}\n', ''))
        self.assertTrue(self.commands.read_text().endswith(' ps\n'))
        result = subprocess.run([sys.executable, '-B', str(STATE), 'show', str(self.root)],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'pid={process.pid} port={self.port}\n', ''))

    def assert_batch_port(self, line, prefix, suffix):
        # A free HTTP port and a distinct free second (gevent) port, like test runs.
        match = re.fullmatch(re.escape(prefix) + r' --http-port=(\d+) --gevent-port=(\d+) ' + re.escape(suffix),
                             line)
        self.assertIsNotNone(match, line)
        ports = [int(match.group(1)), int(match.group(2))]
        self.assertNotEqual(ports[0], ports[1])
        for port in ports:
            self.assertGreaterEqual(port, 1024)
            self.assertNotEqual(port, self.port)
            self.assertTrue(bindable(port))

    def test_batch_start_ignores_the_live_server_and_the_busy_port(self):
        process = self.serve(self.root)
        path = state_dir(self.xdg, self.root) / 'server.json'
        before = path.read_bytes()
        self.assertEqual(json.loads(before)['pid'], process.pid)
        with busy(self.port):
            result = self.invoke(self.root, 'start', '--stop-after-init', '-u', 'coffee', '-d', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        lines = self.odoo_lines()
        self.assertEqual(lines[0], self.odoo_call(self.root, f'--http-port={self.port}'))
        self.assertEqual(len(lines), 2, lines)
        self.assert_batch_port(lines[1], self.odoo_call(self.root),
                               '--stop-after-init -u coffee -d cc_dev_coffee')
        self.assertEqual(path.read_bytes(), before)
        self.assertIsNone(process.poll())
        # An explicit port in a batch run is passed as given, unchecked and not repeated.
        with busy(self.port):
            result = self.invoke(self.root, 'start', '--stop-after-init', f'--http-port={self.port}')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        [line] = self.odoo_lines()[2:]
        match = re.fullmatch(re.escape(self.odoo_call(self.root)) + r' --gevent-port=(\d+) '
                             + re.escape(f'--stop-after-init --http-port={self.port}'), line)
        self.assertIsNotNone(match, line)
        self.assertNotEqual(int(match.group(1)), self.port)
        self.assertEqual(path.read_bytes(), before)
        # The database guards still apply to batch runs.
        result = self.invoke(self.root, 'start', '--stop-after-init', '-d', 'other_db')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Managed databases must use cc_dev_<name> or cc_test_<name>: other_db\n'))
        self.assertEqual(len(self.odoo_lines()), 3)

    def test_batch_start_in_a_linked_worktree_gets_only_free_ephemeral_ports(self):
        self.linked_layout()
        result = self.invoke(self.linked, 'start', '--stop-after-init', '-u', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        [line] = self.odoo_lines()
        self.assert_batch_port(line, ' '.join(['odoo', str(self.source / 'odoo-bin'), '-c', str(self.conf),
                                               self.addons]), '--stop-after-init -u coffee')
        self.assertIsNone(self.record(self.linked))

    @unittest.skipUnless(privileged_port_is_refused(), 'port 1 is bindable here (root or sysctl)')
    def test_start_relays_an_unbindable_port(self):
        for args, conf in ((('-p', '1'), None), (('--http-port=1',), None), ((), lifecycle.conf_text('http_port = 1\n'))):
            with self.subTest(args=args, conf=conf):
                if conf:
                    (self.root / 'dev/odoo.conf').write_text(conf)
                result = self.invoke(self.root, 'start', *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, '', 'Cannot bind port 1: permission denied.\n'))
                self.unchanged()
                self.assertIsNone(self.record(self.root))

    def test_start_records_the_profile_python(self):
        process = self.serve(self.root)
        record = self.record(self.root)
        self.assertEqual((record['pid'], record['python'], record['odoo_bin']),
                         (process.pid, str(self.python), str(self.source / 'odoo-bin')))

    def staged_tools_with_state_helper(self, source):
        """A copy of the tools whose runtime_state.py is replaced by source."""
        tools = Path(self.scratch.name) / 'staged-tools'
        shutil.copytree(lifecycle.STAGE / 'tools', tools, ignore=shutil.ignore_patterns('__pycache__'),
                        dirs_exist_ok=True)
        (tools / 'runtime_state.py').write_text(source)
        self.env['ODOO19_TOOLS_DIR'] = str(tools)

    def test_status_ignores_stderr_of_a_successful_state_read(self):
        for stdout, expected in (('pid=4242 port=8070', 'server: running pid 4242 port 8070\n'),
                                 ('', 'server: stopped\n')):
            with self.subTest(stdout=stdout):
                self.staged_tools_with_state_helper(
                    'import sys\n'
                    'print("warning: something to note", file=sys.stderr)\n'
                    f'print({stdout!r}) if {stdout!r} else None\n')
                result = self.invoke(self.root, 'status')
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (0, expected, 'warning: something to note\n'))
                self.assertTrue(self.commands.read_text().endswith(' ps\n'))
        # On failure stderr is the reason, and stdout is not mistaken for it.
        self.staged_tools_with_state_helper(
            'import sys\nprint("pid=1 port=2")\nprint("ERROR: broken state", file=sys.stderr)\nsys.exit(2)\n')
        result = self.invoke(self.root, 'status')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, 'server: unknown (broken state)\n', ''))

    @unittest.skipIf(os.geteuid() == 0, 'root can write a 0500 directory')
    def test_status_without_a_writable_temp_directory(self):
        process = self.serve(self.root)
        blocked = Path(self.scratch.name) / 'no-tmp'
        blocked.mkdir(mode=0o500)
        self.addCleanup(blocked.chmod, 0o700)
        self.env['TMPDIR'] = str(blocked)
        result = self.invoke(self.root, 'status')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'server: running pid {process.pid} port {self.port}\n', ''))
        self.assertTrue(self.commands.read_text().endswith(' ps\n'))
        self.commands.unlink()
        # A failing read still gives its reason, and a successful read's warnings stay on stderr.
        for source, stdout, stderr in (
                ('import sys\nprint("ERROR: broken state", file=sys.stderr)\nsys.exit(2)\n',
                 'server: unknown (broken state)\n', ''),
                ('import sys\nprint("warning: note", file=sys.stderr)\n', 'server: stopped\n',
                 'warning: note\n')):
            with self.subTest(stdout=stdout):
                self.staged_tools_with_state_helper(source)
                result = self.invoke(self.root, 'status')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, stdout, stderr))
                self.assertTrue(self.commands.read_text().endswith(' ps\n'))
                self.commands.unlink()

    def test_status_degrades_when_runtime_state_fails(self):
        target = self.xdg / 'elsewhere'
        target.mkdir(mode=0o700)
        user_root = self.xdg / f'oasis-{os.getuid()}'
        user_root.symlink_to(target, target_is_directory=True)
        result = self.invoke(self.root, 'status')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'server: unknown (Runtime state directory is a symlink: {user_root})\n', ''))
        self.assertTrue(self.commands.read_text().endswith(' ps\n'))
        self.assertEqual(list(target.iterdir()), [])

    def test_stop_without_a_server(self):
        result = self.invoke(self.root, 'stop')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, 'No Odoo server running for this checkout.\n', ''))
        self.assertNotIn('compose', self.commands.read_text() if self.commands.exists() else '')

    def linked_layout(self):
        shared.shared_layout(self)
        self.conf.write_text(f'[options]\naddons_path = {self.enterprise},{self.main},{self.odoo_addons}\n'
                             f'http_port = {self.port}\ngevent_port = {self.port}\n')
        self.addons = f'--addons-path={self.enterprise},{self.linked},{self.odoo_addons}'

    def test_linked_start_takes_the_next_free_port_after_the_conf_port(self):
        self.linked_layout()
        with busy(self.port, self.port + 1):
            result = self.invoke(self.linked, 'start')
        self.assertEqual((result.returncode, result.stdout), (0, ''), result.stderr)
        self.started(result, self.port + 2)
        # gevent: the first free port after the conf's gevent_port that is not the HTTP port.
        self.assertEqual(self.odoo_lines(), [' '.join([
            'odoo', str(self.source / 'odoo-bin'), '-c', str(self.conf), self.addons,
            f'--http-port={self.port + 2}', f'--gevent-port={self.port + 3}'])])
        self.assertEqual(self.record(self.linked)['port'], self.port + 2)

    def test_linked_start_passes_an_explicit_gevent_port_as_given(self):
        # The second port option comes from config.py (ODOO_SECOND_PORT_OPTION, --gevent-port on 19.0).
        self.linked_layout()
        for given in (['--gevent-port', '9999'], ['--gevent-port=9999']):
            with self.subTest(given=given):
                result = self.invoke(self.linked, 'start', *given)
                self.assertEqual((result.returncode, result.stdout), (0, ''), result.stderr)
                self.assertEqual(self.odoo_lines(), [' '.join([
                    'odoo', str(self.source / 'odoo-bin'), '-c', str(self.conf), self.addons,
                    f'--http-port={self.port + 1}', *given])])
                self.commands.unlink()
                (state_dir(self.xdg, self.linked) / 'server.json').unlink(missing_ok=True)

    def test_a_busy_port_names_the_checkout_whose_server_holds_it(self):
        self.linked_layout()
        # The linked worktree's server holds the main checkout's conf port (explicit -p).
        linked = self.serve(self.linked, '-p', str(self.port))
        self.assertEqual(self.record(self.linked)['port'], self.port)
        with busy(self.port):
            self.commands.unlink()
            result = self.invoke(self.main, 'start')
            self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
                f'Port {self.port} is in use by checkout {self.linked} (pid {linked.pid}); pass --http-port '
                'or run oasis stop in that checkout.\n')))
            self.unchanged()
            result = self.invoke(self.main, 'start', f'--http-port={self.port}')
            self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
                f'Port {self.port} is in use by checkout {self.linked} (pid {linked.pid}); pass another '
                '--http-port or run oasis stop in that checkout.\n')))
            self.unchanged()
            # Another port of a recorded server does not name it.
            with busy(self.port + 3):
                result = self.invoke(self.main, 'start', f'--http-port={self.port + 3}')
            self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
                f'Port {self.port + 3} is in use by another process; pass another --http-port or stop that '
                'process.\n')))
        self.assertIsNone(self.record(self.main))

    def test_stop_terminates_only_this_checkout_and_database_waits_for_others(self):
        self.linked_layout()
        main = self.serve(self.main)
        linked = self.serve(self.linked)
        linked_port = self.record(self.linked)['port']
        self.assertGreater(linked_port, self.port)
        # The main checkout cannot stop the database while the linked worktree serves.
        result = self.invoke(self.main, 'stop', '--database')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
            'Refusing to stop the database: Odoo is running for other checkouts:\n'
            f'  {self.linked} (port {linked_port}, pid {linked.pid})\n')))
        self.assertNotIn(' stop', self.commands.read_text())
        # stop in the linked worktree ends only its own server.
        result = self.invoke(self.linked, 'stop')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'Stopped Odoo for this checkout: pid {linked.pid}, port {linked_port}.\n', ''))
        self.assertEqual(linked.wait(5), -signal.SIGTERM)
        self.assertIsNone(self.record(self.linked))
        self.assertIsNone(main.poll())
        self.assertEqual(self.record(self.main)['pid'], main.pid)
        # The linked worktree's own --database stop still waits for the main checkout.
        result = self.invoke(self.linked, 'stop', '--database')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
            'Refusing to stop the database: Odoo is running for other checkouts:\n'
            f'  {self.main} (port {self.port}, pid {main.pid})\n')))
        result = self.invoke(self.main, 'stop')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(main.wait(5), -signal.SIGTERM)
        result = self.invoke(self.linked, 'stop', '--database')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertTrue(self.commands.read_text().endswith(
            f'docker compose --env-file {self.config_dir}/runtime-env -f {self.config_dir}/compose.yml stop db\n'))

    def test_stop_usage(self):
        for args in (('--all',), ('--force', '--database'), ('--database', '--force'), ('--force', '--force')):
            with self.subTest(args=args):
                result = self.invoke(self.root, 'stop', *args)
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertIn('Usage: ', result.stderr)
                self.assertIn('[--database | --force]', result.stderr)
                self.unchanged()
        result = self.invoke(self.root, 'stop', '--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn('[--database | --force]', result.stdout)
        self.assertIn('--force', result.stdout.split('\n', 1)[1])
        self.unchanged()

    def running(self, pid):
        """Whether pid still runs this test's fake odoo-bin (a zombie does not run)."""
        try:
            stat_line = Path(f'/proc/{pid}/stat').read_text()
            argv = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        except OSError:
            return False
        return stat_line[stat_line.rindex(')') + 2] != 'Z' and os.fsencode(str(self.source / 'odoo-bin')) in argv

    def kill_fake(self, pid):
        """SIGKILL pid only while it runs this test's fake odoo-bin (never a reused pid)."""
        if self.running(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def stubborn(self, term):
        """A foreground fake server (STUBBORN, FAKE_TERM=term) and the pid of its child."""
        (self.source / 'odoo-bin').write_text(STUBBORN)
        child_file = Path(self.scratch.name) / 'child.pid'
        self.env.update(FAKE_TERM=term, FAKE_CHILD=str(child_file), OASIS_STOP_TIMEOUT='1')
        process = self.serve(self.root)
        deadline = time.monotonic() + 20
        while not (child_file.exists() and child_file.read_text()):
            self.assertLess(time.monotonic(), deadline, 'the fake child never started')
            time.sleep(0.05)
        child = int(child_file.read_text())
        self.addCleanup(self.kill_fake, child)
        self.assertTrue(self.running(child))
        return process, child

    def test_stop_without_force_still_gives_up_after_the_timeout(self):
        # SIGTERM only, exit 1 after the timeout, server and record left as they are; it suggests --force.
        process, child = self.stubborn('ignore')
        before = (state_dir(self.xdg, self.root) / 'server.json').read_bytes()
        result = self.invoke(self.root, 'stop')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (1, '', f'Odoo did not stop within 1 s: pid {process.pid}, port {self.port}; run oasis stop --force.\n'))
        self.assertTrue(self.running(process.pid))
        self.assertTrue(self.running(child))
        self.assertEqual((state_dir(self.xdg, self.root) / 'server.json').read_bytes(), before)

    def test_stop_force_kills_a_server_and_a_child_that_ignore_sigterm(self):
        process, child = self.stubborn('ignore')
        result = self.invoke(self.root, 'stop', '--force')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, (
            f'Killed Odoo for this checkout after 1 s (SIGKILL to its session): pid {process.pid}, '
            f'port {self.port}.\n'), ''))
        self.assertEqual(process.wait(5), -signal.SIGKILL)
        deadline = time.monotonic() + 5
        while self.running(child):
            self.assertLess(time.monotonic(), deadline, 'the child survived stop --force')
            time.sleep(0.05)
        self.assertIsNone(self.record(self.root))
        result = self.invoke(self.root, 'status')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, 'server: stopped\n', ''))

    def test_stop_force_kills_session_members_that_outlive_the_server(self):
        process, child = self.stubborn('exit')
        result = self.invoke(self.root, 'stop', '--force')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, (
            f'Stopped Odoo for this checkout: pid {process.pid}, port {self.port}; killed 1 process(es) of '
            'its session that outlived it.\n'), ''))
        self.assertEqual(process.wait(5), -signal.SIGTERM)
        deadline = time.monotonic() + 5
        while self.running(child):
            self.assertLess(time.monotonic(), deadline, 'the child survived stop --force')
            time.sleep(0.05)
        self.assertIsNone(self.record(self.root))

    def test_stop_force_without_a_server_and_with_a_server_that_stops(self):
        result = self.invoke(self.root, 'stop', '--force')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, 'No Odoo server running for this checkout.\n', ''))
        process = self.serve(self.root)
        result = self.invoke(self.root, 'stop', '--force')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'Stopped Odoo for this checkout: pid {process.pid}, port {self.port}.\n', ''))
        self.assertEqual(process.wait(5), -signal.SIGTERM)
        self.assertIsNone(self.record(self.root))

    def test_status_lists_the_servers_of_every_checkout_of_the_repository(self):
        self.linked_layout()
        main = self.serve(self.main, '-d', 'cc_dev_coffee')
        linked = self.serve(self.linked)
        linked_port = self.record(self.linked)['port']
        # A live server of a checkout outside this repository is not listed.
        elsewhere = Path(self.scratch.name) / 'elsewhere'
        elsewhere.mkdir()
        sleeper = subprocess.Popen([sys.executable, str(self.source / 'odoo-bin')])
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        recorded = subprocess.run([sys.executable, '-B', str(STATE), 'record', str(elsewhere), str(sleeper.pid),
                                   str(self.port + 9), str(self.source / 'odoo-bin')],
                                  capture_output=True, text=True, env=self.env)
        self.assertEqual((recorded.returncode, recorded.stderr), (0, ''))
        lines = {self.main: f'  {self.main}: pid {main.pid}, port {self.port}, database cc_dev_coffee',
                 self.linked: f'  {self.linked}: pid {linked.pid}, port {linked_port}'}
        for root, process, port in ((self.main, main, self.port), (self.linked, linked, linked_port)):
            with self.subTest(root=root):
                result = self.invoke(root, 'status')
                listed = [lines[self.main] + (' (this checkout)' if root == self.main else ''),
                          lines[self.linked] + (' (this checkout)' if root == self.linked else '')]
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, (
                    f'server: running pid {process.pid} port {port}\nrepository servers: 2\n'
                    + ''.join(line + '\n' for line in listed)), ''))
                self.assertTrue(self.commands.read_text().endswith(' ps\n'))
        # A stopped checkout lists the servers of the others.
        self.assertEqual(self.invoke(self.linked, 'stop').returncode, 0)
        result = self.invoke(self.linked, 'status')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'server: stopped\nrepository servers: 1\n{lines[self.main]}\n', ''))
        self.assertEqual(self.invoke(self.main, 'stop').returncode, 0)
        result = self.invoke(self.main, 'status')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, 'server: stopped\nrepository servers: 0\n', ''))

    def test_stop_force_kills_the_master_first_and_the_workers_it_starts_meanwhile(self):
        (self.source / 'odoo-bin').write_text(PREFORK)
        workers = Path(self.scratch.name) / 'workers'
        self.env.update(FAKE_TERM='ignore', FAKE_WORKERS=str(workers), OASIS_STOP_TIMEOUT='1')
        def listed():
            return [int(pid) for pid in workers.read_text().split()] if workers.exists() else []
        self.addCleanup(lambda: [self.kill_fake(pid) for pid in listed()])
        process = self.serve(self.root)
        deadline = time.monotonic() + 20
        while len(listed()) < 3:
            self.assertLess(time.monotonic(), deadline, 'the fake master never started workers')
            time.sleep(0.05)
        result = self.invoke(self.root, 'stop', '--force')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, (
            f'Killed Odoo for this checkout after 1 s (SIGKILL to its session): pid {process.pid}, '
            f'port {self.port}.\n'), ''))
        self.assertEqual(process.wait(5), -signal.SIGKILL)
        deadline = time.monotonic() + 5
        while survivors := [pid for pid in listed() if self.running(pid)]:
            self.assertLess(time.monotonic(), deadline, f'workers survived stop --force: {survivors}')
            time.sleep(0.05)
        self.assertIsNone(self.record(self.root))

    def git_checkout(self):
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True, env=self.env, capture_output=True)

    def test_status_reports_unknown_repository_servers_when_git_fails(self):
        self.git_checkout()
        # git works for the checkout identity; only `git worktree list` fails.
        wrapper = Path(self.scratch.name) / 'git-wrapper'
        wrapper.mkdir()
        (wrapper / 'git').write_text('#!/bin/sh\ncase " $* " in *" worktree list "*) echo "fatal: boom" >&2; exit 128 ;; '
                                     f'esac\nexec {shutil.which("git")} "$@"\n')
        (wrapper / 'git').chmod(0o755)
        self.env['PATH'] = f'{wrapper}:{self.env["PATH"]}'
        result = self.invoke(self.root, 'status')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, (
            'server: stopped\nrepository servers: unknown (git worktree list failed: fatal: boom)\n'), ''))
        self.assertTrue(self.commands.read_text().endswith(' ps\n'))

    def test_status_counts_only_the_servers_on_stdout(self):
        self.git_checkout()
        self.staged_tools_with_state_helper(
            'import sys\n'
            'if sys.argv[1] == "servers":\n'
            '    print("/elsewhere: pid 4242, port 8070")\n'
            '    print("warning: something to note", file=sys.stderr)\n')
        result = self.invoke(self.root, 'status')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, (
            'server: stopped\nrepository servers: 1\n  /elsewhere: pid 4242, port 8070\n'),
            'warning: something to note\n'))
        self.assertTrue(self.commands.read_text().endswith(' ps\n'))
        # On failure the last stderr line is the reason, and stdout is not listed.
        self.staged_tools_with_state_helper(
            'import sys\n'
            'if sys.argv[1] == "servers":\n'
            '    print("/elsewhere: pid 4242, port 8070")\n'
            '    print("ERROR: broken servers", file=sys.stderr)\n'
            '    sys.exit(2)\n')
        result = self.invoke(self.root, 'status')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, 'server: stopped\nrepository servers: unknown (broken servers)\n', ''))


class TestRunPortTests(unittest.TestCase):
    """test-module and verify-module give the Odoo test process its own free HTTP port."""
    setUp = lifecycle.LifecycleTests.setUp
    invoke = lifecycle.LifecycleTests.invoke

    def assert_test_port(self, line, prefix):
        # A free HTTP port and a distinct free second (gevent) port.
        match = re.fullmatch(re.escape(prefix) + r' --http-port=(\d+) --gevent-port=(\d+) (.*)', line)
        self.assertIsNotNone(match, line)
        ports = [int(match.group(1)), int(match.group(2))]
        self.assertNotEqual(ports[0], ports[1])
        for port in ports:
            self.assertGreaterEqual(port, 1024)
            self.assertTrue(bindable(port))
        return match.group(3)

    def test_test_and_verify_runs_pass_a_free_http_port(self):
        prefix = f'odoo {self.source / "odoo-bin"} -c {self.root / "dev/odoo.conf"}'
        # The default test database is disposable: cc_test_coffee_r<6 hex>, and its _update sibling.
        tests = '-d cc_test_coffee_r<run> -i coffee --without-demo --test-tags /coffee --stop-after-init'
        for command, args in (('test-module', ()), ('test-module', ('--compact',)),
                              ('verify-module', ()), ('verify-module', ('--compact',))):
            with self.subTest(command=command, args=args):
                self.commands.unlink(missing_ok=True)
                result = self.invoke(command, *args, 'coffee')
                self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
                lines = [lifecycle.any_run_database(line) for line in self.commands.read_text().splitlines()
                         if line.startswith('odoo ')]
                self.assertEqual(self.assert_test_port(lines[0], prefix), tests)
                # Install and update phases keep their command line.
                self.assertEqual(lines[1:], [] if command == 'test-module' else [
                    f'{prefix} -d cc_test_coffee_r<run>_update -i coffee --without-demo --stop-after-init',
                    f'{prefix} -d cc_test_coffee_r<run>_update -u coffee --stop-after-init'])


if __name__ == '__main__':
    unittest.main()
