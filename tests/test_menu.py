"""v0.9.0 action panel core: the action catalog, `oasis menu` and `start --detach` (S3-S5, S7, S8).

The lifecycle fixture (fake docker/python recording every argv, private XDG_RUNTIME_DIR); the
terminal menu runs on a pseudo-terminal created by the test. Detached fake servers are killed in
cleanup.
"""
from pathlib import Path
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import time
import unittest

import test_lifecycle as lifecycle

ROOT = lifecycle.STAGE
ENTRY = str((ROOT / 'oasis').resolve())
ACTIONS = ['server.start', 'server.stop', 'server.logs', 'server.status', 'server.stop_database',
           'modules.install', 'modules.update', 'modules.status', 'modules.init_dev', 'modules.overview',
           'tests.module', 'tests.class', 'tests.reuse',
           'maintenance.create_database', 'maintenance.drop_database', 'maintenance.trash',
           'maintenance.trash_restore', 'maintenance.trash_empty', 'maintenance.gc', 'maintenance.gc_apply', 'maintenance.doctor', 'maintenance.migrate_plan',
           'maintenance.migrate', 'maintenance.worktree']
ACTION_KEYS = ['argv', 'command', 'confirm', 'destructive', 'group', 'id', 'inputs', 'kind', 'label',
               'terminal_only', 'user_run']
INPUT_KEYS = ['allow_new', 'default', 'error', 'hint', 'id', 'kind', 'label', 'pattern', 'required',
              'source']
MODULE_INPUT = {'id': 'module', 'label': 'Module', 'kind': 'choice', 'source': 'modules',
                'required': True, 'allow_new': False, 'pattern': None, 'error': None, 'default': None,
                'hint': None}
ONLY_INPUT = {'id': 'only', 'label': 'Test class (Class or Class.method)', 'kind': 'text',
              'source': None, 'required': True, 'allow_new': False,
              'pattern': r'^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$',
              'error': '--only takes a test class or Class.method.', 'default': None, 'hint': None}
WAITING = 'Listing databases (this may start the database service)...'
NO_TERMINAL = ('oasis menu needs a terminal (stdin is not a TTY); run it yourself, or print the '
               'actions as JSON with --catalog.\n')
# A fake odoo-bin that listens like Odoo (on --http-interface, else the conf's http_interface;
# 127.0.0.1 for none, 0.0.0.0 or ::, so a test never listens beyond loopback), says it serves and
# stays alive until killed. FAKE_LISTEN_HOST overrides the address, FAKE_NO_LISTEN binds nothing.
SERVING = r'''import configparser, os, socket, sys, time
args, host, port = sys.argv[1:], None, None
for index, arg in enumerate(args):
    if arg.startswith('--http-port='):
        port = int(arg.split('=', 1)[1])
    elif arg == '--http-interface':
        host = args[index + 1]
    elif arg.startswith('--http-interface='):
        host = arg.split('=', 1)[1]
if host is None and '-c' in args:
    conf = configparser.RawConfigParser()
    conf.read(args[args.index('-c') + 1])
    host = conf.get('options', 'http_interface', fallback='')
host = os.environ.get('FAKE_LISTEN_HOST') or (host if host not in ('', '0.0.0.0', '::') else '127.0.0.1')
if not os.environ.get('FAKE_NO_LISTEN'):
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((host, port))
    listener.listen()
print("serving", flush=True)
while True:
    time.sleep(0.1)
'''
SERVE = f'if [ -n "${{FAKE_SERVE:-}}" ]; then exec "{sys.executable}" "$@"; fi\n'
DIE = 'if [ -n "${FAKE_DIE:-}" ]; then echo "address already in use" >&2; exit 3; fi\n'


class MenuFixture(unittest.TestCase):
    setUp_fixture = lifecycle.LifecycleTests.setUp
    unchanged = lifecycle.LifecycleTests.unchanged

    def setUp(self):
        self.setUp_fixture()
        self.project = str(self.root.resolve())
        docker = self.bindir / 'docker'
        # list-databases prints FAKE_DATABASES (space separated).
        docker.write_text(docker.read_text().replace(
            'esac\n', '  *"SELECT datname FROM pg_database"*) for name in ${FAKE_DATABASES:-}; do '
            'echo "$name"; done ;;\nesac\n', 1))

    def oasis(self, *args, program='oasis'):
        return subprocess.run([sys.executable, '-B', str(ROOT / program), '--project', str(self.root), *args],
                              text=True, cwd=self.root, env=self.env, capture_output=True,
                              stdin=subprocess.DEVNULL, timeout=60)

    def terminal(self, answers, *args):
        """oasis menu with a pseudo-terminal on stdin that already holds the answers."""
        master, slave = os.openpty()
        try:
            process = subprocess.Popen(
                [sys.executable, '-B', str(ROOT / 'oasis'), '--project', str(self.root), 'menu', *args],
                text=True, cwd=self.root, env=self.env, stdin=slave, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        finally:
            os.close(slave)
        try:
            os.write(master, answers.encode())
            stdout, stderr = process.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            self.fail(f'menu waited for more input:\n{stdout}\n{stderr}')
        finally:
            os.close(master)
        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)

    def command(self, *words):
        return 'Command: ' + shlex.join([ENTRY, '--project', self.project, *words]) + '\n'

    def log(self):
        return self.commands.read_text() if self.commands.exists() else ''


class CatalogTests(MenuFixture):
    def catalog(self):
        result = self.oasis('menu', '--catalog')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        return json.loads(result.stdout)

    def test_catalog_is_json_with_every_action_and_runs_nothing(self):
        catalog = self.catalog()
        self.assertEqual(sorted(catalog), ['actions', 'catalog_version', 'entrypoint', 'groups', 'project',
                                           'server_log', 'sources'])
        self.assertEqual((catalog['catalog_version'], catalog['project'], catalog['entrypoint']),
                         (1, self.project, ENTRY))
        self.assertEqual(catalog['server_log'], str(self.root.resolve() / 'dev/logs/odoo19/server.log'))
        self.assertEqual(catalog['groups'], [
            {'id': 'server', 'label': 'Server'}, {'id': 'modules', 'label': 'Modules'},
            {'id': 'tests', 'label': 'Tests'}, {'id': 'maintenance', 'label': 'Databases and maintenance'}])
        self.assertEqual(catalog['sources'], {
            'modules': {'choices': ['coffee']},
            'databases': {'argv': [ENTRY, '--project', self.project, 'list-databases'], 'waiting': WAITING}})
        self.assertEqual([action['id'] for action in catalog['actions']], ACTIONS)
        groups = {group['id'] for group in catalog['groups']}
        for action in catalog['actions']:
            with self.subTest(action=action['id']):
                self.assertEqual(sorted(action), ACTION_KEYS)
                self.assertIn(action['group'], groups)
                self.assertTrue(action['id'].startswith(action['group'] + '.'))
                names = [item['id'] for item in action['inputs']]
                for item in action['inputs']:
                    self.assertEqual(sorted(item), INPUT_KEYS)
                    self.assertIn(item['kind'], ('choice', 'text', 'boolean'))
                    self.assertIn(item['source'], (None, 'modules', 'databases'))
                for token in action['argv']:
                    if isinstance(token, dict):
                        self.assertTrue(set(token) in ({'input'}, {'input', 'option'}, {'input', 'flag'},
                                                       {'compact'}), token)
                        if 'input' in token:
                            self.assertIn(token['input'], names)
                    else:
                        self.assertIsInstance(token, str)
                self.assertIn(action['confirm'], (None, 'yes', 'database'))
                self.assertEqual(action['destructive'], action['confirm'] is not None)
                if action['kind'] == 'command':
                    self.assertEqual(action['argv'][:4], [ENTRY, '--project', self.project, action['command']])
                else:
                    self.assertEqual((action['kind'], action['command'], action['argv']),
                                     ('log', None, ['tail', '-n', '200', catalog['server_log']]))
        self.unchanged()
        self.assertFalse((self.root / 'dev/logs').exists())

    def test_catalog_entries_declare_their_command_inputs_and_flags(self):
        actions = {action['id']: action for action in self.catalog()['actions']}
        prefix = [ENTRY, '--project', self.project]
        self.assertEqual(actions['tests.class'], {
            'id': 'tests.class', 'group': 'tests', 'label': 'Test one class or method', 'kind': 'command',
            'command': 'test-module',
            'argv': [*prefix, 'test-module', {'compact': '--compact'}, {'input': 'only', 'option': '--only'},
                     {'input': 'module'}],
            'inputs': [MODULE_INPUT, ONLY_INPUT], 'destructive': False, 'confirm': None, 'user_run': False,
            'terminal_only': False})
        self.assertEqual(actions['server.start']['argv'], [*prefix, 'start', '--detach',
                                                           {'input': 'database', 'option': '-d'}])
        self.assertEqual(actions['modules.install']['argv'], [
            *prefix, 'install-module', {'input': 'demo', 'flag': '--with-demo'}, {'input': 'module'},
            {'input': 'database'}])
        self.assertEqual([item['id'] for item in actions['modules.install']['inputs']], ['module', 'database', 'demo'])
        self.assertEqual(actions['modules.install']['inputs'][2]['default'], False)
        self.assertEqual(actions['tests.reuse']['argv'], [
            *prefix, 'test-module', {'compact': '--compact'}, '--reuse', {'input': 'only', 'option': '--only'},
            {'input': 'module'}])
        self.assertFalse(actions['tests.reuse']['inputs'][1]['required'])
        self.assertEqual(actions['modules.update']['argv'], [
            *prefix, 'update-module', {'compact': '--compact'}, {'input': 'module'}, {'input': 'database'}])
        self.assertEqual((actions['maintenance.drop_database']['confirm'], actions['maintenance.gc_apply']['confirm'],
                          actions['server.stop_database']['confirm'], actions['maintenance.migrate']['confirm'],
                          actions['maintenance.trash_empty']['confirm']),
                         ('database', 'yes', 'yes', 'yes', 'yes'))
        # The trash (S2): drop moves to it; list, restore and empty it.
        self.assertEqual(actions['maintenance.drop_database']['label'], 'Move a database to the trash')
        self.assertEqual(actions['maintenance.trash'], {
            'id': 'maintenance.trash', 'group': 'maintenance', 'label': 'List trash', 'kind': 'command',
            'command': 'trash', 'argv': [*prefix, 'trash'], 'inputs': [], 'destructive': False, 'confirm': None,
            'user_run': False, 'terminal_only': False})
        self.assertEqual(actions['maintenance.trash_restore'], {
            'id': 'maintenance.trash_restore', 'group': 'maintenance', 'label': 'Restore from trash',
            'kind': 'command', 'command': 'trash', 'argv': [*prefix, 'trash', 'restore', {'input': 'trash'}],
            'inputs': [{'id': 'trash', 'label': 'Trash name (as listed by List trash)', 'kind': 'text',
                        'source': None, 'required': True, 'allow_new': False, 'pattern': '^[A-Za-z0-9_]+$',
                        'error': 'Database name must use only letters, numbers, and underscores.',
                        'default': None, 'hint': None}],
            'destructive': False, 'confirm': None, 'user_run': False, 'terminal_only': False})
        self.assertEqual(actions['maintenance.trash_empty'], {
            'id': 'maintenance.trash_empty', 'group': 'maintenance', 'label': 'Empty trash', 'kind': 'command',
            'command': 'gc', 'argv': [*prefix, 'gc', '--apply', '--trash',
                                      {'input': 'older_than', 'option': '--older-than'}],
            'inputs': [{'id': 'older_than', 'label': 'Dropped at least this many days ago', 'kind': 'text',
                        'source': None, 'required': False, 'allow_new': False, 'pattern': '^[0-9]+$',
                        'error': 'Days must be a whole number.', 'default': None, 'hint': 'Enter for 7'}],
            'destructive': True, 'confirm': 'yes', 'user_run': False, 'terminal_only': False})
        self.assertEqual([key for key, action in actions.items() if action['user_run']],
                         ['maintenance.migrate', 'maintenance.worktree'])
        self.assertEqual([key for key, action in actions.items() if action['terminal_only']], ['modules.init_dev'])
        self.assertEqual(actions['maintenance.migrate_plan']['argv'], [*prefix, 'migrate', '--plan'])
        # Read-only, from source: no database input, no confirmation.
        self.assertEqual(actions['modules.overview'], {
            'id': 'modules.overview', 'group': 'modules', 'label': "Show a module's overview from source",
            'kind': 'command', 'command': 'module-info', 'argv': [*prefix, 'module-info', {'input': 'module'}],
            'inputs': [MODULE_INPUT], 'destructive': False, 'confirm': None, 'user_run': False,
            'terminal_only': False})

    def test_catalog_server_log_follows_the_configured_logs_directory(self):
        profile = self.root / '.odoo19-agent.toml'
        profile.write_text(profile.read_text() + "logs = '../logs'\n")
        self.assertEqual(self.catalog()['server_log'], str(self.root.resolve().parent / 'logs/main/server.log'))
        self.assertFalse((self.root.parent / 'logs').exists())

    def test_menu_is_a_public_command_with_help(self):
        result = self.oasis('menu', '--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(f'Usage: {ENTRY} menu [--catalog]\n'), result.stdout)
        result = self.oasis('menu', '--bogus')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', f'Usage: {ENTRY} menu [--catalog]\n'))
        self.unchanged()


class TerminalMenuTests(MenuFixture):
    def test_menu_refuses_without_a_terminal(self):
        for program in ('oasis', 'odoo19'):
            with self.subTest(program=program):
                result = self.oasis('menu', program=program)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, '', NO_TERMINAL.replace('oasis menu', f'{program} menu')))
        self.unchanged()

    def test_menu_shows_the_command_then_runs_it(self):
        result = self.terminal('3\n1\n1\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        for line in ('  1) Server\n', '  2) Modules\n', '  3) Tests\n', '  4) Databases and maintenance\n',
                     '  1) Test a module\n', '  2) Test one class or method\n', '  1) coffee\n'):
            self.assertIn(line, result.stdout)
        self.assertTrue(result.stdout.endswith(self.command('test-module', 'coffee')), result.stdout)
        self.assertRegex(self.log(), r'-d cc_test_coffee_r[0-9a-f]{6} -i coffee --without-demo --test-tags /coffee ')

    def test_quit_runs_nothing(self):
        result = self.terminal('q\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.unchanged()

    def test_invalid_answers_are_asked_again(self):
        result = self.terminal('9\n3\n2\nteh\n5\n1\nTest Order\nTestOrder\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn('Choose a number from 1 to 4, or q.\n', result.stdout)
        self.assertEqual(result.stdout.count('Choose a number from 1 to 1, or a name from the list.\n'), 2)
        self.assertIn('--only takes a test class or Class.method.\n', result.stdout)
        self.assertTrue(result.stdout.endswith(self.command('test-module', '--only', 'TestOrder', 'coffee')))
        self.assertIn(' --test-tags /coffee:TestOrder ', self.log())

    def test_databases_are_listed_with_a_waiting_message_and_defaults_apply(self):
        result = self.terminal('2\n1\n1\n\ny\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn(WAITING + '\n', result.stdout)
        self.assertIn('No databases found.\n', result.stdout)
        self.assertTrue(result.stdout.endswith(self.command('install-module', '--with-demo', 'coffee')))
        # list-databases started the database service (S7), then install-module ran.
        self.assertIn('up -d --wait --wait-timeout 60 db', self.log())
        self.assertIn('-d cc_dev_coffee -i coffee --with-demo --stop-after-init', self.log())

    def test_a_number_outside_the_database_list_is_asked_again(self):
        self.env.update(FAKE_DATABASES='cc_dev_coffee', FAKE_EXISTS='1')
        result = self.terminal('2\n2\n1\n7\n0\n1\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertEqual(result.stdout.count('Choose a number from 1 to 1, or type a name.\n'), 2, result.stdout)
        self.assertTrue(result.stdout.endswith(self.command('update-module', 'coffee', 'cc_dev_coffee')))
        self.assertNotIn(' -d 7 ', self.log())
        self.assertIn('-d cc_dev_coffee -u coffee --stop-after-init', self.log())

    def test_a_listed_name_made_of_digits_is_taken_as_written(self):
        self.env.update(FAKE_DATABASES='cc_dev_coffee 2024', FAKE_EXISTS='1')
        for answer, database in (('2024', '2024'), ('2', '2024'), ('1', 'cc_dev_coffee')):
            with self.subTest(answer=answer):
                result = self.terminal(f'2\n3\n1\n{answer}\n')
                self.assertNotIn('Choose a number', result.stdout)
                self.assertIn(self.command('module-status', 'coffee', database), result.stdout)

    def test_a_number_is_not_a_database_name_when_none_is_listed(self):
        result = self.terminal('2\n1\n1\n3\n\nn\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn('No databases found.\n', result.stdout)
        self.assertIn('No database is listed: type a name.\n', result.stdout)
        self.assertTrue(result.stdout.endswith(self.command('install-module', 'coffee')))
        self.assertIn('-d cc_dev_coffee -i coffee', self.log())

    def test_drop_requires_typing_the_database_name(self):
        self.env.update(FAKE_DATABASES='cc_dev_coffee cc_test_other')
        # Only cc_dev_coffee exists, so its trash name is free.
        Path(str(self.commands) + '.databases').write_text('cc_dev_coffee\n')
        result = self.terminal('4\n2\n1\nn\ncc_dev_coffe\n')
        self.assertEqual((result.returncode, result.stderr), (1, ''), result.stdout)
        self.assertIn('  1) cc_dev_coffee\n  2) cc_test_other\n', result.stdout)
        self.assertIn(self.command('drop-database', 'cc_dev_coffee'), result.stdout)
        self.assertTrue(result.stdout.endswith('Not confirmed: nothing ran.\n'), result.stdout)
        self.assertNotIn('ALTER DATABASE', self.log())
        result = self.terminal('4\n2\n1\nn\ncc_dev_coffee\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        # The command first, then the confirmation (the typed answer echoes on the terminal only).
        self.assertRegex(result.stdout, re.escape(self.command('drop-database', 'cc_dev_coffee') +
                                                  'Type the database name to confirm: database=cc_dev_coffee\n') +
                         r'size=unknown\nsessions=0\nfilestore=none\ntrash=(cc_dev_coffee_trash_\d{8}_\d{6})\n'
                         r'Database moved to trash: cc_dev_coffee -> \1\n'
                         r'Restore it with: oasis trash restore \1\n\Z')
        self.assertIn('ALTER DATABASE "cc_dev_coffee" RENAME TO "cc_dev_coffee_trash_', self.log())
        self.assertNotIn('dropdb', self.log())

    def test_yes_confirmation_for_stopping_the_database_service(self):
        result = self.terminal('1\n5\nno\n')
        self.assertEqual((result.returncode, result.stderr), (1, ''), result.stdout)
        self.assertIn(self.command('stop', '--database'), result.stdout)
        self.assertIn('Type yes to confirm: ', result.stdout)
        self.assertTrue(result.stdout.endswith('Not confirmed: nothing ran.\n'))
        self.unchanged()
        result = self.terminal('1\n5\nyes\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertTrue(self.log().endswith(' stop db\n'), self.log())

    def test_missing_server_log(self):
        result = self.terminal('1\n3\n')
        self.assertEqual((result.returncode, result.stderr), (1, ''))
        self.assertTrue(result.stdout.endswith(
            f'No server log yet: {self.root.resolve() / "dev/logs/odoo19/server.log"}\n'), result.stdout)
        self.unchanged()


class DetachTests(MenuFixture):
    def setUp(self):
        super().setUp()
        self.python.write_text(self.python.read_text() + SERVE + DIE)
        (self.source / 'odoo-bin').write_text(SERVING)
        self.port = lifecycle.quiet_ports(2)
        (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text(f'http_port = {self.port}\n'))
        self.env.update(OASIS_DETACH_WAIT='0.5')
        self.server_log = self.root.resolve() / 'dev/logs/odoo19/server.log'
        self.addCleanup(self.kill_recorded)

    def record(self):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/runtime_state.py'), 'show', str(self.root)],
                                capture_output=True, text=True, env=self.env)
        return result.stdout

    def kill_recorded(self):
        match = re.match(r'pid=(\d+) ', self.record())
        if match:
            self.kill(int(match.group(1)))

    def kill(self, pid):
        """SIGKILL pid only while it still runs the fake odoo-bin (never a reused pid)."""
        try:
            argv = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        except OSError:
            return
        if os.fsencode(str(self.source / 'odoo-bin')) not in argv:
            return
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def start(self, *args):
        return self.invoke('start', *args)

    def invoke(self, command, *args):
        """The project wrapper, bounded: a start that never returns fails instead of hanging."""
        path = self.root / 'dev/scripts' / command
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / 'project-wrappers' / command).read_bytes())
        try:
            return subprocess.run(['bash', str(path), *args], text=True, cwd=self.root, env=self.env,
                                  capture_output=True, stdin=subprocess.DEVNULL, timeout=30)
        except subprocess.TimeoutExpired as exc:
            self.kill_recorded()
            self.fail(f'{command} did not return: {exc}')

    def detached(self, result, log):
        match = re.fullmatch(rf'pid=(\d+) port={self.port} log={re.escape(str(log))}\n', result.stdout)
        self.assertIsNotNone(match, (result.stdout, result.stderr))
        pid = int(match.group(1))
        self.addCleanup(self.kill, pid)
        return pid

    def test_detach_starts_records_logs_and_returns(self):
        self.env['FAKE_SERVE'] = '1'
        result = self.start('--detach', '--workers=0')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        pid = self.detached(result, self.server_log)
        # A session of its own: no terminal or Ctrl+C of the caller reaches it.
        self.assertEqual(os.getsid(pid), pid)
        self.assertEqual(self.record(), f'pid={pid} port={self.port}\n')
        self.assertIn(f'odoo {self.source / "odoo-bin"} -c {self.root / "dev/odoo.conf"} '
                      f'--http-port={self.port} --workers=0\n', self.log())
        deadline = time.monotonic() + 10
        while 'serving' not in (self.server_log.read_text() if self.server_log.exists() else ''):
            self.assertLess(time.monotonic(), deadline, 'no server output in server.log')
            time.sleep(0.05)
        self.assertEqual(self.server_log.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.server_log.parent.stat().st_mode & 0o777, 0o700)
        result = self.start('--detach')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'Odoo is already running for this checkout: pid {pid}, port {self.port}; '
                          'run oasis stop first.\n'))
        result = self.invoke('stop')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'Stopped Odoo for this checkout: pid {pid}, port {self.port}.\n', ''))
        # The next detached server appends to the same log.
        result = self.start('--detach')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.detached(result, self.server_log)
        deadline = time.monotonic() + 10
        while self.server_log.read_text().count('serving') < 2:
            self.assertLess(time.monotonic(), deadline, 'the second server did not append')
            time.sleep(0.05)
        self.assertEqual(self.server_log.read_text(), 'serving\nserving\n')

    def test_detach_reports_a_server_that_exits_at_once(self):
        self.env['FAKE_DIE'] = '1'
        result = self.start('--detach')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (1, '', f'Odoo exited at once with status 3; the end of {self.server_log}:\n'
                          'address already in use\n'))
        self.assertEqual(self.record(), '')
        self.assertEqual(self.server_log.read_text(), 'address already in use\n')

    def fake_servers(self):
        """The pids of the processes that run this test's fake odoo-bin."""
        target = os.fsencode(str(self.source / 'odoo-bin'))
        found = []
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                argv = (entry / 'cmdline').read_bytes().split(b'\0')
            except OSError:
                continue
            if target in argv:
                found.append(int(entry.name))
        return found

    def test_detach_fails_and_stops_a_server_that_does_not_listen_in_time(self):
        self.env.update(FAKE_SERVE='1', FAKE_NO_LISTEN='1', OASIS_DETACH_WAIT='2')
        result = self.start('--detach')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', (
            f'Odoo did not listen on 127.0.0.1:{self.port} within 2 s and was stopped; the end of '
            f'{self.server_log}:\nserving\n')))
        self.assertEqual(self.record(), '')
        self.assertEqual(self.fake_servers(), [])
        # Nothing is left behind: the next start works.
        del self.env['FAKE_NO_LISTEN']
        result = self.start('--detach')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.detached(result, self.server_log)

    def test_detach_probes_the_configured_http_interface(self):
        try:
            with socket.socket() as probe:
                probe.bind(('127.0.0.2', 0))
        except OSError:
            self.skipTest('127.0.0.2 is not a local address here')
        # A probe of the wrong address would wait the whole 20 s, then fail.
        self.env.update(FAKE_SERVE='1', OASIS_DETACH_WAIT='20')
        conf = self.root / 'dev/odoo.conf'
        for options, args in (
                ('http_interface = 127.0.0.2\n', ()),
                ('', ('--http-interface', '127.0.0.2')),
                ('http_interface = 127.0.0.1\n', ('--http-interface=127.0.0.2',)),
                ('http_interface = 0.0.0.0\n', ()),
                ('http_interface = ::\n', ()),
                ('http_interface =\n', ())):
            with self.subTest(options=options, args=args):
                conf.write_text(lifecycle.conf_text(f'http_port = {self.port}\n{options}'))
                began = time.monotonic()
                result = self.start('--detach', *args)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertLess(time.monotonic() - began, 10, 'start waited on an address Odoo does not use')
                pid = self.detached(result, self.server_log)
                result = self.invoke('stop')
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (0, f'Stopped Odoo for this checkout: pid {pid}, port {self.port}.\n', ''))

    def test_detach_writes_to_the_configured_logs_directory(self):
        profile = self.root / '.odoo19-agent.toml'
        profile.write_text(profile.read_text() + "logs = '../logs'\n")
        self.env['FAKE_SERVE'] = '1'
        result = self.start('--detach')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.detached(result, self.root.resolve().parent / 'logs/main/server.log')
        self.assertFalse((self.root / 'dev/logs').exists())

    def assert_refused_before_anything(self, result, message):
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', message))
        self.assertEqual(self.record(), '')
        # Neither the database service nor Odoo was started.
        self.unchanged()

    def test_detach_refuses_a_log_directory_outside_the_project(self):
        outside = Path(self.scratch.name) / 'elsewhere'
        outside.mkdir()
        (self.root / 'dev/logs').symlink_to(outside, target_is_directory=True)
        self.env['FAKE_SERVE'] = '1'
        self.assert_refused_before_anything(self.start('--detach'),
                                            'Compact logs must remain inside the project.\n')
        self.assertEqual(list(outside.iterdir()), [])

    def test_detach_refuses_a_checkout_directory_escaping_the_logs_directory(self):
        profile = self.root / '.odoo19-agent.toml'
        profile.write_text(profile.read_text() + "logs = '../logs'\n")
        outside = Path(self.scratch.name) / 'elsewhere'
        outside.mkdir()
        (self.root.parent / 'logs').mkdir()
        (self.root.parent / 'logs/main').symlink_to(outside, target_is_directory=True)
        self.env['FAKE_SERVE'] = '1'
        self.assert_refused_before_anything(self.start('--detach'),
                                            'Compact logs must remain inside the configured logs directory.\n')
        self.assertEqual(list(outside.iterdir()), [])

    def test_detach_refuses_a_batch_run(self):
        result = self.start('--detach', '--stop-after-init', '-u', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', '--detach starts a server; it cannot be combined with --stop-after-init.\n'))
        self.unchanged()

    def test_start_without_detach_is_unchanged(self):
        result = self.start('--workers=0')
        self.assertEqual((result.returncode, result.stdout), (0, ''))
        self.assertRegex(result.stderr, rf'^oasis start: http://localhost:{self.port} \(pid \d+\)\n$')
        self.assertEqual([line for line in self.log().splitlines() if line.startswith('odoo ')],
                         [f'odoo {self.source / "odoo-bin"} -c {self.root / "dev/odoo.conf"} '
                          f'--http-port={self.port} --workers=0'])
        self.assertFalse((self.root / 'dev/logs').exists())


if __name__ == '__main__':
    unittest.main()
