"""A linked worktree that shares the main checkout's odoo.conf runs Odoo with its own addons.

Real git worktrees inside the bundle-local fixture root, with the fake docker/python harness
of test_lifecycle that records every Odoo argv. The shared configuration directory sits next
to the checkouts (`<projects>/config`), as in the recommended layout; the environment file
has a neutral name. Git never reads the user's configuration.
"""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import test_dev_users
import test_lifecycle as lifecycle

HELPER = lifecycle.STAGE / 'tools' / 'odoo_addons_path.py'
GIT = ['git', '-c', 'user.name=oasis tests', '-c', 'user.email=tests@example.invalid',
       '-c', 'init.defaultBranch=main', '-c', 'commit.gpgsign=false']
SHARED_PROFILE = (lifecycle.PROFILE
                  .replace("config = 'dev/odoo.conf'", "config = '../config/odoo.conf'")
                  .replace("env_file = 'dev/.env'", "env_file = '../config/runtime-env'")
                  .replace("compose = 'dev/compose.yml'", "compose = '../config/compose.yml'")
                  .replace("requirements = 'dev/requirements'", "requirements = '../config/requirements'"))
SECRET = 'fixture-secret-value'


def shared_layout(test, profile=SHARED_PROFILE):
    """Turn the lifecycle fixture into <projects>/{a project, a project-wt, config}."""
    test.env.update({'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
                     'GIT_CEILING_DIRECTORIES': str(Path(test.scratch.name).resolve())})
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_INDEX_FILE'):
        test.env.pop(key, None)
    test.main = test.root.resolve()
    test.config_dir = test.main.parent / 'config'
    test.config_dir.mkdir()
    for name in ('runtime-env', 'compose.yml'):
        (test.config_dir / name).touch()
    test.conf = test.config_dir / 'odoo.conf'
    test.enterprise = test.main.parent.parent / 'source' / 'enterprise'
    test.odoo_addons = test.source / 'addons'
    write_conf(test, f'{test.enterprise},{test.main},{test.odoo_addons}')
    (test.main / '.odoo19-agent.toml').write_text(profile)

    def git(*args):
        subprocess.run([*GIT, '-C', str(test.main), *args], check=True, capture_output=True,
                       env=test.env)

    git('init', '-q')
    git('add', '.odoo19-agent.toml', 'coffee/__manifest__.py')
    git('commit', '-q', '-m', 'profile and module')
    test.linked = test.main.parent / 'a project-wt'
    git('worktree', 'add', '-q', '-b', 'wt', str(test.linked))


def write_conf(test, addons_path):
    test.conf.write_text('[options]\n'
                         f'addons_path = {addons_path}\n'
                         f'admin_passwd = {SECRET}\n'
                         'db_host = db\n')


class SharedConfTests(unittest.TestCase):
    setUp_fixture = lifecycle.LifecycleTests.setUp
    unchanged = lifecycle.LifecycleTests.unchanged

    def setUp(self):
        self.setUp_fixture()
        shared_layout(self)

    def invoke(self, root, command, *args, input=None):
        path = root / 'dev/scripts' / command
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((lifecycle.STAGE / 'project-wrappers' / command).read_bytes())
        return subprocess.run(['bash', str(path), *args], text=True, input=input, cwd=root,
                              env=self.env, capture_output=True)

    def odoo_lines(self):
        if not self.commands.exists():
            return []
        lines = [line for line in self.commands.read_text().splitlines() if line.startswith('odoo ')]
        self.commands.unlink()
        return lines

    def odoo_call(self, *args, shell=False, conf=None, addons=None):
        words = ['odoo', str(self.source / 'odoo-bin'), *(['shell'] if shell else []),
                 '-c', str(conf or self.conf)]
        if addons is not None:
            words.append('--addons-path=' + addons)
        return ' '.join([*words, *args])

    def run_all(self, root, slug=''):
        """Run the five Odoo-launching commands; return their recorded Odoo argv lines."""
        dev = f'cc_dev_{slug}coffee'
        test = f'cc_test_{slug}coffee'
        lines = {}
        for command, args, stdin in (
                ('test-module', ('coffee',), None),
                ('install-module', ('coffee',), None),
                ('update-module', ('coffee', dev), None),
                ('odoo-shell', (dev,), 'print(1)\n'),
                ('start', ('--stop-after-init',), None)):
            self.env['FAKE_EXISTS'] = '1' if command in ('update-module', 'odoo-shell') else '0'
            result = self.invoke(root, command, *args, input=stdin)
            self.assertEqual((result.returncode, result.stderr), (0, ''), command)
            lines[command] = self.odoo_lines()
        self.assertEqual(set(lines), {'test-module', 'install-module', 'update-module', 'odoo-shell', 'start'})
        return lines, dev, test

    def expected(self, dev, test, **kwargs):
        return {
            'test-module': [self.odoo_call('-d', test, '-i', 'coffee', '--without-demo',
                                           '--test-tags', '/coffee', '--stop-after-init', **kwargs)],
            'install-module': [self.odoo_call('-d', dev, '-i', 'coffee', '--without-demo',
                                              '--stop-after-init', **kwargs)],
            'update-module': [self.odoo_call('-d', dev, '-u', 'coffee', '--stop-after-init', **kwargs)],
            'odoo-shell': [self.odoo_call('-d', dev, shell=True, **kwargs)],
            'start': [self.odoo_call('--stop-after-init', **kwargs)],
        }

    def test_linked_worktree_gets_the_rewritten_addons_path_everywhere(self):
        lines, dev, test = self.run_all(self.linked, 'wt_')
        addons = f'{self.enterprise},{self.linked},{self.odoo_addons}'
        self.assertEqual(lines, self.expected(dev, test, addons=addons))

    def test_main_checkout_command_lines_are_unchanged(self):
        lines, dev, test = self.run_all(self.main)
        self.assertEqual(lines, self.expected(dev, test))

    def test_sub_paths_move_and_unrelated_items_stay_in_order(self):
        write_conf(self, f' {self.main}/vendor , {self.main}-other/addons,/srv/oca, {self.main} ')
        result = self.invoke(self.linked, 'install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        addons = f'{self.linked}/vendor,{self.main}-other/addons,/srv/oca,{self.linked}'
        self.assertEqual(self.odoo_lines(), [self.odoo_call(
            '-d', 'cc_dev_wt_coffee', '-i', 'coffee', '--without-demo', '--stop-after-init',
            addons=addons)])

    def test_no_main_checkout_item_or_no_addons_path_adds_no_flag(self):
        for content in (f'[options]\naddons_path = {self.enterprise},/srv/oca\n',
                        '[options]\ndb_host = db\n', '[other]\naddons_path = /x\n'):
            with self.subTest(content=content):
                self.conf.write_text(content)
                result = self.invoke(self.linked, 'install-module', 'coffee')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
                self.assertEqual(self.odoo_lines(), [self.odoo_call(
                    '-d', 'cc_dev_wt_coffee', '-i', 'coffee', '--without-demo', '--stop-after-init')])

    def test_linked_worktree_with_its_own_conf_adds_no_flag(self):
        profile = self.linked / '.odoo19-agent.toml'
        profile.write_text(SHARED_PROFILE.replace("'../config/odoo.conf'", "'dev/odoo.conf'"))
        own = self.linked / 'dev/odoo.conf'
        own.parent.mkdir()
        own.write_text(f'[options]\naddons_path = {self.enterprise},{self.linked},{self.odoo_addons}\n')
        result = self.invoke(self.linked, 'install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(self.odoo_lines(), [self.odoo_call(
            '-d', 'cc_dev_wt_coffee', '-i', 'coffee', '--without-demo', '--stop-after-init', conf=own)])

    MALFORMED = (f'addons_path = {{main}}\nadmin_passwd = {SECRET}\n',
                 f'[options]\naddons_path = {{main}}\naddons_path = {SECRET}\n',
                 f'[options]\naddons_path = {{main}}\n  {SECRET}\n[\n')

    def test_malformed_conf_stops_a_linked_worktree_before_any_odoo_call(self):
        message = f'ERROR: Cannot read addons_path from {self.conf}: invalid configuration file.\n'
        for content in self.MALFORMED:
            # test-module (before its reset), odoo-shell and start (before the database
            # service): nothing runs. install-module and update-module run their database
            # preparation first, as before, where Odoo itself would then have failed.
            for command, args, commands in (
                    ('test-module', ('coffee',), False), ('start', (), False),
                    ('odoo-shell', ('cc_dev_wt_coffee',), False),
                    ('install-module', ('coffee',), True),
                    ('update-module', ('coffee', 'cc_dev_wt_coffee'), True)):
                with self.subTest(content=content, command=command):
                    self.env['FAKE_EXISTS'] = '1'
                    self.conf.write_text(content.format(main=self.main))
                    result = self.invoke(self.linked, command, *args, input='')
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', message))
                    if commands:
                        self.assertEqual(self.odoo_lines(), [])
                    else:
                        self.unchanged()

    def test_malformed_conf_does_not_change_commands_that_do_not_start_odoo(self):
        self.conf.write_text(self.MALFORMED[0].format(main=self.main))
        for command, args in (('status', ()), ('stop', ()), ('list-databases', ()),
                              ('module-status', ('coffee', 'cc_dev_wt_coffee'))):
            with self.subTest(command=command):
                result = self.invoke(self.linked, command, *args)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(self.odoo_lines(), [])

    def test_project_local_helpers_calling_run_odoo_get_the_same_options(self):
        helper = 'source "$(dirname "$0")/common.sh"\nrun_odoo -d cc_dev_x --stop-after-init\n'
        for root, addons in ((self.main, None),
                             (self.linked, f'{self.enterprise},{self.linked},{self.odoo_addons}')):
            with self.subTest(root=root):
                scripts = root / 'dev/scripts'
                scripts.mkdir(parents=True, exist_ok=True)
                (scripts / 'common.sh').write_bytes(
                    (lifecycle.STAGE / 'project-wrappers/common.sh').read_bytes())
                (scripts / 'local-helper').write_text('set -Eeuo pipefail\n' + helper)
                result = subprocess.run(['bash', str(scripts / 'local-helper')], text=True, cwd=root,
                                        env=self.env, capture_output=True)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
                self.assertEqual(self.odoo_lines(), [self.odoo_call(
                    '-d', 'cc_dev_x', '--stop-after-init', addons=addons)])

    def test_malformed_conf_leaves_the_main_checkout_unchanged(self):
        self.conf.write_text(f'addons_path = {self.main}\n')
        result = self.invoke(self.main, 'install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(self.odoo_lines(), [self.odoo_call(
            '-d', 'cc_dev_coffee', '-i', 'coffee', '--without-demo', '--stop-after-init')])


class AddonsPathHelperTests(unittest.TestCase):
    """tools/odoo_addons_path.py on its own: only addons_path is read, nothing else printed."""

    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix='oasis-addons-')).resolve()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.main = self.scratch / 'main'
        self.main.mkdir()
        self.conf = self.scratch / 'odoo.conf'

    def run_helper(self, project, conf=None):
        return subprocess.run([sys.executable, '-B', str(HELPER), str(conf or self.conf),
                               str(self.main), str(project)], capture_output=True, text=True)

    def test_a_worktree_inside_the_main_checkout_keeps_its_own_items(self):
        nested = self.main / '.worktrees' / 'feat'
        self.conf.write_text(f'[options]\naddons_path = {self.main},{nested}/addons,{self.main}/vendor\n'
                             f'admin_passwd = {SECRET}\n')
        result = self.run_helper(nested)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'{nested},{nested}/addons,{nested}/vendor\n', ''))

    def test_symlinked_spellings_of_the_main_root_are_rewritten(self):
        alias = self.scratch / 'alias'
        alias.symlink_to(self.main, target_is_directory=True)
        other = self.scratch / 'other'
        self.conf.write_text(f'[options]\naddons_path = {alias}/addons,relative/addons\n')
        result = self.run_helper(other)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'{other}/addons,relative/addons\n', ''))

    def test_missing_addons_path_prints_nothing(self):
        for content in ('[options]\ndb_host = db\n', '', '[other]\naddons_path = /x\n'):
            with self.subTest(content=content):
                self.conf.write_text(content)
                result = self.run_helper(self.scratch / 'other')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))

    def test_errors_exit_2_without_content(self):
        missing = self.scratch / 'missing.conf'
        result = self.run_helper(self.scratch / 'other', conf=missing)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'ERROR: Cannot read {missing}.\n'))
        self.conf.write_bytes(b'[options]\naddons_path = \xff' + SECRET.encode() + b'\n')
        result = self.run_helper(self.scratch / 'other')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'ERROR: Cannot read addons_path from {self.conf}: '
                          'invalid configuration file.\n'))
        result = subprocess.run([sys.executable, '-B', str(HELPER), str(self.conf)],
                                capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'ERROR: Usage: odoo_addons_path.py <odoo.conf> <main_root> '
                          '<project_root>\n'))


class SharedConfDevelopmentTests(unittest.TestCase):
    """init-dev-database parses the configuration and runs odoo-bin with the rewrite too."""
    setUp_fixture = test_dev_users.DevelopmentUsersTests.setUp
    command = test_dev_users.DevelopmentUsersTests.command
    terminal = test_dev_users.DevelopmentUsersTests.terminal

    def setUp(self):
        self.setUp_fixture()
        shared_layout(self, SHARED_PROFILE + test_dev_users.PROFILE)
        self.parsed = Path(str(self.state) + '.config')

    def initialize(self, root, database):
        self.root = root
        code, output = self.terminal('coffee', database)
        self.assertEqual(code, 0, output)
        state = json.loads(self.state.read_text())
        return json.loads(self.parsed.read_text()), state['installs']

    def test_linked_worktree_initializes_with_its_own_addons(self):
        parsed, installs = self.initialize(self.linked, 'cc_dev_wt_coffee')
        flag = f'--addons-path={self.enterprise},{self.linked},{self.odoo_addons}'
        self.assertEqual(parsed, ['-c', str(self.conf), flag, '--no-http', '--without-demo',
                                  '--log-level=critical'])
        self.assertEqual(installs, [[str(self.source / 'odoo-bin'), '-c', str(self.conf), flag,
                                     '-d', 'cc_dev_wt_coffee', '-i', 'coffee', '--without-demo',
                                     '--stop-after-init', '--no-http', '--log-level=critical']])

    def test_main_checkout_initializes_unchanged(self):
        parsed, installs = self.initialize(self.main, 'cc_dev_coffee')
        self.assertEqual(parsed, ['-c', str(self.conf), '--no-http', '--without-demo',
                                  '--log-level=critical'])
        self.assertEqual(installs, [[str(self.source / 'odoo-bin'), '-c', str(self.conf),
                                     '-d', 'cc_dev_coffee', '-i', 'coffee', '--without-demo',
                                     '--stop-after-init', '--no-http', '--log-level=critical']])


if __name__ == '__main__':
    unittest.main()
