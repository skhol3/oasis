"""Compact execution must preserve fail-closed behavior and evidence."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
from pathlib import Path
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import unittest
import test_lifecycle as lifecycle

LOGS_REFUSED = 'Compact logs must remain inside the configured logs directory.\n'
# The decision oasis_test_summary makes (pi/lib/tools.ts formatBackgroundRun with the real file
# system), for the checkout's tools/config.py values and what test-module --compact printed.
SUMMARY = """
import { readFileSync, realpathSync } from "node:fs";
import { pathToFileURL } from "node:url";
const { formatBackgroundRun } = await import(pathToFileURL(process.env.OASIS_TOOLS_TS).href);
const { config, output } = JSON.parse(process.env.OASIS_SUMMARY_INPUT);
try {
  const files = { realpath: realpathSync, readLog: (path) => readFileSync(path, "utf8") };
  console.log(formatBackgroundRun("coffee", output, config, files, { maxFailures: 10, traceLines: 6 }));
} catch (error) {
  console.log(`refused: ${error.message}`);
}
"""


def summary_of(test, root, output):
    """What oasis_test_summary would answer in the checkout at root for this compact output."""
    if not shutil.which('node'):
        test.skipTest('node is required')
    values = subprocess.run(['python3', '-B', str(lifecycle.STAGE / 'tools/config.py'), str(root)],
                            text=True, capture_output=True, env=test.env, check=True).stdout
    config = dict(word.split('=', 1) for word in shlex.split(values))
    result = subprocess.run(
        ['node', '--input-type=module', '-e', SUMMARY], text=True, capture_output=True, timeout=60,
        env={**test.env, 'OASIS_TOOLS_TS': str(lifecycle.STAGE / 'pi/lib/tools.ts'),
             'OASIS_SUMMARY_INPUT': json.dumps({'config': config, 'output': output})})
    test.assertEqual((result.returncode, result.stderr), (0, ''))
    return result.stdout
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
        self.assertRegex(lines[0], r'^phase=tests database=cc_test_coffee_r[0-9a-f]{6} exit=41$')
        self.assertEqual(lines[1], 'database_lifecycle=disposable dropped=yes')
        logs = dict(line.split('=', 1) for line in lines[1:])
        self.assertEqual(Path(logs['stdout_log']).read_text(), '')
        self.assertEqual(Path(logs['stderr_log']).read_text(), 'database unavailable\n')
        self.assertNotIn('dropdb ', self.commands.read_text())
        self.assertNotIn('odoo ', self.commands.read_text())

    def test_outside_log_symlink_rejected_before_effects(self):
        # Without [tooling].logs the logs are <workspace directory>/logs (v0.17.0): its checkout directory
        # may not lead out of it.
        outside = self.root.parent / 'outside'
        outside.mkdir()
        sentinel = outside / 'sentinel'
        sentinel.write_bytes(b'unchanged')
        (self.root / 'logs').mkdir()
        (self.root / 'logs/main').symlink_to(outside, target_is_directory=True)
        profile = self.root / 'oasis-workspace.toml'
        before = hashlib.sha256(profile.read_bytes()).digest()
        for command in ('test-module', 'verify-module'):
            with self.subTest(command=command):
                result = self.invoke(command, '--compact', 'coffee')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', LOGS_REFUSED))
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
        self.assertRegex(result.stdout,
                         r'(?m)^phase=current_code_update database=cc_test_coffee_r[0-9a-f]{6}_update exit=7$')
        self.assertIn('current_code_update_exit=7\n', result.stdout)
        paths = [Path(line.split('=', 1)[1]) for line in result.stdout.splitlines()
                 if line.startswith(('stdout_log=', 'stderr_log='))]
        self.assertEqual(len(paths), 8)
        self.assertTrue(any(p.read_text() == 'update out\n' for p in paths))
        self.assertTrue(any(p.read_text() == 'update err\n' for p in paths))


@unittest.skipUnless(shutil.which('git'), 'git is required')
class LinkedWorktreeCompactTests(unittest.TestCase):
    """Without [tooling].logs, a checkout's compact runs go to <workspace directory>/logs/<main|slug>/run-*, as
    setup writes the key (v0.17.0); here each checkout reads a workspace file of its own."""
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
        self.git(self.main, 'add', 'oasis-workspace.toml')
        self.git(self.main, 'commit', '-q', '-m', 'profile')
        self.linked = self.main.parent / 'a project-wt'
        self.git(self.main, 'worktree', 'add', '-q', '-b', 'wt', str(self.linked))
        # The linked checkout gets its own runtime files; a neutral env file name.
        (self.linked / 'oasis-workspace.toml').write_text(
            lifecycle.WORKSPACE.replace("env_file = 'dev/.env'", "env_file = 'dev/runtime-env'"))
        for name in ('dev/odoo.conf', 'dev/runtime-env', 'dev/compose.yml', 'coffee/__manifest__.py'):
            path = self.linked / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    def git(self, cwd, *args):
        subprocess.run([*GIT, '-C', str(cwd), *args], check=True, capture_output=True, env=self.env)

    def invoke(self, root, *args):
        return subprocess.run(lifecycle.oasis_argv(root, 'test-module', *args), text=True, cwd=root, env=self.env,
                              capture_output=True)

    def run_of(self, root, result, checkout_id):
        """The one run directory of a compact run in root's default logs, <root>/logs/<checkout_id>."""
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        logs = dict(line.split('=', 1) for line in result.stdout.splitlines()[1:])
        runs = list((root / 'logs' / checkout_id).iterdir())
        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0].name.startswith('run-'))
        self.assertEqual(Path(logs['stdout_log']), runs[0] / 'stdout.log')
        self.assertEqual(Path(logs['stderr_log']), runs[0] / 'stderr.log')
        self.assertEqual(runs[0].stat().st_mode & 0o777, 0o700)
        return logs

    def test_linked_worktree_runs_go_to_the_logs_next_to_its_workspace_file(self):
        result = self.invoke(self.linked, '--compact', 'coffee')
        self.assertRegex(result.stdout.splitlines()[0], r'^phase=tests database=cc_test_wt_coffee_r[0-9a-f]{6} exit=0$')
        logs = self.run_of(self.linked, result, 'wt')
        summary = summary_of(self, self.linked, result.stdout)
        self.assertTrue(summary.startswith('module=coffee database=cc_test_wt_coffee_r'), summary)
        self.assertIn(f"logs: {logs['stdout_log']} {logs['stderr_log']}", summary)
        for root in (self.main, self.linked):
            self.assertFalse((root / 'dev/logs').exists())
        self.assertFalse((self.main / 'logs').exists())

    def test_main_checkout_runs_go_under_the_main_id(self):
        result = self.invoke(self.main, '--compact', 'coffee')
        self.assertRegex(result.stdout.splitlines()[0], r'^phase=tests database=cc_test_coffee_r[0-9a-f]{6} exit=0$')
        self.run_of(self.main, result, 'main')
        self.assertFalse((self.main / 'dev/logs').exists())

    def test_a_dev_logs_directory_is_neither_written_nor_read(self):
        # Before 0.17.0 a checkout without [tooling].logs used dev/logs/odoo19, which a linked worktree could link
        # to the main checkout's: that directory is no log location any more.
        (self.main / 'dev/logs/odoo19/run-1').mkdir(parents=True)
        (self.main / 'dev/logs/odoo19/run-1/stdout.log').write_text('old run\n')
        (self.main / 'dev/logs/odoo19/run-1/stderr.log').write_text('')
        (self.linked / 'dev/logs').symlink_to(self.main / 'dev/logs', target_is_directory=True)
        result = self.invoke(self.linked, '--compact', 'coffee')
        self.run_of(self.linked, result, 'wt')
        self.assertEqual(sorted(path.name for path in (self.main / 'dev/logs/odoo19').iterdir()), ['run-1'])
        old = ('phase=tests database=cc_test_wt_coffee_r1a2b3c exit=0\n'
               f'stdout_log={self.linked}/dev/logs/odoo19/run-1/stdout.log\n'
               f'stderr_log={self.linked}/dev/logs/odoo19/run-1/stderr.log\n')
        for root in (self.main, self.linked):
            with self.subTest(root=root.name):
                self.assertEqual(summary_of(self, root, old.replace(str(self.linked), str(root))).split(':', 1)[0],
                                 'refused')

    def test_a_checkout_directory_escaping_the_default_logs_is_refused(self):
        outside = self.main.parent.parent / 'outside'
        outside.mkdir()
        for root, checkout_id in ((self.main, 'main'), (self.linked, 'wt')):
            (root / 'logs').mkdir()
            (root / 'logs' / checkout_id).symlink_to(outside, target_is_directory=True)
            with self.subTest(checkout=checkout_id):
                result = self.invoke(root, '--compact', 'coffee')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', LOGS_REFUSED))
                self.assertEqual(list(outside.iterdir()), [])
                self.unchanged()


@unittest.skipUnless(shutil.which('git'), 'git is required')
class ConfiguredLogsCompactTests(unittest.TestCase):
    """[tooling].logs sends compact runs to <logs>/<main|slug>/run-* for every checkout."""
    setUp_fixture = lifecycle.LifecycleTests.setUp
    unchanged = lifecycle.LifecycleTests.unchanged
    git = LinkedWorktreeCompactTests.git

    def setUp(self):
        LinkedWorktreeCompactTests.setUp(self)
        # <projects>/logs, shared by '<projects>/a project' and '<projects>/a project-wt'.
        self.logs = self.main.parent / 'logs'
        for root in (self.main, self.linked):
            profile = root / 'oasis-workspace.toml'
            profile.write_text(profile.read_text() + "logs = '../logs'\n")

    def invoke(self, root, command, *args):
        return subprocess.run(lifecycle.oasis_argv(root, command, *args), text=True, cwd=root, env=self.env,
                              capture_output=True)

    def assert_single_run(self, root, checkout_id, database):
        result = self.invoke(root, 'test-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        lines = result.stdout.splitlines()
        self.assertRegex(lines[0], '^' + re.escape(f'phase=tests database={database}') + r'_r[0-9a-f]{6} exit=0$')
        self.assertEqual(lines[1], 'database_lifecycle=disposable dropped=yes')
        logs = dict(line.split('=', 1) for line in lines[1:])
        runs = list((self.logs / checkout_id).iterdir())
        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0].name.startswith('run-'))
        self.assertEqual(Path(logs['stdout_log']), runs[0] / 'stdout.log')
        self.assertEqual(Path(logs['stderr_log']), runs[0] / 'stderr.log')
        # No odoo19/ level below the logs directory.
        self.assertEqual([path.name for path in self.logs.iterdir()], [checkout_id])
        for directory in (self.logs, self.logs / checkout_id, runs[0]):
            with self.subTest(directory=directory):
                self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        # No dev/ log directory is needed in either checkout.
        self.assertFalse((self.main / 'dev/logs').exists())
        self.assertFalse((self.linked / 'dev/logs').exists())

    def test_a_logs_path_with_a_link_or_dotdot_still_gives_readable_runs(self):
        # tools/config.py resolves [tooling].logs, so compact.sh prints paths below the real
        # directory and oasis_test_summary reads them.
        (self.main.parent / 'logs-link').symlink_to('logs', target_is_directory=True)
        self.logs.mkdir()
        profile = self.main / 'oasis-workspace.toml'
        text = profile.read_text()
        for spelling in ("../logs-link", "dev/../../logs"):
            with self.subTest(logs=spelling):
                profile.write_text(text.replace("logs = '../logs'\n", f"logs = '{spelling}'\n"))
                result = self.invoke(self.main, 'test-module', '--compact', 'coffee')
                self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
                logs = dict(line.split('=', 1) for line in result.stdout.splitlines()[1:])
                self.assertEqual(Path(logs['stdout_log']).parent.parent, self.logs / 'main')
                summary = summary_of(self, self.main, result.stdout)
                self.assertTrue(summary.startswith('module=coffee database=cc_test_coffee_r'), summary)
                self.assertIn(f"logs: {logs['stdout_log']} {logs['stderr_log']}", summary)
                # Named through the link instead, it is not below the resolved LOGS_DIR: refused.
                linked = result.stdout.replace(str(self.logs), str(self.main.parent / 'logs-link'))
                self.assertEqual(summary_of(self, self.main, linked).split(':', 1)[0], 'refused')

    def test_main_checkout_runs_go_under_the_main_id(self):
        self.assert_single_run(self.main, 'main', 'cc_test_coffee')

    def test_linked_worktree_runs_go_under_its_slug(self):
        self.assert_single_run(self.linked, 'wt', 'cc_test_wt_coffee')

    def test_each_checkout_keeps_its_own_directory(self):
        for root in (self.main, self.linked):
            result = self.invoke(root, 'test-module', '--compact', 'coffee')
            self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertEqual(sorted(path.name for path in self.logs.iterdir()), ['main', 'wt'])

    def test_verify_module_uses_the_same_directory(self):
        result = self.invoke(self.linked, 'verify-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        runs = list((self.logs / 'wt').iterdir())
        self.assertEqual(len(runs), 1)
        paths = [Path(line.split('=', 1)[1]) for line in result.stdout.splitlines()
                 if line.startswith(('stdout_log=', 'stderr_log='))]
        self.assertEqual(len(paths), 8)
        self.assertTrue(all(path.parent == runs[0] for path in paths), paths)

    def test_checkout_directory_escaping_the_logs_directory_is_refused(self):
        outside = self.main.parent.parent / 'outside'
        outside.mkdir()
        self.logs.mkdir()
        for root, checkout_id in ((self.main, 'main'), (self.linked, 'wt')):
            (self.logs / checkout_id).symlink_to(outside, target_is_directory=True)
            for command in ('test-module', 'verify-module'):
                with self.subTest(checkout=checkout_id, command=command):
                    result = self.invoke(root, command, '--compact', 'coffee')
                    self.assertEqual((result.returncode, result.stdout, result.stderr),
                                     (1, '', LOGS_REFUSED))
                    self.assertEqual(list(outside.iterdir()), [])
                    self.unchanged()

    def test_existing_odoo19_runs_are_left_where_they_are(self):
        # Runs of the previous layout (<logs>/odoo19/<checkout>/run-*) are never moved or deleted.
        old = self.logs / 'odoo19' / 'main' / 'run-old'
        old.mkdir(parents=True)
        (old / 'stdout.log').write_text('old run\n')
        before = sorted(path.relative_to(self.logs) for path in (self.logs / 'odoo19').rglob('*'))
        self.assert_new_run_beside_the_old_layout()
        self.assertEqual(sorted(path.relative_to(self.logs) for path in (self.logs / 'odoo19').rglob('*')), before)
        self.assertEqual((old / 'stdout.log').read_text(), 'old run\n')

    def test_an_odoo19_link_in_the_logs_directory_is_not_followed(self):
        outside = self.main.parent.parent / 'outside'
        outside.mkdir()
        self.logs.mkdir()
        (self.logs / 'odoo19').symlink_to(outside, target_is_directory=True)
        self.assert_new_run_beside_the_old_layout()
        self.assertEqual(list(outside.iterdir()), [])

    def assert_new_run_beside_the_old_layout(self):
        result = self.invoke(self.main, 'test-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        runs = list((self.logs / 'main').iterdir())
        self.assertEqual(len(runs), 1)
        self.assertIn(f'stdout_log={runs[0] / "stdout.log"}', result.stdout.splitlines())
        self.assertEqual(sorted(path.name for path in self.logs.iterdir()), ['main', 'odoo19'])

    def test_dev_logs_link_is_ignored_when_the_key_is_set(self):
        outside = self.main.parent.parent / 'outside'
        outside.mkdir()
        (self.main / 'dev/logs').symlink_to(outside, target_is_directory=True)
        result = self.invoke(self.main, 'test-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(len(list((self.logs / 'main').iterdir())), 1)
