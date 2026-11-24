"""A path-free odoo.conf: oasis passes the location-dependent options on the command line.

`[tooling].data_dir` becomes `--data-dir=<path>` on every Odoo launch and the directory of the
filestores that disposable runs remove; an odoo.conf without `addons_path` gets an
`--addons-path` composed from the Enterprise source, the checkout's addon roots and the
Community addons, for the main checkout and a linked worktree alike. Test runs get a free
second (gevent) port besides their free HTTP port. The fake harness of test_lifecycle records
every Odoo argv; nothing outside the scratch fixture is touched.
"""
from pathlib import Path
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import unittest

import test_dev_users
import test_disposable_tests as disposable
import test_lifecycle as lifecycle
import test_shared_conf as shared

READER = lifecycle.STAGE / 'tools' / 'config.py'
# The five commands that start Odoo, with their arguments and whether the database exists.
COMMANDS = (('test-module', ('coffee',), '0'), ('install-module', ('coffee',), '0'),
            ('update-module', ('coffee', 'cc_dev_coffee'), '1'), ('odoo-shell', ('cc_dev_coffee',), '1'),
            ('start', ('--workers=0',), '0'))


def bindable(port):
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


def test_ports(line):
    """The free test ports of a test line (http, second) and the line with both replaced."""
    match = re.search(r' --http-port=(\d+) --gevent-port=(\d+) ', line)
    if match is None:
        return None, line
    return ((int(match.group(1)), int(match.group(2))),
            line[:match.start()] + ' --http-port=<free> --gevent-port=<free> ' + line[match.end():])


class PathFreeConfFixture(unittest.TestCase):
    setUp_fixture = lifecycle.LifecycleTests.setUp
    invoke = lifecycle.LifecycleTests.invoke
    unchanged = lifecycle.LifecycleTests.unchanged

    def setUp(self):
        self.setUp_fixture()
        self.conf = self.root / 'dev/odoo.conf'
        self.port = lifecycle.free_port()
        self.odoo = 'odoo ' + str(self.source / 'odoo-bin')
        self.profile = self.root / '.odoo19-agent.toml'

    def write_profile(self, extra='', replace=()):
        text = lifecycle.PROFILE
        for old, new in replace:
            text = text.replace(old, new)
        self.profile.write_text(text + extra)

    def odoo_lines(self):
        if not self.commands.exists():
            return []
        lines = []
        for entry in self.commands.read_text().splitlines():
            if entry.startswith('odoo '):
                ports, entry = test_ports(entry)
                if ports is not None:
                    self.assertNotEqual(ports[0], ports[1], entry)
                    self.assertTrue(all(port >= 1024 and bindable(port) for port in ports), ports)
                lines.append(lifecycle.any_run_database(entry))
        self.commands.unlink()
        return lines

    def run_commands(self, options):
        """Run every Odoo-starting command; compare each argv with the options after odoo-bin."""
        for command, args, exists in COMMANDS:
            with self.subTest(command=command):
                self.env['FAKE_EXISTS'] = exists
                result = self.invoke(command, *args, input='')
                self.assertEqual((result.returncode, result.stdout if command != 'odoo-shell' else ''),
                                 (0, ''), result.stderr)
                if command == 'start':
                    self.assertRegex(result.stderr, rf'^oasis start: http://localhost:{self.port} \(pid \d+\)\n$')
                else:
                    self.assertEqual(result.stderr, '')
                tail = {
                    'test-module': '--http-port=<free> --gevent-port=<free> -d cc_test_coffee_r<run> -i coffee '
                                   '--without-demo --test-tags /coffee --stop-after-init',
                    'install-module': '-d cc_dev_coffee -i coffee --without-demo --stop-after-init',
                    'update-module': '-d cc_dev_coffee -u coffee --stop-after-init',
                    'odoo-shell': '-d cc_dev_coffee',
                    'start': f'--http-port={self.port} --workers=0'}[command]
                shell = ' shell' if command == 'odoo-shell' else ''
                self.assertEqual(self.odoo_lines(), [' '.join([self.odoo + shell, *options, tail])])


class ComposedAddonsPathTests(PathFreeConfFixture):
    def test_a_conf_without_addons_path_gets_the_composed_addons_path_everywhere(self):
        self.conf.write_text(f'[options]\nhttp_port = {self.port}\n')
        root = self.root.resolve()
        self.run_commands(['-c', str(self.conf), f'--addons-path={root},{self.source}/addons'])

    def test_enterprise_comes_first_and_every_addon_root_follows_in_order(self):
        self.write_profile("enterprise = '../../source/enterprise'\n",
                           replace=(("addons_paths = ['.']", "addons_paths = ['vendor', '.']"),))
        (self.root / 'vendor').mkdir()
        self.conf.write_text(f'[options]\nhttp_port = {self.port}\n')
        enterprise = self.source.parent / 'enterprise'
        root = self.root.resolve()
        self.run_commands(['-c', str(self.conf),
                           f'--addons-path={enterprise},{root}/vendor,{root},{self.source}/addons'])

    def test_a_conf_with_addons_path_keeps_the_previous_command_line(self):
        self.conf.write_text(f'[options]\naddons_path = /srv/addons\nhttp_port = {self.port}\n')
        self.run_commands(['-c', str(self.conf)])

    def test_an_addon_root_with_a_comma_is_refused_before_odoo_starts(self):
        self.write_profile(replace=(("addons_paths = ['.']", "addons_paths = ['a,b']"),))
        (self.root / 'a,b/coffee').mkdir(parents=True)
        (self.root / 'a,b/coffee/__manifest__.py').touch()
        self.conf.write_text('[options]\n')
        result = self.invoke('install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'ERROR: Cannot compose --addons-path: {self.root.resolve()}/a,b contains a comma.\n'))
        self.assertEqual(self.odoo_lines(), [])


class DataDirTests(PathFreeConfFixture):
    def test_config_emits_data_dir_last_resolved_from_the_profile(self):
        self.write_profile("data_dir = 'dev/data'\n")
        result = subprocess.run([sys.executable, '-B', str(READER), str(self.root)], capture_output=True,
                                text=True, env=self.env)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout.splitlines()[-3:],
                         ['PYTHON_VERSION=3.12', 'DATA_DIR=' + shlex.quote(str(self.root.resolve() / 'dev/data')),
                          'AGENT_DESTRUCTIVE=ask'])
        self.write_profile()
        result = subprocess.run([sys.executable, '-B', str(READER), str(self.root)], capture_output=True,
                                text=True, env=self.env)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout.splitlines()[-2:], ["DATA_DIR=''", 'AGENT_DESTRUCTIVE=ask'])

    def test_an_invalid_data_dir_is_refused_without_assignments(self):
        for value in ('""', '7', '["data"]', '"a\\nb"', '"a\\u0000b"'):
            with self.subTest(value=value):
                self.write_profile(f'data_dir = {value}\n')
                result = subprocess.run([sys.executable, '-B', str(READER), str(self.root)],
                                        capture_output=True, text=True, env=self.env)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, '', 'ERROR: Invalid tooling path: data_dir.\n'))
                result = self.invoke('install-module', 'coffee')
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, '', 'ERROR: Invalid tooling path: data_dir.\n'))
                self.unchanged()

    def test_every_launch_passes_the_data_dir(self):
        self.write_profile("data_dir = '../../data'\n")
        data = self.source.parent.parent / 'data'
        self.conf.write_text(f'[options]\naddons_path = /srv/addons\nhttp_port = {self.port}\n')
        self.run_commands(['-c', str(self.conf), f'--data-dir={data}'])

    def test_a_path_free_conf_gets_both_options(self):
        self.write_profile("data_dir = '../../data'\n")
        data = self.source.parent.parent / 'data'
        self.conf.write_text(f'[options]\nhttp_port = {self.port}\n')
        self.run_commands(['-c', str(self.conf), f'--addons-path={self.root.resolve()},{self.source}/addons',
                           f'--data-dir={data}'])


class PathFreeLinkedWorktreeTests(unittest.TestCase):
    setUp_fixture = lifecycle.LifecycleTests.setUp
    invoke = shared.SharedConfTests.invoke
    odoo_lines = shared.SharedConfTests.odoo_lines
    odoo_call = shared.SharedConfTests.odoo_call
    break_git_with_profile_slug = shared.SharedConfTests.break_git_with_profile_slug

    def setUp(self):
        self.setUp_fixture()
        shared.shared_layout(self)
        # The shared conf names no addons_path: oasis composes it for every checkout.
        self.conf.write_text(f'[options]\nhttp_port = {self.http_port}\ngevent_port = {self.gevent_port}\n')

    def install(self, root, database):
        result = self.invoke(root, 'install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        return self.odoo_lines(), [self.odoo_call('-d', database, '-i', 'coffee', '--without-demo',
                                                  '--stop-after-init',
                                                  addons=f'{root},{self.odoo_addons}')]

    def test_main_and_linked_checkouts_get_their_own_roots_without_a_rewrite(self):
        for root, database in ((self.main, 'cc_dev_coffee'), (self.linked, 'cc_dev_wt_coffee')):
            with self.subTest(root=root):
                lines, expected = self.install(root, database)
                self.assertEqual(lines, expected)

    def test_without_git_a_path_free_shared_conf_is_composed_instead_of_refused(self):
        self.break_git_with_profile_slug()
        lines, expected = self.install(self.linked, 'cc_dev_wt_coffee')
        self.assertEqual(lines, expected)

    def test_without_git_a_shared_conf_with_addons_path_is_still_refused(self):
        self.break_git_with_profile_slug()
        self.conf.write_text(f'[options]\naddons_path = {self.main}\n')
        result = self.invoke(self.linked, 'install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
            f'ERROR: Cannot move the addons_path of {self.conf} to this worktree: git failed, '
            'so the main checkout is unknown.\n')))
        self.assertEqual(self.odoo_lines(), [])


class PathFreeDevelopmentTests(unittest.TestCase):
    """init-dev-database (dev_users_runtime.py) passes the same configuration options."""
    setUp_fixture = test_dev_users.DevelopmentUsersTests.setUp
    command = test_dev_users.DevelopmentUsersTests.command
    terminal = test_dev_users.DevelopmentUsersTests.terminal

    def setUp(self):
        self.setUp_fixture()
        self.parsed = Path(str(self.state) + '.config')
        self.conf = self.root / 'dev/odoo.conf'

    def test_path_free_conf_and_data_dir_reach_the_in_process_and_install_command_lines(self):
        self.profile.write_text(self.profile.read_text().replace(
            "test_prefix = 'cc_test_'\n", "test_prefix = 'cc_test_'\ndata_dir = '../../data'\n"))
        self.conf.write_text('[options]\n')
        code, output = self.terminal('coffee', 'cc_dev_coffee')
        self.assertEqual(code, 0, output)
        options = ['-c', str(self.conf), f'--addons-path={self.root.resolve()},{self.source}/addons',
                   f'--data-dir={self.source.parent.parent / "data"}']
        self.assertEqual(json.loads(self.parsed.read_text()),
                         [*options, '--no-http', '--without-demo', '--log-level=critical'])
        self.assertEqual(json.loads(self.state.read_text())['installs'], [[
            str(self.source / 'odoo-bin'), *options, '-d', 'cc_dev_coffee', '-i', 'coffee', '--without-demo',
            '--stop-after-init', '--no-http', '--log-level=critical']])


class DataDirFilestoreTests(disposable.DisposableFixture):
    """Disposable runs remove <DATA_DIR>/filestore/<database>; the conf's data_dir is not read."""

    def setUp(self):
        super().setUp()
        self.conf_data = self.root.parent / 'conf-data'
        self.write_profile("data_dir = '../data'\n")
        # The fake Odoo writes its filestore under FAKE_DATA, the profile's data_dir.
        (self.root / 'dev/odoo.conf').write_text(f'[options]\ndata_dir = {self.conf_data}\n')

    def test_test_module_removes_the_filestore_under_the_profile_data_dir(self):
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        database = self.run_database()
        self.assertFalse((self.data / 'filestore' / database).exists())
        self.assertTrue((self.data / 'filestore').is_dir())
        self.assertIn(f' --data-dir={self.data.resolve()} ', self.log())

    def test_verify_module_removes_both_filestores_under_the_profile_data_dir(self):
        result = self.invoke('verify-module', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertRegex(self.run_database(), '^cc_test_coffee' + disposable.RUN + '$')
        self.assertEqual(sorted((self.data / 'filestore').iterdir()), [])
        self.assertFalse(self.conf_data.exists())

    def test_a_conf_without_data_dir_still_has_the_filestore_removed(self):
        (self.root / 'dev/odoo.conf').write_text('[options]\naddons_path = /srv/addons\n')
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertFalse((self.data / 'filestore' / self.run_database()).exists())


class TestRunSecondPortTests(PathFreeConfFixture):
    def setUp(self):
        super().setUp()
        self.conf.write_text(f'[options]\naddons_path = /srv/addons\nhttp_port = {self.port}\n')
        self.prefix = f'{self.odoo} -c {self.conf}'

    def test_test_and_verify_runs_get_a_free_second_port(self):
        tests = (f'{self.prefix} --http-port=<free> --gevent-port=<free> -d cc_test_coffee_r<run> -i coffee '
                 '--without-demo --test-tags /coffee --stop-after-init')
        for command, args in (('test-module', ()), ('test-module', ('--compact',)),
                              ('verify-module', ()), ('verify-module', ('--compact',))):
            with self.subTest(command=command, args=args):
                result = self.invoke(command, *args, 'coffee')
                self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
                self.assertEqual(self.odoo_lines(), [tests] if command == 'test-module' else [
                    tests, f'{self.prefix} -d cc_test_coffee_r<run>_update -i coffee --without-demo --stop-after-init',
                    f'{self.prefix} -d cc_test_coffee_r<run>_update -u coffee --stop-after-init'])

    def batch(self, *args):
        result = self.invoke('start', '--stop-after-init', *args)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        [line] = [entry for entry in self.commands.read_text().splitlines() if entry.startswith('odoo ')]
        self.commands.unlink()
        return line

    def test_batch_start_gets_two_distinct_free_ports(self):
        line = self.batch('-u', 'coffee')
        match = re.fullmatch(re.escape(self.prefix) + r' --http-port=(\d+) --gevent-port=(\d+) '
                             r'--stop-after-init -u coffee', line)
        self.assertIsNotNone(match, line)
        http, second = int(match.group(1)), int(match.group(2))
        self.assertNotEqual(http, second)
        self.assertTrue(all(port >= 1024 and bindable(port) for port in (http, second)))

    def test_batch_start_honours_explicit_ports(self):
        line = self.batch(f'--http-port={self.port}')
        match = re.fullmatch(re.escape(self.prefix) + r' --gevent-port=(\d+) --stop-after-init '
                             + re.escape(f'--http-port={self.port}'), line)
        self.assertIsNotNone(match, line)
        self.assertNotEqual(int(match.group(1)), self.port)
        for given in (['--gevent-port', '9999'], ['--gevent-port=9999']):
            with self.subTest(given=given):
                line = self.batch(*given)
                self.assertRegex(line, re.escape(self.prefix) + r' --http-port=\d+ --stop-after-init '
                                 + re.escape(' '.join(given)) + '$')
        line = self.batch('--http-port=8100', '--gevent-port=8101')
        self.assertEqual(line, f'{self.prefix} --stop-after-init --http-port=8100 --gevent-port=8101')

    def test_batch_start_passes_an_out_of_range_explicit_port_as_given(self):
        # L17: only a valid port is excluded from the second port; Odoo judges the rest.
        for given in (['--http-port=70000'], ['--http-port', '99999'], ['-p0'], ['-p', '00000']):
            with self.subTest(given=given):
                line = self.batch(*given)
                match = re.fullmatch(re.escape(self.prefix) + r' --gevent-port=(\d+) --stop-after-init '
                                     + re.escape(' '.join(given)), line)
                self.assertIsNotNone(match, line)
                self.assertTrue(bindable(int(match.group(1))))

    def test_a_serving_start_of_the_main_checkout_is_unchanged(self):
        result = self.invoke('start')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.odoo_lines(), [f'{self.prefix} --http-port={self.port}'])


class WorkspacePythonVersionTests(unittest.TestCase):
    """L14: a named environment's python reaches require_python_version at the shell boundary."""
    setUp_fixture = lifecycle.LifecycleTests.setUp
    invoke = lifecycle.LifecycleTests.invoke
    unchanged = lifecycle.LifecycleTests.unchanged

    def setUp(self):
        previous = os.umask(0o022)
        self.addCleanup(os.umask, previous)
        self.setUp_fixture()
        self.profile = self.root / '.odoo19-agent.toml'
        self.profile.unlink()
        workspace = self.root.parent.parent
        for directory in (workspace, *(path for path in self.root.parents if path.is_relative_to(workspace))):
            directory.chmod(0o755)
        (workspace / 'oasis-workspace.toml').write_text('''workspace_version = 1
odoo_version = '19.0'

[tooling]
community = 'source/odoo'
config = 'projects/a project/dev/odoo.conf'
env_file = 'projects/a project/dev/.env'
compose = 'projects/a project/dev/compose.yml'
requirements = 'projects/a project/dev/requirements'
addons_paths = ['.']
db_service = 'db'
dev_prefix = 'cc_dev_'
test_prefix = 'cc_test_'

[environments.default]
path = 'environments/example'
python = '3.13'
''')

    def test_an_interpreter_that_is_not_the_declared_python_is_refused(self):
        result = self.invoke('install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Python 3.13 is required; found 3.12.\n'))
        self.unchanged()

    def test_the_declared_python_runs(self):
        self.python.write_text(self.python.read_text().replace('echo 3.12', 'echo 3.13'))
        result = self.invoke('install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertIn(' -d cc_dev_coffee -i coffee --without-demo --stop-after-init\n', self.commands.read_text())


if __name__ == '__main__':
    unittest.main()
