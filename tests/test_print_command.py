"""v0.12.1 `start --print-command` and `restart --print-command` (S4, S5).

The odoo-bin command line `start` would exec, printed as one shell-quoted line without side
effects: no database service, no Odoo run (not even `odoo-bin --version`), no server record, no
server log. The lifecycle fixture (fake docker/python recording every argv, private
XDG_RUNTIME_DIR); detached fake servers listen like Odoo (test_menu.SERVING) and are killed in
cleanup; the linked worktree comes from the shared-conf fixture.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import re
import shlex
import socket
import subprocess
import sys
import unittest

import test_lifecycle as lifecycle
import test_menu as menu
import test_shared_conf as shared

ROOT = lifecycle.STAGE
LATE = '--print-command must be the first argument.\n'


class PrintCommandTests(menu.MenuFixture):
    record = menu.DetachTests.record
    kill_recorded = menu.DetachTests.kill_recorded
    kill = menu.DetachTests.kill

    def setUp(self):
        super().setUp()
        # odoo-bin --version is logged too: a print run must not run Odoo at all.
        self.python.write_text(self.python.read_text().replace(
            'if [ "$2" = "--version" ]; then', 'if [ "$2" = "--version" ]; then printf "version\\n" >> "$FAKE_LOG";', 1)
            + menu.SERVE + menu.DIE)
        (self.source / 'odoo-bin').write_text(menu.SERVING)
        self.port = lifecycle.quiet_ports(3)
        self.conf = self.root / 'dev/odoo.conf'
        self.conf.write_text(lifecycle.conf_text(f'http_port = {self.port}\n'))
        self.env.update(OASIS_DETACH_WAIT='5')
        self.server_log = self.root.resolve() / 'dev/logs/odoo19/server.log'
        self.checkout = self.root
        self.addCleanup(self.kill_recorded)

    def run_in(self, root, *args, program='oasis'):
        return subprocess.run([sys.executable, '-B', str(ROOT / program), '--project', str(root), *args],
                              text=True, cwd=root, env=self.env, capture_output=True,
                              stdin=subprocess.DEVNULL, timeout=60)

    def line(self, *args):
        return shlex.join([str(self.python), str(self.source / 'odoo-bin'), *args]) + '\n'

    def logged(self, printed):
        """The fake python's log line of the argv a printed line names."""
        return ' '.join(['odoo', *shlex.split(printed)[1:]])

    def assert_no_side_effects(self, root=None):
        """No docker, no Odoo (not even --version), no record, no server log."""
        root = root or self.root
        self.assertEqual(self.log(), '')
        self.assertEqual(self.record_of(root), '')
        self.assertFalse((root / 'dev/logs').exists())
        self.assertFalse((self.root / 'dev/logs').exists())

    def record_of(self, root):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/runtime_state.py'), 'show', str(root)],
                                capture_output=True, text=True, env=self.env)
        return result.stdout

    def detach(self, root, *args):
        result = self.run_in(root, 'start', '--detach', *args)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        pid = int(re.match(r'pid=(\d+) ', result.stdout).group(1))
        self.addCleanup(self.kill, pid)
        return pid

    def linked_layout(self):
        shared.shared_layout(self)
        self.addons = f'--addons-path={self.enterprise},{self.linked},{self.odoo_addons}'
        self.addCleanup(lambda: self.kill_recorded_of(self.linked))

    def kill_recorded_of(self, root):
        match = re.match(r'pid=(\d+) ', self.record_of(root))
        if match:
            self.kill(int(match.group(1)))

    # S4: start --print-command

    def test_start_prints_the_command_of_the_main_checkout_without_side_effects(self):
        expected = self.line('-c', str(self.conf), f'--http-port={self.port}', '-d', 'cc_dev_coffee',
                             '--dev', 'xml')
        for program in ('oasis',):
            for leading in (('--print-command',), ('--print-command', '--detach')):
                with self.subTest(program=program, leading=leading):
                    result = self.run_in(self.root, 'start', *leading, '-d', 'cc_dev_coffee', '--dev', 'xml',
                                         program=program)
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, ''))
                    self.assert_no_side_effects()
        # An explicit port is passed as given, never repeated; the project path is quoted.
        result = self.run_in(self.root, 'start', '--print-command', '--http-port', str(self.port + 1))
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.line('-c', str(self.conf), '--http-port', str(self.port + 1)), ''))
        self.assertIn("'", result.stdout)
        self.assert_no_side_effects()

    def test_start_prints_the_command_of_a_linked_worktree_without_secrets(self):
        self.linked_layout()
        with socket.socket() as holder:
            holder.bind(('127.0.0.1', self.http_port))
            holder.listen()
            result = self.run_in(self.linked, 'start', '--print-command', '--workers=2')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout, self.line(
            '-c', str(self.conf), self.addons, f'--http-port={self.http_port + 1}',
            f'--gevent-port={self.gevent_port + 1}', '--workers=2'))
        self.assertNotIn(shared.SECRET, result.stdout)
        self.assert_no_side_effects(self.linked)

    def test_password_options_are_never_printed(self):
        result = self.run_in(self.root, 'start', '--print-command', '-w', 'one', '-wtwo', '--db_password=three',
                             '--db_pa', 'four', '--smtp-password', 'five', '--smtp-pass=six', '--db_port=5433')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout, self.line(
            '-c', str(self.conf), f'--http-port={self.port}', '-w', '***', '-w***', '--db_password=***',
            '--db_pa', '***', '--smtp-password', '***', '--smtp-pass=***', '--db_port=5433'))
        self.assert_no_side_effects()

    def test_password_masking_around_the_separator_and_without_a_value(self):
        # Before `--` a password option takes the next word as its value, `--` included (as optparse
        # reads it); after `--` the words are not Odoo options and are printed as given.
        for args, shown in (
                (('-w', 'Secret1', '--', '-w', 'Secret2'), ('-w', '***', '--', '-w', 'Secret2')),
                (('--db_password', 'Secret1', '--', '--db_password=Secret2'),
                 ('--db_password', '***', '--', '--db_password=Secret2')),
                (('-w', '--', 'x'), ('-w', '***', 'x')),
                # A password option without a value has nothing to hide: it reaches Odoo as given.
                (('--workers=0', '-w'), ('--workers=0', '-w')),
                (('--smtp-password',), ('--smtp-password',))):
            with self.subTest(args=args):
                result = self.run_in(self.root, 'start', '--print-command', *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (0, self.line('-c', str(self.conf), f'--http-port={self.port}', *shown), ''))
                self.assertNotIn('Secret1', result.stdout)
        self.assert_no_side_effects()

    def test_start_prints_informational_and_batch_commands(self):
        result = self.run_in(self.root, 'start', '--print-command', '--help')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.line('-c', str(self.conf), '--help'), ''))
        result = self.run_in(self.root, 'start', '--print-command', '--stop-after-init', '-u', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        words = shlex.split(result.stdout)
        self.assertEqual(result.stdout.count('\n'), 1)
        self.assertEqual(words[:4] + words[6:], [str(self.python), str(self.source / 'odoo-bin'), '-c',
                                                 str(self.conf), '--stop-after-init', '-u', 'coffee'])
        self.assertRegex(' '.join(words[4:6]), r'^--http-port=\d+ --gevent-port=\d+$')
        self.assert_no_side_effects()

    def test_start_print_errors_keep_their_messages(self):
        with socket.socket() as holder:
            holder.bind(('127.0.0.1', self.port))
            holder.listen()
            result = self.run_in(self.root, 'start', '--print-command')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            2, '', f'Port {self.port} is in use by another process; pass --http-port or stop that process.\n'))
        for args, message in (
                (('-d', 'other_db'), 'Managed databases must use cc_dev_<name> or cc_test_<name>: other_db\n'),
                (('--http-port=0',), 'Invalid HTTP port: 0\n'),
                (('--detach', '--stop-after-init'),
                 '--detach starts a server; it cannot be combined with --stop-after-init.\n')):
            with self.subTest(args=args):
                result = self.run_in(self.root, 'start', '--print-command', *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', message))
        self.assert_no_side_effects()
        self.env['FAKE_SERVE'] = '1'
        pid = self.detach(self.root)
        before = self.log()
        result = self.run_in(self.root, 'start', '--print-command')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            2, '', f'Odoo is already running for this checkout: pid {pid}, port {self.port}; run oasis stop first.\n'))
        self.assertEqual(self.log(), before)

    def test_print_command_elsewhere_is_refused_before_anything_runs(self):
        for command, args in (('start', ('-d', 'cc_dev_coffee', '--print-command')),
                              ('start', ('--detach', '--print-command')),
                              ('restart', ('--workers=0', '--print-command'))):
            with self.subTest(command=command, args=args):
                result = self.run_in(self.root, command, *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', LATE))
                self.assert_no_side_effects()
        # After `--` it is not an option of start: it reaches Odoo as given.
        result = self.run_in(self.root, 'start', '--print-command', '--', '--print-command')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.line('-c', str(self.conf), f'--http-port={self.port}', '--', '--print-command'), ''))

    # S4: restart --print-command

    def test_restart_prints_what_it_would_pass_with_a_running_server(self):
        self.env['FAKE_SERVE'] = '1'
        other = self.port + 1
        pid = self.detach(self.root, f'--http-port={other}', '-d', 'cc_dev_coffee')
        before, log = self.log(), self.server_log.read_bytes()
        for args, expected in (
                (('--dev', 'xml'), ('-c', str(self.conf), f'--http-port={other}', '-d', 'cc_dev_coffee', '--dev', 'xml')),
                (('-d', 'cc_test_coffee', '--http-port', str(self.port)),
                 ('-c', str(self.conf), '-d', 'cc_test_coffee', '--http-port', str(self.port))),
                ((f'--http-port={other}',), ('-c', str(self.conf), '-d', 'cc_dev_coffee', f'--http-port={other}'))):
            with self.subTest(args=args):
                result = self.run_in(self.root, 'restart', '--print-command', *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, self.line(*expected), ''))
                # Nothing was stopped or started.
                self.assertEqual(self.record(), f'pid={pid} port={other}\n')
                self.assertEqual(self.log(), before)
                self.assertEqual(self.server_log.read_bytes(), log)
        printed = self.run_in(self.root, 'restart', '--print-command', '--workers=0').stdout
        # PRESERVE: restart execs exactly that argv.
        result = self.run_in(self.root, 'restart', '--workers=0')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(self.odoo_lines()[-1], self.logged(printed))

    def test_restart_prints_start_command_without_a_server(self):
        result = self.run_in(self.root, 'restart', '--print-command', '-d', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.line('-c', str(self.conf), f'--http-port={self.port}', '-d', 'cc_dev_coffee'), ''))
        self.assert_no_side_effects()

    def test_restart_in_a_linked_worktree_keeps_the_ports_the_stopped_server_frees(self):
        self.linked_layout()
        self.env['FAKE_SERVE'] = '1'
        self.detach(self.linked)
        gevent = self.gevent_port + 1
        before = self.log()
        # The running server holds its gevent port: restart frees it, so it is the one printed.
        with socket.socket() as holder:
            holder.bind(('127.0.0.1', gevent))
            holder.listen()
            result = self.run_in(self.linked, 'restart', '--print-command')
        printed = result.stdout
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(printed, self.line('-c', str(self.conf), self.addons,
                                                  f'--gevent-port={gevent}', f'--http-port={self.http_port + 1}'))
        self.assertNotIn(shared.SECRET, result.stdout)
        self.assertEqual(self.log(), before)
        # PRESERVE: restart execs exactly that argv.
        result = self.run_in(self.linked, 'restart')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(self.odoo_lines()[-1], self.logged(printed))

    def test_restart_in_an_odoo_15_linked_worktree_keeps_its_longpolling_port(self):
        # v0.15.0 S2: the running server's second port is read from its command line by the
        # series' option (--longpolling-port on 15.0), as --gevent-port is on 19.0.
        lifecycle.use_odoo_15(self)
        shared.shared_layout(self, shared.SHARED_PROFILE.replace("odoo_version = '19.0'", "odoo_version = '15.0'", 1))
        self.conf.write_text(self.conf.read_text().replace('gevent_port =', 'longpolling_port =', 1))
        self.addons = f'--addons-path={self.enterprise},{self.linked},{self.odoo_addons}'
        self.addCleanup(lambda: self.kill_recorded_of(self.linked))
        self.env['FAKE_SERVE'] = '1'
        self.detach(self.linked)
        longpolling = self.gevent_port + 1
        self.assertIn(f' --longpolling-port={longpolling}', self.odoo_lines()[-1])
        before = self.log()
        # The running server holds its longpolling port: restart frees it, so it is the one printed.
        with socket.socket() as holder:
            holder.bind(('127.0.0.1', longpolling))
            holder.listen()
            result = self.run_in(self.linked, 'restart', '--print-command')
        printed = result.stdout
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(printed, self.line('-c', str(self.conf), self.addons,
                                            f'--longpolling-port={longpolling}', f'--http-port={self.http_port + 1}'))
        self.assertEqual(self.log(), before)
        # PRESERVE: restart execs exactly that argv (the stopped server's port is free again).
        result = self.run_in(self.linked, 'restart')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(self.odoo_lines()[-1], self.logged(printed))

    def test_restart_print_errors_keep_their_messages(self):
        self.env['FAKE_SERVE'] = '1'
        pid = self.detach(self.root)
        before = self.log()
        usage = f'Usage: {menu.ENTRY} restart [odoo options]\n'
        for args, message in (
                (('--detach',), usage), (('--version',), usage),
                (('--stop-after-init',), 'restart starts a server; it cannot be combined with --stop-after-init.\n'),
                (('-d', 'other_db'), 'Managed databases must use cc_dev_<name> or cc_test_<name>: other_db\n'),
                (('--http-port=0',), 'Invalid HTTP port: 0\n')):
            with self.subTest(args=args):
                result = self.run_in(self.root, 'restart', '--print-command', *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', message))
                self.assertEqual(self.record(), f'pid={pid} port={self.port}\n')
                self.assertEqual(self.log(), before)
        result = self.run_in(self.root, 'restart', '--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn('--print-command', result.stdout)

    def test_restart_print_help_with_other_options_prints_the_usage(self):
        usage = f'Usage: {menu.ENTRY} restart [odoo options]\n'
        for args in (('--help',), ('--help', '-d', 'cc_dev_coffee'), ('--workers=0', '-h'), ('-h', '--dev', 'xml')):
            with self.subTest(args=args):
                result = self.run_in(self.root, 'restart', '--print-command', *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', usage))
                self.assert_no_side_effects()
        # PRESERVE: without --print-command, --help with other options is the same refusal.
        result = self.run_in(self.root, 'restart', '--help', '-d', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', usage))

    def test_restart_print_refuses_a_busy_port_that_is_not_the_servers(self):
        self.env['FAKE_SERVE'] = '1'
        pid = self.detach(self.root)
        before, log = self.log(), self.server_log.read_bytes()
        busy = self.port + 2
        message = f'Port {busy} is in use by another process; pass another --http-port or stop that process.\n'
        with socket.socket() as holder:
            holder.bind(('127.0.0.1', busy))
            holder.listen()
            for args in (('--http-port', str(busy)), (f'--http-port={busy}',), ('-p', str(busy))):
                with self.subTest(args=args):
                    result = self.run_in(self.root, 'restart', '--print-command', *args)
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', message))
                    self.assertEqual(self.record(), f'pid={pid} port={self.port}\n')
                    self.assertEqual(self.log(), before)
                    self.assertEqual(self.server_log.read_bytes(), log)

    def test_restart_print_is_quiet_when_the_recorded_server_vanishes_before_its_ports_are_read(self):
        self.env['FAKE_SERVE'] = '1'
        self.detach(self.root)
        # A python3 on PATH that, after the first `runtime_state.py show`, kills the server it
        # reported and waits until its /proc entry is gone: the race between the record read and
        # the read of the server's command line, made certain.
        gone = self.root / 'vanished'
        shim = self.bindir / 'python3'
        shim.write_text(f'''#!/bin/sh
if [ "$4" = show ] && [ ! -e "{gone}" ]; then
  out=$("{sys.executable}" "$@") || exit $?
  printf '%s\\n' "$out"
  pid=${{out#pid=}}; pid=${{pid%% *}}
  if tr '\\0' '\\n' < "/proc/$pid/cmdline" | grep -qxF "{self.source / 'odoo-bin'}"; then kill -9 "$pid"; fi
  i=0
  while [ -e "/proc/$pid" ] && [ $i -lt 100 ]; do sleep 0.05; i=$((i + 1)); done
  if [ ! -e "/proc/$pid" ]; then echo gone > "{gone}"; else echo alive > "{gone}"; fi
  exit 0
fi
exec "{sys.executable}" "$@"
''')
        shim.chmod(0o755)
        result = self.run_in(self.root, 'restart', '--print-command')
        self.assertEqual(gone.read_text(), 'gone\n')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.line('-c', str(self.conf), f'--http-port={self.port}'), ''))

    # S5 PRESERVE: start's argv is unchanged.

    def test_start_argv_is_unchanged_in_a_linked_worktree(self):
        self.linked_layout()
        with socket.socket() as holder:
            holder.bind(('127.0.0.1', self.http_port + 1))
            holder.listen()
            printed = self.run_in(self.linked, 'start', '--print-command', '--workers=0').stdout
            result = self.run_in(self.linked, 'start', '--workers=0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.odoo_lines(), [' '.join([
            'odoo', str(self.source / 'odoo-bin'), '-c', str(self.conf), self.addons,
            f'--http-port={self.http_port + 2}', f'--gevent-port={self.gevent_port + 1}', '--workers=0'])])
        self.assertEqual(self.odoo_lines()[-1], self.logged(printed))


if __name__ == '__main__':
    unittest.main()
