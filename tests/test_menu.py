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
import subprocess
import sys
import time
import unittest

import test_lifecycle as lifecycle

ROOT = lifecycle.STAGE
ENTRY = str((ROOT / 'oasis').resolve())
ACTIONS = ['server.start', 'server.stop', 'server.logs', 'server.status', 'server.stop_database',
           'modules.install', 'modules.update', 'modules.status', 'modules.init_dev',
           'tests.module', 'tests.class', 'tests.reuse',
           'maintenance.create_database', 'maintenance.drop_database', 'maintenance.gc',
           'maintenance.gc_apply', 'maintenance.doctor', 'maintenance.migrate_plan',
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
# A fake odoo-bin that says it serves and stays alive until killed.
SERVING = 'import time\nprint("serving", flush=True)\nwhile True:\n    time.sleep(0.1)\n'
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
                          actions['server.stop_database']['confirm'], actions['maintenance.migrate']['confirm']),
                         ('database', 'yes', 'yes', 'yes'))
        self.assertEqual([key for key, action in actions.items() if action['user_run']],
                         ['maintenance.migrate', 'maintenance.worktree'])
        self.assertEqual([key for key, action in actions.items() if action['terminal_only']], ['modules.init_dev'])
        self.assertEqual(actions['maintenance.migrate_plan']['argv'], [*prefix, 'migrate', '--plan'])

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
        result = self.terminal('9\n3\n2\nteh\n1\nTest Order\nTestOrder\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn('Choose a number from 1 to 4, or q.\n', result.stdout)
        self.assertIn('Choose a number from 1 to 1, or a name from the list.\n', result.stdout)
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

    def test_drop_requires_typing_the_database_name(self):
        self.env.update(FAKE_DATABASES='cc_dev_coffee cc_test_other', FAKE_EXISTS='1')
        result = self.terminal('4\n2\n1\nn\ncc_dev_coffe\n')
        self.assertEqual((result.returncode, result.stderr), (1, ''), result.stdout)
        self.assertIn('  1) cc_dev_coffee\n  2) cc_test_other\n', result.stdout)
        self.assertIn(self.command('drop-database', 'cc_dev_coffee'), result.stdout)
        self.assertTrue(result.stdout.endswith('Not confirmed: nothing ran.\n'), result.stdout)
        self.assertNotIn('dropdb', self.log())
        result = self.terminal('4\n2\n1\nn\ncc_dev_coffee\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        # The command first, then the confirmation (the typed answer echoes on the terminal only).
        self.assertTrue(result.stdout.endswith(self.command('drop-database', 'cc_dev_coffee') +
                                               'Type the database name to confirm: '
                                               'Database dropped: cc_dev_coffee\n'), result.stdout)
        self.assertIn('dropdb', self.log())

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
                         (2, '', f'Odoo is already running for this checkout: pid {pid}, port {self.port}.\n'))
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

    def test_detach_writes_to_the_configured_logs_directory(self):
        profile = self.root / '.odoo19-agent.toml'
        profile.write_text(profile.read_text() + "logs = '../logs'\n")
        self.env['FAKE_SERVE'] = '1'
        result = self.start('--detach')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.detached(result, self.root.resolve().parent / 'logs/main/server.log')
        self.assertFalse((self.root / 'dev/logs').exists())

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
