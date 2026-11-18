"""Compact execution must preserve fail-closed behavior and evidence."""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import unittest
import test_lifecycle as lifecycle

REFUSED = 'Compact logs must remain inside the project.\n'
GIT = ['git', '-c', 'user.name=oasis tests', '-c', 'user.email=tests@example.invalid',
       '-c', 'init.defaultBranch=main', '-c', 'commit.gpgsign=false']


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


@unittest.skipUnless(shutil.which('git'), 'git is required')
class LinkedWorktreeCompactTests(unittest.TestCase):
    """A linked worktree may keep its dev/logs linked to the main checkout's dev/logs."""
    setUp_fixture = lifecycle.LifecycleTests.setUp
    unchanged = lifecycle.LifecycleTests.unchanged

    def setUp(self):
        self.setUp_fixture()
        self.env.update({'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
                         'GIT_CEILING_DIRECTORIES': str(Path(self.scratch.name).resolve())})
        for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_INDEX_FILE'):
            self.env.pop(key, None)
        self.main = self.root.resolve()
        self.git(self.main, 'init', '-q')
        self.git(self.main, 'add', '.odoo19-agent.toml')
        self.git(self.main, 'commit', '-q', '-m', 'profile')
        self.linked = self.main.parent / 'a project-wt'
        self.git(self.main, 'worktree', 'add', '-q', '-b', 'wt', str(self.linked))
        # The linked checkout gets its own runtime files; a neutral env file name.
        (self.linked / '.odoo19-agent.toml').write_text(
            lifecycle.PROFILE.replace("env_file = 'dev/.env'", "env_file = 'dev/runtime-env'"))
        for name in ('dev/odoo.conf', 'dev/runtime-env', 'dev/compose.yml', 'coffee/__manifest__.py'):
            path = self.linked / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    def git(self, cwd, *args):
        subprocess.run([*GIT, '-C', str(cwd), *args], check=True, capture_output=True, env=self.env)

    def invoke(self, root, *args):
        path = root / 'dev/scripts/test-module'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((lifecycle.STAGE / 'project-wrappers/test-module').read_bytes())
        return subprocess.run(['bash', str(path), *args], text=True, cwd=root, env=self.env,
                              capture_output=True)

    def test_logs_linked_to_the_main_checkout_are_accepted(self):
        (self.main / 'dev/logs').mkdir()
        (self.linked / 'dev/logs').symlink_to(self.main / 'dev/logs', target_is_directory=True)
        result = self.invoke(self.linked, '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], 'phase=tests database=cc_test_wt_coffee exit=0')
        logs = dict(line.split('=', 1) for line in lines[1:])
        runs = list((self.main / 'dev/logs/odoo19').iterdir())
        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0].name.startswith('run-'))
        self.assertEqual(Path(logs['stdout_log']).resolve(), runs[0] / 'stdout.log')
        self.assertEqual(Path(logs['stderr_log']).resolve(), runs[0] / 'stderr.log')
        self.assertEqual(runs[0].stat().st_mode & 0o777, 0o700)

    def test_linked_logs_outside_both_checkouts_are_refused(self):
        outside = self.main.parent.parent / 'outside'
        outside.mkdir()
        (self.linked / 'dev/logs').symlink_to(outside, target_is_directory=True)
        result = self.invoke(self.linked, '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', REFUSED))
        self.assertEqual(list(outside.iterdir()), [])
        self.unchanged()

    def test_linked_logs_elsewhere_in_the_main_checkout_are_refused(self):
        source = self.main / 'addons'
        source.mkdir()
        (self.linked / 'dev/logs').symlink_to(source, target_is_directory=True)
        result = self.invoke(self.linked, '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', REFUSED))
        self.assertEqual(list(source.iterdir()), [])
        self.unchanged()

    def test_main_checkout_logs_outside_stay_refused(self):
        outside = self.main.parent.parent / 'outside'
        outside.mkdir()
        (self.main / 'dev/logs').symlink_to(outside, target_is_directory=True)
        result = self.invoke(self.main, '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', REFUSED))
        self.assertEqual(list(outside.iterdir()), [])
        self.unchanged()

    def test_main_checkout_logs_inside_still_work(self):
        result = self.invoke(self.main, '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertEqual(result.stdout.splitlines()[0], 'phase=tests database=cc_test_coffee exit=0')
        self.assertEqual(len(list((self.main / 'dev/logs/odoo19').iterdir())), 1)


LOGS_REFUSED = 'Compact logs must remain inside the configured logs directory.\n'


@unittest.skipUnless(shutil.which('git'), 'git is required')
class ConfiguredLogsCompactTests(unittest.TestCase):
    """[tooling].logs sends compact runs to <logs>/odoo19/<main|slug>/run-* for every checkout."""
    setUp_fixture = lifecycle.LifecycleTests.setUp
    unchanged = lifecycle.LifecycleTests.unchanged
    git = LinkedWorktreeCompactTests.git

    def setUp(self):
        LinkedWorktreeCompactTests.setUp(self)
        # <projects>/logs, shared by '<projects>/a project' and '<projects>/a project-wt'.
        self.logs = self.main.parent / 'logs'
        for root in (self.main, self.linked):
            profile = root / '.odoo19-agent.toml'
            profile.write_text(profile.read_text() + "logs = '../logs'\n")

    def invoke(self, root, command, *args):
        path = root / 'dev/scripts' / command
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((lifecycle.STAGE / 'project-wrappers' / command).read_bytes())
        return subprocess.run(['bash', str(path), *args], text=True, cwd=root, env=self.env,
                              capture_output=True)

    def assert_single_run(self, root, checkout_id, database):
        result = self.invoke(root, 'test-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], f'phase=tests database={database} exit=0')
        logs = dict(line.split('=', 1) for line in lines[1:])
        runs = list((self.logs / 'odoo19' / checkout_id).iterdir())
        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0].name.startswith('run-'))
        self.assertEqual(Path(logs['stdout_log']), runs[0] / 'stdout.log')
        self.assertEqual(Path(logs['stderr_log']), runs[0] / 'stderr.log')
        for directory in (self.logs, self.logs / 'odoo19', self.logs / 'odoo19' / checkout_id, runs[0]):
            with self.subTest(directory=directory):
                self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        # No dev/ log directory is needed in either checkout.
        self.assertFalse((self.main / 'dev/logs').exists())
        self.assertFalse((self.linked / 'dev/logs').exists())

    def test_main_checkout_runs_go_under_the_main_id(self):
        self.assert_single_run(self.main, 'main', 'cc_test_coffee')

    def test_linked_worktree_runs_go_under_its_slug(self):
        self.assert_single_run(self.linked, 'wt', 'cc_test_wt_coffee')

    def test_each_checkout_keeps_its_own_directory(self):
        for root in (self.main, self.linked):
            result = self.invoke(root, 'test-module', '--compact', 'coffee')
            self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertEqual(sorted(path.name for path in (self.logs / 'odoo19').iterdir()), ['main', 'wt'])

    def test_verify_module_uses_the_same_directory(self):
        result = self.invoke(self.linked, 'verify-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        runs = list((self.logs / 'odoo19' / 'wt').iterdir())
        self.assertEqual(len(runs), 1)
        paths = [Path(line.split('=', 1)[1]) for line in result.stdout.splitlines()
                 if line.startswith(('stdout_log=', 'stderr_log='))]
        self.assertEqual(len(paths), 8)
        self.assertTrue(all(path.parent == runs[0] for path in paths), paths)

    def test_checkout_directory_escaping_the_logs_directory_is_refused(self):
        outside = self.main.parent.parent / 'outside'
        outside.mkdir()
        (self.logs / 'odoo19').mkdir(parents=True)
        for root, checkout_id in ((self.main, 'main'), (self.linked, 'wt')):
            (self.logs / 'odoo19' / checkout_id).symlink_to(outside, target_is_directory=True)
            for command in ('test-module', 'verify-module'):
                with self.subTest(checkout=checkout_id, command=command):
                    result = self.invoke(root, command, '--compact', 'coffee')
                    self.assertEqual((result.returncode, result.stdout, result.stderr),
                                     (1, '', LOGS_REFUSED))
                    self.assertEqual(list(outside.iterdir()), [])
                    self.unchanged()

    def test_odoo19_directory_escaping_the_logs_directory_is_refused(self):
        outside = self.main.parent.parent / 'outside'
        outside.mkdir()
        self.logs.mkdir()
        (self.logs / 'odoo19').symlink_to(outside, target_is_directory=True)
        result = self.invoke(self.main, 'test-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', LOGS_REFUSED))
        self.assertEqual(list(outside.iterdir()), [])
        self.unchanged()

    def test_dev_logs_link_is_ignored_when_the_key_is_set(self):
        outside = self.main.parent.parent / 'outside'
        outside.mkdir()
        (self.main / 'dev/logs').symlink_to(outside, target_is_directory=True)
        result = self.invoke(self.main, 'test-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(len(list((self.logs / 'odoo19' / 'main').iterdir())), 1)
