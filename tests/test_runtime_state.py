"""Per-checkout Odoo server state: HTTP ports, start, stop, status and test-run ports (S6, S7).

The lifecycle fixture (fake docker/python recording every argv) with a private
XDG_RUNTIME_DIR per test; the linked checkout comes from the shared-conf fixture. Every
socket a test binds uses 127.0.0.1 only, and every spawned process is killed in cleanup.
"""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import test_lifecycle as lifecycle
import test_shared_conf as shared

STATE = lifecycle.STAGE / 'tools' / 'runtime_state.py'
# Appended to the fake python: with FAKE_SERVE=1 the "server" stays alive until killed.
SERVE = 'if [ -n "${FAKE_SERVE:-}" ]; then while :; do sleep 0.1; done; fi\n'


def bindable(port):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


def free_ports(count):
    """A port P such that P .. P+count-1 are free on 127.0.0.1."""
    for _ in range(100):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        if port + count <= 65535 and all(bindable(port + offset) for offset in range(count)):
            return port
    raise AssertionError('no free port range on 127.0.0.1')


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
        self.env = {**os.environ, 'XDG_RUNTIME_DIR': str(self.xdg)}

    def helper(self, *args):
        return subprocess.run([sys.executable, '-B', str(STATE), *args], capture_output=True,
                              text=True, env=self.env)

    def spawn(self, odoo_bin=None):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)',
                                    str(odoo_bin or self.odoo_bin)])
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        return process

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
        process = self.spawn(self.scratch / 'other-bin')
        self.helper('record', str(self.root), str(process.pid), '8070', str(self.odoo_bin))
        result = self.helper('show', str(self.root))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertFalse((state_dir(self.xdg, self.root) / 'server.json').exists())

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


class ServerLifecycleTests(unittest.TestCase):
    """start, stop and status of the main checkout (outside git: kind none) and a linked one."""
    setUp_fixture = lifecycle.LifecycleTests.setUp
    unchanged = lifecycle.LifecycleTests.unchanged

    def setUp(self):
        self.setUp_fixture()
        self.xdg = Path(self.env['XDG_RUNTIME_DIR'])
        self.python.write_text(self.python.read_text() + SERVE)
        self.port = free_ports(4)
        self.write_conf(self.root / 'dev/odoo.conf')

    def write_conf(self, path, extra=''):
        path.write_text(f'[options]\nhttp_port = {self.port}\n{extra}')

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
        match = re.fullmatch(rf'odoo19 start: http://localhost:{port} \(pid (\d+)\)\n', result.stderr)
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
        result = self.invoke(self.root, 'start', '--stop-after-init')
        self.assertEqual((result.returncode, result.stdout), (0, ''))
        pid = self.started(result, self.port)
        self.assertEqual(self.odoo_lines(), [self.odoo_call(self.root, f'--http-port={self.port}',
                                                            '--stop-after-init')])
        record = self.record(self.root)
        self.assertEqual((record['pid'], record['port'], record['project_root']),
                         (pid, self.port, str(self.root.resolve())))

    def test_main_start_without_conf_port_defaults_to_8069(self):
        (self.root / 'dev/odoo.conf').write_text('[options]\n')
        if not bindable(8069):
            self.skipTest('8069 is in use on this host')
        result = self.invoke(self.root, 'start', '--stop-after-init')
        self.assertEqual((result.returncode, result.stdout), (0, ''), result.stderr)
        self.started(result, 8069)
        self.assertEqual(self.odoo_lines(), [self.odoo_call(self.root, '--http-port=8069', '--stop-after-init')])

    def test_main_start_refuses_a_busy_conf_port_before_anything_runs(self):
        with busy(self.port):
            result = self.invoke(self.root, 'start', '--stop-after-init')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'Port {self.port} is in use; pass --http-port or stop the other server.\n'))
        self.unchanged()
        self.assertIsNone(self.record(self.root))

    def test_explicit_http_port_is_honored_in_every_form(self):
        explicit = self.port + 2
        for args in (('-p', str(explicit)), (f'-p{explicit}',), ('--http-port', str(explicit)),
                     (f'--http-port={explicit}',)):
            with self.subTest(args=args), busy(self.port):
                self.commands.unlink(missing_ok=True)
                result = self.invoke(self.root, 'start', *args, '--stop-after-init')
                self.assertEqual((result.returncode, result.stdout), (0, ''), result.stderr)
                self.started(result, explicit)
                self.assertEqual(self.odoo_lines(), [self.odoo_call(self.root, *args, '--stop-after-init')])
                self.assertEqual(self.record(self.root)['port'], explicit)
        with busy(explicit):
            self.commands.unlink()
            result = self.invoke(self.root, 'start', '--http-port', str(explicit))
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'Port {explicit} is in use; pass another --http-port or stop the other server.\n'))
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
                          f'port {self.port}.\n'))
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
            result = self.invoke(self.linked, 'start', '--stop-after-init')
        self.assertEqual((result.returncode, result.stdout), (0, ''), result.stderr)
        self.started(result, self.port + 2)
        # gevent: the first free port after the conf's gevent_port that is not the HTTP port.
        self.assertEqual(self.odoo_lines(), [' '.join([
            'odoo', str(self.source / 'odoo-bin'), '-c', str(self.conf), self.addons,
            f'--http-port={self.port + 2}', f'--gevent-port={self.port + 3}', '--stop-after-init'])])
        self.assertEqual(self.record(self.linked)['port'], self.port + 2)

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
        result = self.invoke(self.root, 'stop', '--all')
        self.assertEqual((result.returncode, result.stdout),  (2, ''))
        self.assertIn('Usage: ', result.stderr)
        self.assertIn('[--database]', result.stderr)
        self.unchanged()


class TestRunPortTests(unittest.TestCase):
    """test-module and verify-module give the Odoo test process its own free HTTP port."""
    setUp = lifecycle.LifecycleTests.setUp
    invoke = lifecycle.LifecycleTests.invoke

    def assert_test_port(self, line, prefix):
        match = re.fullmatch(re.escape(prefix) + r' --http-port=(\d+) (.*)', line)
        self.assertIsNotNone(match, line)
        port = int(match.group(1))
        self.assertGreaterEqual(port, 1024)
        self.assertTrue(bindable(port))
        return match.group(2)

    def test_test_and_verify_runs_pass_a_free_http_port(self):
        prefix = f'odoo {self.source / "odoo-bin"} -c {self.root / "dev/odoo.conf"}'
        tests = '-d cc_test_coffee -i coffee --without-demo --test-tags /coffee --stop-after-init'
        for command, args in (('test-module', ()), ('test-module', ('--compact',)),
                              ('verify-module', ()), ('verify-module', ('--compact',))):
            with self.subTest(command=command, args=args):
                self.commands.unlink(missing_ok=True)
                result = self.invoke(command, *args, 'coffee')
                self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
                lines = [line for line in self.commands.read_text().splitlines() if line.startswith('odoo ')]
                self.assertEqual(self.assert_test_port(lines[0], prefix), tests)
                # Install and update phases keep their command line.
                self.assertEqual(lines[1:], [] if command == 'test-module' else [
                    f'{prefix} -d cc_test_coffee_update -i coffee --without-demo --stop-after-init',
                    f'{prefix} -d cc_test_coffee_update -u coffee --stop-after-init'])


if __name__ == '__main__':
    unittest.main()
