"""v0.9.0 action panel core: the action catalog, `oasis menu` and `start --detach` (S3-S5, S7, S8).

The lifecycle fixture (fake docker/python recording every argv, private XDG_RUNTIME_DIR); the
terminal menu runs on a pseudo-terminal created by the test. Detached fake servers are killed in
cleanup.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import re
import select
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import unittest

import test_lifecycle as lifecycle

ROOT = lifecycle.STAGE
ENTRY = str((ROOT / 'oasis').resolve())
ACTIONS = ['server.run', 'server.start', 'server.restart', 'server.stop', 'server.logs', 'server.follow', 'server.status',
           'server.stop_database',
           'modules.install', 'modules.update', 'modules.status', 'modules.init_dev', 'modules.overview',
           'tests.module', 'tests.class', 'tests.reuse',
           'maintenance.create_database', 'maintenance.drop_database', 'maintenance.trash',
           'maintenance.trash_restore', 'maintenance.trash_empty', 'maintenance.gc', 'maintenance.gc_apply', 'maintenance.doctor', 'maintenance.migrate_plan',
           'maintenance.migrate', 'maintenance.worktree']
ACTION_KEYS = ['argv', 'command', 'confirm', 'destructive', 'follow', 'group', 'id', 'inputs', 'kind', 'label',
               'superseded_by', 'terminal_only', 'user_run']
INPUT_KEYS = ['allow_new', 'choices', 'default', 'error', 'hint', 'id', 'kind', 'label', 'pattern', 'required',
              'source']
MODULE_INPUT = {'id': 'module', 'label': 'Module', 'kind': 'choice', 'source': 'modules',
                'required': True, 'allow_new': False, 'pattern': None, 'error': None, 'default': None,
                'hint': None, 'choices': None}
ONLY_INPUT = {'id': 'only', 'label': 'Test class (Class or Class.method)', 'kind': 'text',
              'source': None, 'required': True, 'allow_new': False,
              'pattern': r'^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$',
              'error': '--only takes a test class or Class.method.', 'default': None, 'hint': None,
              'choices': None}
# v0.12.0 (S3): the start / restart flow's inputs in the fixture (one module: cc_dev_coffee is derivable).
DATABASE_PATTERN = '^[A-Za-z0-9_]+$'
DATABASE_ERROR = 'Database name must use only letters, numbers, and underscores.'
PORT_PATTERN = '^(?:[1-9][0-9]{0,3}|[1-5][0-9]{4}|6[0-4][0-9]{3}|65[0-4][0-9]{2}|655[0-2][0-9]|6553[0-5])$'
RUN_DATABASE = {'id': 'database', 'label': 'Database', 'kind': 'choice', 'source': 'databases',
                'required': False, 'allow_new': True, 'pattern': DATABASE_PATTERN, 'error': DATABASE_ERROR,
                'default': 'cc_dev_coffee', 'hint': 'Enter for cc_dev_coffee, - for none', 'choices': None}


def dev_choices(warning=None):
    """The closed dev mode choices of 19.0 (tools/odoo_versions.py); warning on those that turn on reload."""
    return [{'value': '', 'label': 'off', 'warning': None},
            {'value': 'all', 'label': 'all (access, qweb, reload, xml)', 'warning': warning},
            *({'value': name, 'label': name, 'warning': warning if name == 'reload' else None}
              for name in ('access', 'qweb', 'reload', 'replica', 'xml')),
            {'value': 'reload,xml', 'label': 'reload,xml', 'warning': warning}]


def dev_input(warning=None):
    return {'id': 'dev', 'label': 'Dev mode', 'kind': 'choice', 'source': None, 'required': False,
            'allow_new': False, 'pattern': None, 'error': None, 'default': '', 'hint': 'Enter for off',
            'choices': dev_choices(warning)}


def port_input(port):
    return {'id': 'port', 'label': 'HTTP port', 'kind': 'text', 'source': None, 'required': False,
            'allow_new': False, 'pattern': PORT_PATTERN, 'error': 'Port must be a number from 1 to 65535.',
            'default': str(port), 'hint': f'Enter for {port}', 'choices': None}


NO_CONF_DATABASE = 'No database chosen: odoo.conf sets no db_name, so Odoo starts without a database.'
WAITING = 'Listing databases (this may start the database service)...'
NO_TERMINAL = ('oasis menu needs a terminal (stdin is not a TTY); run it yourself, or print the '
               'actions as JSON with --catalog.\n')
# A fake odoo-bin that listens like Odoo (on --http-interface or an unambiguous prefix of it down to
# --http-i, as optparse reads it; else the conf's http_interface; 127.0.0.1 for none, 0.0.0.0 or ::,
# so a test never listens beyond loopback), says it serves and stays alive until killed.
# FAKE_LISTEN_HOST overrides the address, FAKE_NO_LISTEN binds nothing. FAKE_TERM=ignore makes it
# ignore SIGTERM; with FAKE_CHILD it first starts a child (`<odoo-bin> --fake-child`) that ignores
# SIGTERM and writes its pid to that file.
SERVING = r'''import configparser, os, signal, socket, subprocess, sys, time
if sys.argv[1:] == ['--fake-child']:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with open(os.environ['FAKE_CHILD'], 'w') as stream:
        stream.write(str(os.getpid()))
    while True:
        time.sleep(0.1)
if os.environ.get('FAKE_TERM') == 'ignore':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if os.environ.get('FAKE_CHILD'):
    subprocess.Popen([sys.executable, sys.argv[0], '--fake-child'])
    while not (os.path.exists(os.environ['FAKE_CHILD']) and open(os.environ['FAKE_CHILD']).read()):
        time.sleep(0.02)
args, host, port = sys.argv[1:], None, None
for index, arg in enumerate(args):
    name, equals, value = arg.partition('=')
    if name == '--http-port' and equals:
        port = int(value)
    elif len(name) >= len('--http-i') and '--http-interface'.startswith(name):
        host = value if equals else args[index + 1]
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

    def odoo_lines(self):
        return [line for line in self.log().splitlines() if line.startswith('odoo ')]

    def state_file(self, name='menu.json'):
        """A file of this checkout's private runtime directory (tools/runtime_state.py)."""
        digest = hashlib.sha256(os.path.realpath(self.root).encode()).hexdigest()[:16]
        return Path(self.env['XDG_RUNTIME_DIR']) / f'oasis-{os.getuid()}' / digest / name

    def remember(self, action, answers):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/runtime_state.py'), 'remember',
                                 str(self.root), action, json.dumps(answers)],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))

    def without_reload_packages(self):
        """The fake environment Python cannot import inotify or watchdog (FAKE_NO_RELOAD)."""
        self.python.write_text(self.python.read_text().replace(
            'if [ "$1" = "-c" ]; then echo 3.12',
            'if [ "$1" = "-c" ] && [ -n "${FAKE_NO_RELOAD:-}" ] && [ "${3:-}" = inotify ]; then exit 1; fi\n'
            'if [ "$1" = "-c" ]; then echo 3.12', 1))
        self.env['FAKE_NO_RELOAD'] = '1'
        return (f'reload needs inotify or watchdog importable by {self.python}; none is, so Odoo will log a '
                'warning and disable reload.')



class CatalogTests(MenuFixture):
    def catalog(self):
        result = self.oasis('menu', '--catalog')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        return json.loads(result.stdout)

    def test_catalog_is_json_with_every_action_and_runs_nothing(self):
        catalog = self.catalog()
        self.assertEqual(sorted(catalog), ['actions', 'catalog_version', 'checkout', 'entrypoint', 'groups', 'last',
                                           'project', 'server_log', 'sources'])
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
                self.assertEqual(action['follow'], action['id'] == 'server.follow')
                # v0.12.0 (S7): the old start and restart stay for older panels; new front ends show server.run.
                self.assertEqual(action['superseded_by'],
                                 'server.run' if action['id'] in ('server.start', 'server.restart') else None)
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
                    follow = ['-f'] if action['follow'] else []
                    self.assertEqual((action['kind'], action['command'], action['argv']),
                                     ('log', None, ['tail', '-n', '200', *follow, catalog['server_log']]))
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
            'terminal_only': False, 'follow': False, 'superseded_by': None})
        self.assertEqual(actions['server.start']['argv'], [*prefix, 'start', '--detach',
                                                           {'input': 'database', 'option': '-d'}])
        # S6: restart with an optional database, and the live server log.
        self.assertEqual(actions['server.restart'], {
            'id': 'server.restart', 'group': 'server', 'label': 'Restart the server', 'kind': 'command',
            'command': 'restart', 'argv': [*prefix, 'restart', {'input': 'database', 'option': '-d'}],
            'inputs': [actions['server.start']['inputs'][0] | {'hint': 'Enter to keep the database of the running server'}],
            'destructive': False, 'confirm': None, 'user_run': False, 'terminal_only': False, 'follow': False,
            'superseded_by': 'server.run'})
        # v0.12.0 (S7): the old start keeps its id, label, command and input for older panels.
        self.assertEqual(actions['server.start'], {
            'id': 'server.start', 'group': 'server', 'label': 'Start the server in the background', 'kind': 'command',
            'command': 'start', 'argv': [*prefix, 'start', '--detach', {'input': 'database', 'option': '-d'}],
            'inputs': [RUN_DATABASE | {'default': None, 'hint': 'Enter to start without -d'}],
            'destructive': False, 'confirm': None, 'user_run': False, 'terminal_only': False, 'follow': False,
            'superseded_by': 'server.run'})
        self.assertEqual(actions['server.follow'], {
            'id': 'server.follow', 'group': 'server', 'label': 'Follow the server log', 'kind': 'log',
            'command': None, 'argv': ['tail', '-n', '200', '-f', str(self.root.resolve() / 'dev/logs/odoo19/server.log')],
            'inputs': [], 'destructive': False, 'confirm': None, 'user_run': False, 'terminal_only': False,
            'follow': True, 'superseded_by': None})
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
            'user_run': False, 'terminal_only': False, 'follow': False, 'superseded_by': None})
        self.assertEqual(actions['maintenance.trash_restore'], {
            'id': 'maintenance.trash_restore', 'group': 'maintenance', 'label': 'Restore from trash',
            'kind': 'command', 'command': 'trash', 'argv': [*prefix, 'trash', 'restore', {'input': 'trash'}],
            'inputs': [{'id': 'trash', 'label': 'Trash name (as listed by List trash)', 'kind': 'text',
                        'source': None, 'required': True, 'allow_new': False, 'pattern': '^[A-Za-z0-9_]+$',
                        'error': 'Database name must use only letters, numbers, and underscores.',
                        'default': None, 'hint': None, 'choices': None}],
            'destructive': False, 'confirm': None, 'user_run': False, 'terminal_only': False, 'follow': False, 'superseded_by': None})
        self.assertEqual(actions['maintenance.trash_empty'], {
            'id': 'maintenance.trash_empty', 'group': 'maintenance', 'label': 'Empty trash', 'kind': 'command',
            'command': 'gc', 'argv': [*prefix, 'gc', '--apply', '--trash',
                                      {'input': 'older_than', 'option': '--older-than'}],
            'inputs': [{'id': 'older_than', 'label': 'Dropped at least this many days ago', 'kind': 'text',
                        'source': None, 'required': False, 'allow_new': False, 'pattern': '^[0-9]+$',
                        'error': 'Days must be a whole number.', 'default': None, 'hint': 'Enter for 7',
                        'choices': None}],
            'destructive': True, 'confirm': 'yes', 'user_run': False, 'terminal_only': False, 'follow': False, 'superseded_by': None})
        self.assertEqual([key for key, action in actions.items() if action['user_run']],
                         ['maintenance.migrate', 'maintenance.worktree'])
        self.assertEqual([key for key, action in actions.items() if action['terminal_only']], ['modules.init_dev'])
        self.assertEqual(actions['maintenance.migrate_plan']['argv'], [*prefix, 'migrate', '--plan'])
        # Read-only, from source: no database input, no confirmation.
        self.assertEqual(actions['modules.overview'], {
            'id': 'modules.overview', 'group': 'modules', 'label': "Show a module's overview from source",
            'kind': 'command', 'command': 'module-info', 'argv': [*prefix, 'module-info', {'input': 'module'}],
            'inputs': [MODULE_INPUT], 'destructive': False, 'confirm': None, 'user_run': False,
            'terminal_only': False, 'follow': False, 'superseded_by': None})

    def test_catalog_server_log_follows_the_configured_logs_directory(self):
        profile = self.root / '.odoo19-agent.toml'
        profile.write_text(profile.read_text() + "logs = '../logs'\n")
        self.assertEqual(self.catalog()['server_log'], str(self.root.resolve().parent / 'logs/main/server.log'))
        self.assertFalse((self.root.parent / 'logs').exists())

    def test_catalog_start_restart_action_asks_database_dev_mode_and_port(self):
        catalog = self.catalog()
        prefix = [ENTRY, '--project', self.project]
        actions = {action['id']: action for action in catalog['actions']}
        # v0.12.0 (S3): one action; a stopped checkout starts in the background.
        self.assertEqual(actions['server.run'], {
            'id': 'server.run', 'group': 'server', 'label': 'Start / restart the server', 'kind': 'command',
            'command': 'start',
            'argv': [*prefix, 'start', '--detach', {'input': 'database', 'option': '-d'},
                     {'input': 'dev', 'option': '--dev'}, {'input': 'port', 'option': '--http-port'}],
            'inputs': [RUN_DATABASE, dev_input(), port_input(8069)], 'destructive': False, 'confirm': None,
            'user_run': False, 'terminal_only': False, 'follow': False, 'superseded_by': None})
        # S5: what the headers show.
        self.assertEqual(catalog['checkout'], {
            'name': 'main',
            'server': {'state': 'stopped', 'pid': None, 'port': None, 'database': None, 'error': None},
            'default_database': 'cc_dev_coffee',
            'no_database': {'start': NO_CONF_DATABASE, 'restart': NO_CONF_DATABASE}})
        self.assertIsNone(catalog['last'])
        self.unchanged()

    def test_catalog_defaults_follow_the_checkout_and_its_odoo_conf(self):
        warning = self.without_reload_packages()
        conf = self.root / 'dev/odoo.conf'
        conf.write_text(lifecycle.conf_text('http_port = 8100\ndb_name = cc_dev_other\n'))
        (self.root / 'tea').mkdir()
        (self.root / 'tea/__manifest__.py').touch()
        catalog = self.catalog()
        run = next(action for action in catalog['actions'] if action['id'] == 'server.run')
        # Two modules: no development database is derivable, so the default is none.
        self.assertEqual(run['inputs'], [RUN_DATABASE | {'default': None, 'hint': 'Enter for none'},
                                         dev_input(warning), port_input(8100)])
        uses = "No database chosen: Odoo will use odoo.conf's db_name (cc_dev_other)."
        self.assertEqual((catalog['checkout']['default_database'], catalog['checkout']['no_database']),
                         (None, {'start': uses, 'restart': uses}))
        # Odoo writes db_name = False for none.
        for value in ('False', ''):
            with self.subTest(db_name=value):
                conf.write_text(lifecycle.conf_text(f'db_name = {value}\n'))
                self.assertEqual(self.catalog()['checkout']['no_database'],
                                 {'start': NO_CONF_DATABASE, 'restart': NO_CONF_DATABASE})
        # The last database this flow used in this checkout comes first.
        self.remember('server.run', {'database': 'cc_dev_tea', 'dev': 'all', 'port': '8070'})
        catalog = self.catalog()
        self.assertEqual(catalog['checkout']['default_database'], 'cc_dev_tea')
        self.assertEqual(catalog['actions'][0]['inputs'][0],
                         RUN_DATABASE | {'default': 'cc_dev_tea', 'hint': 'Enter for cc_dev_tea, - for none'})
        self.assertEqual(catalog['last'], {
            'action': 'server.run', 'answers': {'database': 'cc_dev_tea', 'dev': 'all', 'port': '8070'},
            'label': 'Repeat: Start / restart the server (cc_dev_tea, dev all, port 8070)'})
        # Choosing no database later keeps the last one used as the default.
        self.remember('server.run', {'database': '', 'dev': '', 'port': ''})
        catalog = self.catalog()
        self.assertEqual((catalog['checkout']['default_database'], catalog['last']['label']),
                         ('cc_dev_tea', 'Repeat: Start / restart the server'))
        self.unchanged()

    def test_catalog_offers_the_last_action_only_while_it_still_applies(self):
        self.remember('modules.update', {'module': 'coffee', 'database': 'cc_dev_coffee'})
        self.assertEqual(self.catalog()['last'], {
            'action': 'modules.update', 'answers': {'module': 'coffee', 'database': 'cc_dev_coffee'},
            'label': 'Repeat: Update a module (coffee, cc_dev_coffee)'})
        self.remember('modules.install', {'module': 'coffee', 'database': '', 'demo': True})
        self.assertEqual(self.catalog()['last']['label'], 'Repeat: Install a module (coffee, demo)')
        self.remember('tests.class', {'module': 'coffee', 'only': 'TestCup.test_fill'})
        self.assertEqual(self.catalog()['last']['label'], 'Repeat: Test one class or method (coffee, only TestCup.test_fill)')
        for action, answers in (
                ('modules.update', {'module': 'gone', 'database': 'cc_dev_coffee'}),
                ('modules.update', {'module': 'coffee'}),
                ('modules.update', {'module': 'coffee', 'database': 'cc_dev_coffee', 'extra': 'x'}),
                ('modules.update', {'module': 'coffee', 'database': 'bad-name'}),
                ('modules.install', {'module': 'coffee', 'database': '', 'demo': 'yes'}),
                ('server.run', {'database': '', 'dev': 'pdb', 'port': ''}),
                ('server.run', {'database': '', 'dev': '', 'port': '70000'}),
                ('maintenance.worktree', {'feature': 'shop', 'branch': 'shop'}),
                ('modules.init_dev', {'module': 'coffee', 'database': 'cc_dev_x', 'demo': False}),
                ('server.follow', {}),
                ('server.gone', {})):
            with self.subTest(action=action, answers=answers):
                self.remember(action, answers)
                self.assertIsNone(self.catalog()['last'])
        self.unchanged()

    def test_catalog_reports_an_unreadable_runtime_state_and_still_lists_the_actions(self):
        user_root = Path(self.env['XDG_RUNTIME_DIR']) / f'oasis-{os.getuid()}'
        elsewhere = Path(self.scratch.name) / 'elsewhere'
        elsewhere.mkdir()
        user_root.symlink_to(elsewhere, target_is_directory=True)
        catalog = self.catalog()
        self.assertEqual(catalog['checkout']['server'], {
            'state': 'unknown', 'pid': None, 'port': None, 'database': None,
            'error': f'Runtime state directory is a symlink: {user_root}'})
        self.assertEqual((catalog['last'], catalog['actions'][0]['command']), (None, 'start'))
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_start_port_follows_the_rules_of_start(self):
        spec = importlib.util.spec_from_file_location('oasis_actions_under_test', ROOT / 'tools/actions.py')
        actions = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(actions)
        port = lifecycle.quiet_ports(3)
        conf = self.root / 'dev/odoo.conf'
        conf.write_text(lifecycle.conf_text(f'http_port = {port}\n'))
        values = {'ODOO_CONFIG': str(conf), 'CHECKOUT_KIND': 'main'}
        self.assertEqual(actions.start_port(values, None), port)
        self.assertEqual(actions.start_port(values, {'port': 9000}), 9000)
        with socket.socket() as holder:
            holder.bind(('127.0.0.1', port + 1))
            holder.listen()
            self.assertEqual(actions.start_port(values | {'CHECKOUT_KIND': 'linked'}, None), port + 2)
        conf.write_text(lifecycle.conf_text())
        self.assertEqual(actions.start_port(values, None), 8069)
        conf.write_text(lifecycle.conf_text('http_port = x\n'))
        self.assertIsNone(actions.start_port(values, None))

    def test_menu_is_a_public_command_with_help(self):
        result = self.oasis('menu', '--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(f'Usage: {ENTRY} menu [--catalog]\n'), result.stdout)
        result = self.oasis('menu', '--bogus')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', f'Usage: {ENTRY} menu [--catalog]\n'))
        self.unchanged()


class TerminalMenuTests(MenuFixture):
    def test_menu_header_shows_checkout_server_and_default_database(self):
        result = self.terminal('q\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(
            f'oasis menu: {self.project}\ncheckout: main\nserver: stopped\ndefault database: cc_dev_coffee\n'
            '  1) Server\n'), result.stdout)
        self.assertIn('Group (q to quit): ', result.stdout)
        self.assertNotIn('Repeat', result.stdout)
        # One start / restart action; the superseded ones are not listed.
        result = self.terminal('1\nq\n')
        self.assertIn('Server\n  1) Start / restart the server\n  2) Stop the server\n'
                      '  3) Show the end of the server log\n', result.stdout)
        self.assertNotIn('Start the server in the background', result.stdout)
        self.assertNotIn('Restart the server\n', result.stdout)
        self.unchanged()

    def test_start_restart_asks_database_dev_mode_and_port_then_confirms(self):
        self.env.update(FAKE_DATABASES='cc_dev_coffee cc_dev_tea')
        result = self.terminal('1\n1\n\n\n\nn\n')
        self.assertEqual((result.returncode, result.stderr), (1, ''), result.stdout)
        self.assertIn('Database\n  1) cc_dev_coffee\n  2) cc_dev_tea\n'
                      'Database (number or name, Enter for cc_dev_coffee, - for none): Dev mode\n  1) off\n'
                      '  2) all (access, qweb, reload, xml)\n  3) access\n  4) qweb\n  5) reload\n  6) replica\n'
                      '  7) xml\n  8) reload,xml\nDev mode (number, Enter for off): HTTP port (Enter for 8069): ',
                      result.stdout)
        self.assertTrue(result.stdout.endswith(
            self.command('start', '--detach', '-d', 'cc_dev_coffee') +
            'Run this command? [y/N]: Not confirmed: nothing ran.\n'), result.stdout)
        self.assertEqual(self.odoo_lines(), [])
        self.assertFalse(self.state_file().exists())
        # No database, a dev mode whose reload cannot work here, a port asked again until valid.
        warning = self.without_reload_packages()
        result = self.terminal('1\n1\n-\n9\n2\n0\n8070\nno\n')
        self.assertEqual((result.returncode, result.stderr), (1, ''), result.stdout)
        self.assertIn('Choose a number from 1 to 8.\n', result.stdout)
        self.assertIn(f'Warning: {warning}\nHTTP port', result.stdout)
        self.assertIn('Port must be a number from 1 to 65535.\n', result.stdout)
        self.assertTrue(result.stdout.endswith(
            self.command('start', '--detach', '--dev', 'all', '--http-port', '8070') + NO_CONF_DATABASE +
            '\nRun this command? [y/N]: Not confirmed: nothing ran.\n'), result.stdout)
        self.assertEqual(self.odoo_lines(), [])

    def test_the_last_action_is_offered_first_and_repeats_after_the_same_confirmation(self):
        self.env.update(FAKE_DATABASES='cc_dev_coffee', FAKE_EXISTS='1')
        result = self.terminal('2\n3\n1\n1\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        memory = self.state_file()
        self.assertEqual(memory.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(memory.read_text()),
                         {'last': {'action': 'modules.status', 'answers': {'module': 'coffee', 'database': 'cc_dev_coffee'}}})
        before = self.log().count('COALESCE(latest_version')
        result = self.terminal('r\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        # The group numbers stay; r repeats.
        self.assertIn("default database: cc_dev_coffee\n  r) Repeat: Show a module's state (coffee, cc_dev_coffee)\n"
                      '  1) Server\n', result.stdout)
        self.assertIn('Group (r to repeat, q to quit): ' + self.command('module-status', 'coffee', 'cc_dev_coffee'),
                      result.stdout)
        self.assertEqual(self.log().count('COALESCE(latest_version'), before + 1)
        # A destructive action repeats only after its typed confirmation.
        Path(str(self.commands) + '.databases').write_text('cc_dev_coffee\n')
        self.env.pop('FAKE_EXISTS')
        result = self.terminal('4\n2\n1\nn\ncc_dev_coffee\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        result = self.terminal('r\ncc_dev_coffe\n')
        self.assertEqual((result.returncode, result.stderr), (1, ''), result.stdout)
        self.assertIn('  r) Repeat: Move a database to the trash (cc_dev_coffee)\n', result.stdout)
        self.assertTrue(result.stdout.endswith(
            self.command('drop-database', 'cc_dev_coffee') + 'Type the database name to confirm: '
            'Not confirmed: nothing ran.\n'), result.stdout)
        self.assertEqual(self.log().count('RENAME TO'), 1)

    def test_user_run_actions_are_not_remembered(self):
        result = self.terminal('4\n11\nshop\nshop\n')
        self.assertIn(self.command('worktree-init', 'shop', 'shop'), result.stdout)
        self.assertFalse(self.state_file().exists())
        result = self.terminal('q\n')
        self.assertNotIn('Repeat', result.stdout)

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
        # list-databases lists only prefixed names (v0.12.0 S2), so a module named 2024 holds the rule.
        (self.root / '2024').mkdir()
        (self.root / '2024/__manifest__.py').touch()
        self.env.update(FAKE_DATABASES='cc_dev_coffee', FAKE_EXISTS='1')
        for answer, module in (('2024', '2024'), ('1', '2024'), ('2', 'coffee')):
            with self.subTest(answer=answer):
                result = self.terminal(f'2\n3\n{answer}\n1\n')
                self.assertIn('  1) 2024\n  2) coffee\n', result.stdout)
                self.assertNotIn('Choose a number', result.stdout)
                self.assertIn(self.command('module-status', module, 'cc_dev_coffee'), result.stdout)

    def test_database_choices_are_the_checkouts_own(self):
        # The fake service answers every name; list-databases keeps this checkout's (v0.12.0 S2).
        self.env.update(FAKE_DATABASES='cc_dev_coffee cc_dev_wt_1_coffee cc_test_other cc_test_wt_1_x postgres',
                        FAKE_EXISTS='1')
        profile = self.root / '.odoo19-agent.toml'
        for extra, listed, database in (
                ('', ['cc_dev_coffee', 'cc_dev_wt_1_coffee', 'cc_test_other', 'cc_test_wt_1_x'], 'cc_dev_coffee'),
                ("checkout_slug = 'wt_1'\n", ['cc_dev_wt_1_coffee', 'cc_test_wt_1_x'], 'cc_dev_wt_1_coffee')):
            with self.subTest(slug=extra):
                profile.write_text(lifecycle.PROFILE + extra)
                result = self.terminal('2\n3\n1\n1\n')
                self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
                choices = ''.join(f'  {number}) {name}\n' for number, name in enumerate(listed, 1))
                self.assertIn(WAITING + '\nDatabase\n' + choices + 'Database (number or name', result.stdout)
                self.assertIn(self.command('module-status', 'coffee', database), result.stdout)
                self.assertIn("SELECT datname FROM pg_database WHERE datname LIKE 'cc\\_dev\\_%' ESCAPE", self.log())

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
        result = self.terminal('1\n6\nno\n')
        self.assertEqual((result.returncode, result.stderr), (1, ''), result.stdout)
        self.assertIn(self.command('stop', '--database'), result.stdout)
        self.assertIn('Type yes to confirm: ', result.stdout)
        self.assertTrue(result.stdout.endswith('Not confirmed: nothing ran.\n'))
        self.unchanged()
        result = self.terminal('1\n6\nyes\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertTrue(self.log().endswith(' stop db\n'), self.log())

    def test_missing_server_log(self):
        for answers in ('1\n3\n', '1\n4\n'):
            with self.subTest(action=answers.split()[1]):
                result = self.terminal(answers)
                self.assertEqual((result.returncode, result.stderr), (1, ''))
                self.assertTrue(result.stdout.endswith(
                    f'No server log yet: {self.root.resolve() / "dev/logs/odoo19/server.log"}\n'), result.stdout)
                self.unchanged()

    def test_follow_the_server_log_until_ctrl_c(self):
        log = self.root.resolve() / 'dev/logs/odoo19/server.log'
        log.parent.mkdir(parents=True)
        log.write_text(''.join(f'line {number}\n' for number in range(1, 251)))
        master, slave = os.openpty()
        try:
            # A session of its own, so the test can send Ctrl+C (SIGINT) to the menu and tail only.
            process = subprocess.Popen(
                [sys.executable, '-B', str(ROOT / 'oasis'), '--project', str(self.root), 'menu'], text=True,
                cwd=self.root, env=self.env, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True)
        finally:
            os.close(slave)
        self.addCleanup(os.close, master)

        def end():
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
        self.addCleanup(end)
        os.write(master, b'1\n4\n')
        seen = b''

        def read_until(text):
            nonlocal seen
            deadline = time.monotonic() + 20
            while text not in seen:
                self.assertLess(time.monotonic(), deadline, seen.decode()[-2000:])
                ready, _, _ = select.select([process.stdout], [], [], 0.1)
                if ready:
                    chunk = os.read(process.stdout.fileno(), 65536)
                    self.assertTrue(chunk, seen.decode()[-2000:])
                    seen += chunk
        read_until(b'line 250\n')
        with log.open('a') as stream:
            stream.write('line 251\n')
        read_until(b'line 251\n')
        self.assertIsNone(process.poll())
        os.killpg(process.pid, signal.SIGINT)
        stdout, stderr = process.communicate(timeout=20)
        output = (seen + stdout.encode()).decode()
        self.assertEqual((process.returncode, stderr), (0, ''))
        self.assertIn('Command: ' + shlex.join(['tail', '-n', '200', '-f', str(log)]) + '\n'
                      f'Following {log}; press Ctrl+C to stop.\nline 51\n', output)
        self.assertNotIn('line 50\n', output)
        self.assertTrue(output.endswith('line 251\n\nStopped following the server log.\n'), output[-300:])
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

    def test_detach_kills_a_server_and_a_child_that_ignore_sigterm(self):
        # The escalation (L9): SIGTERM to the session, SIGKILL to whatever is left after the grace.
        child_file = Path(self.scratch.name) / 'child.pid'
        self.addCleanup(lambda: [self.kill(pid) for pid in self.fake_servers()])
        self.env.update(FAKE_SERVE='1', FAKE_NO_LISTEN='1', OASIS_DETACH_WAIT='1', OASIS_STOP_GRACE='0.5',
                        FAKE_CHILD=str(child_file))
        for term in ('ignore', 'exit'):
            with self.subTest(term=term):
                child_file.unlink(missing_ok=True)
                self.env['FAKE_TERM'] = term
                result = self.start('--detach')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', (
                    f'Odoo did not listen on 127.0.0.1:{self.port} within 1 s and was stopped; the end of '
                    f'{self.server_log}:\nserving\n')))
                self.assertTrue(child_file.read_text())
                self.assertEqual(self.record(), '')
                deadline = time.monotonic() + 5
                while self.fake_servers():
                    self.assertLess(time.monotonic(), deadline, f'left running: {self.fake_servers()}')
                    time.sleep(0.05)
                self.server_log.unlink()

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
                # Odoo reads unambiguous abbreviations (optparse), down to --http-i.
                ('http_interface = 127.0.0.1\n', ('--http-int=127.0.0.2',)),
                ('', ('--http-i', '127.0.0.2')),
                ('http_interface = 127.0.0.1\n', ('--http-interfac', '127.0.0.2')),
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

    def restarted(self, result, port):
        match = re.fullmatch(rf'pid=(\d+) port={port} log={re.escape(str(self.server_log))}\n',
                             result.stdout.split('\n', 1)[1] if '\n' in result.stdout else '')
        self.assertIsNotNone(match, (result.stdout, result.stderr))
        pid = int(match.group(1))
        self.addCleanup(self.kill, pid)
        return pid

    def test_restart_stops_the_server_and_starts_it_detached_on_the_same_port(self):
        self.env['FAKE_SERVE'] = '1'
        other = self.port + 1
        result = self.start('--detach', f'--http-port={other}')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        first = int(re.match(r'pid=(\d+) ', result.stdout).group(1))
        self.addCleanup(self.kill, first)
        result = self.oasis('restart', '--workers=0')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(f'Stopped Odoo for this checkout: pid {first}, port {other}.\n'),
                        result.stdout)
        second = self.restarted(result, other)
        self.assertNotEqual(second, first)
        self.assertEqual(self.record(), f'pid={second} port={other}\n')
        self.assertNotIn(first, self.fake_servers())
        conf = self.root / 'dev/odoo.conf'
        self.assertEqual(self.odoo_lines()[-1],
                         f'odoo {self.source / "odoo-bin"} -c {conf} --http-port={other} --workers=0')
        # Options that name another port win; the record follows.
        result = self.oasis('restart', f'--http-port={self.port}')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(f'Stopped Odoo for this checkout: pid {second}, port {other}.\n'))
        third = self.restarted(result, self.port)
        self.assertEqual(self.record(), f'pid={third} port={self.port}\n')
        self.assertEqual(self.odoo_lines()[-1], f'odoo {self.source / "odoo-bin"} -c {conf} --http-port={self.port}')

    def test_restart_without_a_server_starts_one(self):
        self.env['FAKE_SERVE'] = '1'
        result = self.oasis('restart', '-d', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith('No Odoo server running for this checkout.\n'), result.stdout)
        pid = self.restarted(result, self.port)
        self.assertEqual(self.record(), f'pid={pid} port={self.port}\n')
        self.assertEqual(self.odoo_lines(), [f'odoo {self.source / "odoo-bin"} -c {self.root / "dev/odoo.conf"} '
                                             f'--http-port={self.port} -d cc_dev_coffee'])

    def test_restart_keeps_the_database_the_stopped_server_recorded(self):
        git = {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}
        self.env.update(git, FAKE_SERVE='1')
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True, env=self.env, capture_output=True)
        result = self.start('--detach', '-d', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.detached(result, self.server_log)
        prefix = f'odoo {self.source / "odoo-bin"} -c {self.root / "dev/odoo.conf"}'
        other = self.port + 1
        # Without -d/--database the recorded database is kept, restart after restart; given ones win.
        for args, port, line in (
                ((), self.port, f'--http-port={self.port} -d cc_dev_coffee'),
                (('--workers=0',), self.port, f'--http-port={self.port} -d cc_dev_coffee --workers=0'),
                (('-d', 'cc_test_coffee'), self.port, f'--http-port={self.port} -d cc_test_coffee'),
                (('--database=cc_dev_coffee',), self.port, f'--http-port={self.port} --database=cc_dev_coffee'),
                ((f'--http-port={other}',), other, f'-d cc_dev_coffee --http-port={other}')):
            with self.subTest(args=args):
                result = self.oasis('restart', *args)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                pid = self.restarted(result, port)
                self.assertEqual(self.odoo_lines()[-1], f'{prefix} {line}')
        result = self.oasis('status')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout, (
            f'server: running pid {pid} port {other}\nrepository servers: 1\n'
            f'  {self.root.resolve()}: pid {pid}, port {other}, database cc_dev_coffee (this checkout)\n'))

    def test_restart_names_the_database_in_the_repository_status(self):
        git = {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}
        self.env.update(git, FAKE_SERVE='1')
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True, env=self.env, capture_output=True)
        result = self.oasis('restart', '-d', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        pid = self.restarted(result, self.port)
        result = self.oasis('status')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout, (
            f'server: running pid {pid} port {self.port}\nrepository servers: 1\n'
            f'  {self.root.resolve()}: pid {pid}, port {self.port}, database cc_dev_coffee (this checkout)\n'))

    def test_restart_refuses_cleanly_when_stop_fails(self):
        self.env.update(FAKE_SERVE='1', FAKE_TERM='ignore', OASIS_STOP_TIMEOUT='0.5')
        result = self.start('--detach')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        pid = self.detached(result, self.server_log)
        lines = self.odoo_lines()
        result = self.oasis('restart')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', (
            f'Odoo did not stop within 0.5 s: pid {pid}, port {self.port}; run oasis stop --force.\n'
            'Nothing was restarted: Odoo is still running for this checkout.\n')))
        self.assertEqual(self.record(), f'pid={pid} port={self.port}\n')
        self.assertIn(pid, self.fake_servers())
        self.assertEqual(self.odoo_lines(), lines)
        # Plain stop suggests --force with the program that ran it; the exit code stays 1.
        for program in ('oasis', 'odoo19'):
            with self.subTest(program=program):
                result = self.oasis('stop', program=program)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', (
                    f'Odoo did not stop within 0.5 s: pid {pid}, port {self.port}; run {program} stop --force.\n')))
                self.assertEqual(self.record(), f'pid={pid} port={self.port}\n')
        # stop --force ends it; restart then starts a new server.
        result = self.oasis('stop', '--force')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, (
            f'Killed Odoo for this checkout after 0.5 s (SIGKILL to its session): pid {pid}, port {self.port}.\n'), ''))
        del self.env['FAKE_TERM']
        result = self.oasis('restart')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.restarted(result, self.port)

    def test_restart_reports_a_stop_failure_without_claiming_odoo_still_runs(self):
        self.env['FAKE_SERVE'] = '1'
        result = self.start('--detach')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        pid = self.detached(result, self.server_log)
        lines = self.odoo_lines()
        # The tools with a runtime_state.py whose stop fails as FAKE_STOP says; the rest is the real one.
        tools = Path(self.scratch.name) / 'staged-tools'
        shutil.copytree(ROOT / 'tools', tools, ignore=shutil.ignore_patterns('__pycache__'))
        (tools / 'runtime_state.py').write_text(
            'import os, sys\n'
            'if sys.argv[1:2] == ["stop"]:\n'
            '    status, message = os.environ["FAKE_STOP"].split(":", 1)\n'
            '    print(message, file=sys.stderr)\n'
            '    sys.exit(int(status))\n'
            f'os.execv(sys.executable, [sys.executable, "-I", "-B", {str(ROOT / "tools/runtime_state.py")!r}, '
            '*sys.argv[1:]])\n')
        env = {**self.env, 'OASIS_PROJECT_ROOT': str(self.root), 'ODOO19_PROJECT_ROOT': str(self.root)}
        for status, message in ((2, f'ERROR: Cannot read runtime state: {self.root}/server.json'),
                                (1, 'Traceback (most recent call last):\nPermissionError: [Errno 13] Permission denied')):
            with self.subTest(status=status):
                result = subprocess.run(['bash', str(tools / 'restart')], text=True, cwd=self.root,
                                        env={**env, 'FAKE_STOP': f'{status}:{message}'}, capture_output=True,
                                        stdin=subprocess.DEVNULL, timeout=30)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (status, '', f'{message}\nNothing was restarted.\n'))
                self.assertEqual(self.record(), f'pid={pid} port={self.port}\n')
                self.assertIn(pid, self.fake_servers())
                self.assertEqual(self.odoo_lines(), lines)

    def test_restart_refuses_before_stopping_what_start_would_refuse(self):
        self.env['FAKE_SERVE'] = '1'
        result = self.start('--detach')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        pid = self.detached(result, self.server_log)
        lines = self.odoo_lines()
        usage = f'Usage: {ENTRY} restart [odoo options]\n'
        with socket.socket() as holder:
            holder.bind(('127.0.0.1', self.port + 1))
            holder.listen()
            for args, message in (
                    (('--stop-after-init',), 'restart starts a server; it cannot be combined with --stop-after-init.\n'),
                    (('--detach',), usage), (('--workers=0', '--detach'), usage), (('--help', '-d', 'cc_dev_coffee'), usage),
                    (('--version',), usage),
                    (('-d', 'other_db'), 'Managed databases must use cc_dev_<name> or cc_test_<name>: other_db\n'),
                    (('--http-port=0',), 'Invalid HTTP port: 0\n'),
                    ((f'--http-port={self.port + 1}',), (
                        f'Port {self.port + 1} is in use by another process; pass another --http-port or stop that '
                        'process.\n'))):
                with self.subTest(args=args):
                    result = self.oasis('restart', *args)
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', message))
                    self.assertEqual(self.record(), f'pid={pid} port={self.port}\n')
                    self.assertEqual(self.odoo_lines(), lines)
        result = self.oasis('restart', '--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(usage), result.stdout)
        self.assertIn('--http-port', result.stdout)
        self.assertIn('the port and the database the stopped server had', ' '.join(result.stdout.split()))
        self.assertEqual(self.record(), f'pid={pid} port={self.port}\n')

    def test_start_restart_from_the_menu_starts_then_restarts_and_repeats(self):
        self.env.update(FAKE_SERVE='1', FAKE_DATABASES='cc_dev_coffee', FAKE_EXISTS='1')
        prefix = f'odoo {self.source / "odoo-bin"} -c {self.root / "dev/odoo.conf"}'
        result = self.terminal('1\n1\n\n\n\ny\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn(f'HTTP port (Enter for {self.port}): ' + self.command('start', '--detach', '-d', 'cc_dev_coffee') +
                      'Run this command? [y/N]: pid=', result.stdout)
        pid = int(re.search(r'pid=(\d+) ', self.record()).group(1))
        self.addCleanup(self.kill, pid)
        self.assertEqual(self.odoo_lines()[-1], f'{prefix} --http-port={self.port} -d cc_dev_coffee')
        # The server runs: the same action restarts it, with the chosen dev mode.
        result = self.terminal('1\n1\n\n4\n\ny\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn(f'server: running on port {self.port} (pid {pid})\n', result.stdout)
        self.assertIn(self.command('restart', '-d', 'cc_dev_coffee', '--dev', 'qweb') + 'Run this command? [y/N]: '
                      f'Stopped Odoo for this checkout: pid {pid}, port {self.port}.\n', result.stdout)
        second = self.restarted(subprocess.CompletedProcess([], 0, result.stdout.split('Run this command? [y/N]: ', 1)[1], ''),
                                self.port)
        self.assertEqual(self.odoo_lines()[-1], f'{prefix} --http-port={self.port} -d cc_dev_coffee --dev qweb')
        result = self.terminal('r\ny\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn('  r) Repeat: Start / restart the server (cc_dev_coffee, dev qweb)\n', result.stdout)
        self.assertIn(self.command('restart', '-d', 'cc_dev_coffee', '--dev', 'qweb') + 'Run this command? [y/N]: '
                      f'Stopped Odoo for this checkout: pid {second}, port {self.port}.\n', result.stdout)
        third = int(re.search(r'pid=(\d+) ', self.record()).group(1))
        self.addCleanup(self.kill, third)
        self.assertEqual(len(self.odoo_lines()), 3)

    def test_start_without_a_database_from_the_menu_is_remembered(self):
        self.env.update(FAKE_SERVE='1', FAKE_DATABASES='cc_dev_coffee', FAKE_EXISTS='1')
        result = self.terminal('1\n1\n-\n\n\ny\n')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn(self.command('start', '--detach') + NO_CONF_DATABASE, result.stdout)
        pid = int(re.search(r'pid=(\d+) ', self.record()).group(1))
        self.addCleanup(self.kill, pid)
        memory = json.loads(self.state_file().read_text())
        self.assertEqual(memory['last']['action'], 'server.run')
        self.assertEqual(memory['last']['answers']['database'], '')

    def test_catalog_restarts_a_running_server_and_keeps_its_port(self):
        self.env['FAKE_SERVE'] = '1'
        other = self.port + 1
        result = self.start('--detach', '-d', 'cc_dev_coffee', f'--http-port={other}')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        pid = int(re.match(r'pid=(\d+) ', result.stdout).group(1))
        self.addCleanup(self.kill, pid)
        result = self.oasis('menu', '--catalog')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        catalog = json.loads(result.stdout)
        run = catalog['actions'][0]
        self.assertEqual((run['id'], run['command'], run['argv'][3:]), ('server.run', 'restart', [
            'restart', {'input': 'database', 'option': '-d'}, {'input': 'dev', 'option': '--dev'},
            {'input': 'port', 'option': '--http-port'}]))
        self.assertEqual(run['inputs'][2], port_input(other))
        self.assertEqual(catalog['checkout']['server'], {'state': 'running', 'pid': pid, 'port': other,
                                                         'database': 'cc_dev_coffee', 'error': None})
        self.assertEqual(catalog['checkout']['no_database'], {
            'start': NO_CONF_DATABASE,
            'restart': 'No database chosen: restart keeps the database of the running server (cc_dev_coffee).'})

    def test_start_without_a_database_warns_when_odoo_conf_names_one(self):
        self.env['FAKE_SERVE'] = '1'
        conf = self.root / 'dev/odoo.conf'
        conf.write_text(lifecycle.conf_text(f'http_port = {self.port}\ndb_name = cc_dev_coffee\n'))
        warning = "WARNING: no database given (-d); Odoo will use odoo.conf's db_name (cc_dev_coffee).\n"
        result = self.start('--detach')
        self.assertEqual((result.returncode, result.stderr), (0, warning))
        pid = self.detached(result, self.server_log)
        # restart without a recorded database starts without -d: the same warning.
        result = self.oasis('restart')
        self.assertEqual((result.returncode, result.stderr), (0, warning))
        self.restarted(result, self.port)
        result = self.invoke('stop')
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.start('--detach', '-d', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.detached(result, self.server_log)
        # The recorded database is kept: no warning.
        result = self.oasis('restart')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.restarted(result, self.port)
        result = self.invoke('stop')
        self.assertEqual(result.returncode, 0, result.stderr)
        # A batch run is not warned; neither is a conf without db_name (Odoo writes False for none).
        del self.env['FAKE_SERVE']
        result = self.start('--stop-after-init')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.env['FAKE_SERVE'] = '1'
        for value in ('False', ''):
            with self.subTest(db_name=value):
                conf.write_text(lifecycle.conf_text(f'http_port = {self.port}\ndb_name = {value}\n'))
                result = self.start('--detach')
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.detached(result, self.server_log)
                self.assertEqual(self.invoke('stop').returncode, 0)

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
