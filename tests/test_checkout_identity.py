"""Checkout identity (kind and slug) emitted by tools/config.py for real git checkouts.

Every repository lives in a fresh system temp directory; git runs with explicit -c identity
flags and never reads or writes the user's global configuration.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
READER = ROOT / 'tools' / 'config.py'
# A workspace file in each checkout (committed, so a linked worktree has its own copy).
WORKSPACE = (ROOT / 'tests' / 'fixture-workspace.toml').read_text()
# Appended after WORKSPACE_ROOT: the Odoo 19.0 options, no named environment, then DATA_DIR
# (empty without [tooling].data_dir) and AGENT_DESTRUCTIVE (ask by default).
APPENDED = ['ODOO_VERSION=19.0', 'ODOO_SECOND_PORT_OPTION=--gevent-port', 'ODOO_DEMO_OFF_ARGS=--without-demo',
            "ENVIRONMENT_NAME=''", 'PYTHON_VERSION=3.12', "DATA_DIR=''", 'AGENT_DESTRUCTIVE=ask']
GIT = ['git', '-c', 'user.name=oasis tests', '-c', 'user.email=tests@example.invalid',
       '-c', 'init.defaultBranch=main', '-c', 'commit.gpgsign=false']


@unittest.skipUnless(shutil.which('git'), 'git is required')
class CheckoutIdentityTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix='oasis-checkout-'))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        # Keep git discovery inside the scratch directory, whatever surrounds the temp dir.
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        self.env.update({'GIT_CEILING_DIRECTORIES': str(self.scratch), 'GIT_CONFIG_GLOBAL': os.devnull,
                         'GIT_CONFIG_NOSYSTEM': '1', 'PYTHONDONTWRITEBYTECODE': '1'})

    def git(self, cwd, *args):
        subprocess.run([*GIT, '-C', str(cwd), *args], check=True, capture_output=True, env=self.env)

    def project(self, name='proj'):
        root = self.scratch / name
        root.mkdir()
        (root / 'oasis-workspace.toml').write_text(WORKSPACE)
        return root

    def slug(self, root, line):
        """The checkout's oasis-checkout.toml with this [tooling].checkout_slug line."""
        (root / 'oasis-checkout.toml').write_text('[tooling]\n' + line)

    def repository(self, name='proj'):
        root = self.project(name)
        self.git(root, 'init', '-q')
        self.git(root, 'add', 'oasis-workspace.toml')
        self.git(root, 'commit', '-q', '-m', 'workspace')
        return root

    def worktree(self, main, name):
        self.git(main, 'worktree', 'add', '-q', '-b', 'wt-' + str(len(name)), '../' + name)
        return self.scratch / name

    def run_reader(self, root, env=None):
        return subprocess.run([sys.executable, '-B', str(READER), str(root)],
                              capture_output=True, text=True, env=env or self.env)

    def failing_git(self, script):
        """An environment whose `git` is a fake running script (sh); the fixtures keep real git."""
        bindir = Path(tempfile.mkdtemp(prefix='fake-git-', dir=self.scratch))
        fake = bindir / 'git'
        fake.write_text('#!/bin/sh\n' + script)
        fake.chmod(0o755)
        return {**self.env, 'PATH': f'{bindir}:{self.env["PATH"]}'}

    def without_git(self):
        """An environment whose PATH has no git at all (running it raises OSError)."""
        empty = self.scratch / 'no-git'
        empty.mkdir(exist_ok=True)
        return {**self.env, 'PATH': str(empty)}

    def failures(self):
        """(label, environment, reason) for each way git detection can fail."""
        return (('exit', self.failing_git('echo "fatal: broken" >&2\nexit 1\n'), 'exit 1: fatal: broken'),
                ('output', self.failing_git('echo /only/one/line\n'), 'unexpected output'),
                ('missing', self.without_git(), 'cannot run git: No such file or directory'))

    def assert_failure(self, root, env, message):
        result = self.run_reader(root, env)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', f'ERROR: {message}\n'))

    def assignments(self, root):
        result = self.run_reader(root)
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        return result.stdout.splitlines()

    def identity(self, root):
        lines = self.assignments(root)
        return [line for line in lines if line.startswith(('CHECKOUT_KIND=', 'CHECKOUT_SLUG='))]

    def main_root(self, root):
        lines = [line for line in self.assignments(root) if line.startswith('CHECKOUT_MAIN_ROOT=')]
        self.assertEqual(len(lines), 1, lines)
        return lines[0]

    def previous_assignments(self, root):
        """The exact lines config.py emitted before the checkout identity existed."""
        root = root.resolve()
        values = {
            'PROJECT_ROOT': str(root), 'PROJECT_NAME': root.name,
            'DEV_PREFIX': 'cc_dev_', 'TEST_PREFIX': 'cc_test_', 'TEST_DATABASE': '',
            'ODOO_SOURCE': str((root / '../../source/odoo').resolve()),
            'PROJECT_ENVIRONMENT': str((root / '../../environments/example').resolve()),
            'ODOO_CONFIG': str(root / 'dev/odoo.conf'), 'ENV_FILE': str(root / 'dev/.env'),
            'COMPOSE_FILE': str(root / 'dev/compose.yml'),
            'REQUIREMENTS_DIR': str(root / 'dev/requirements'), 'ADDON_ROOTS': str(root),
            'DB_SERVICE': 'db',
            'PYTHON': str((root / '../../environments/example').resolve() / 'bin/python'),
            'ODOO_BIN': str((root / '../../source/odoo').resolve() / 'odoo-bin'),
            'ENVIRONMENTS_DIR': str((root / '../../environments').resolve()),
        }
        return [f'{name}={shlex.quote(value)}' for name, value in values.items()]

    def workspace_root(self, root):
        return 'WORKSPACE_ROOT=' + shlex.quote(str(root.resolve()))

    def assert_rejected(self, root, message):
        result = self.run_reader(root)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', f'ERROR: {message}\n'))

    def test_main_checkout_has_no_slug(self):
        main = self.repository()
        self.assertEqual(self.identity(main), ["CHECKOUT_KIND=main", "CHECKOUT_SLUG=''"])

    def test_linked_worktree_strips_the_main_directory_prefix(self):
        linked = self.worktree(self.repository('proj'), 'proj-07.1')
        self.assertEqual(self.identity(linked), ['CHECKOUT_KIND=linked', 'CHECKOUT_SLUG=07_1'])

    def test_linked_worktree_with_unrelated_name_is_normalized(self):
        linked = self.worktree(self.repository('proj'), 'Feature Branch!')
        self.assertEqual(self.identity(linked), ['CHECKOUT_KIND=linked', 'CHECKOUT_SLUG=feature_branch'])

    def test_checkout_file_slug_overrides_the_main_checkout(self):
        main = self.repository()
        self.slug(main, "checkout_slug = 'base'\n")
        self.assertEqual(self.identity(main), ['CHECKOUT_KIND=main', 'CHECKOUT_SLUG=base'])

    def test_checkout_file_slug_overrides_a_linked_worktree(self):
        linked = self.worktree(self.repository('proj'), 'proj-07.1')
        self.slug(linked, "checkout_slug = 'mrp_2'\n")
        self.assertEqual(self.identity(linked), ['CHECKOUT_KIND=linked', 'CHECKOUT_SLUG=mrp_2'])

    def test_checkout_file_slug_applies_outside_git(self):
        root = self.project()
        self.slug(root, "checkout_slug = 'solo'\n")
        self.assertEqual(self.identity(root), ['CHECKOUT_KIND=none', 'CHECKOUT_SLUG=solo'])

    def test_invalid_checkout_file_slug_is_rejected_without_assignments(self):
        main = self.repository()
        for value in ("''", "'07.1'", "'Upper'", "'_lead'", "'a" + 'b' * 20 + "'", '7'):
            with self.subTest(value=value):
                self.slug(main, f'checkout_slug = {value}\n')
                self.assert_rejected(main, 'Invalid tooling checkout slug.')

    def test_twenty_byte_checkout_file_slug_is_accepted(self):
        main = self.repository()
        self.slug(main, "checkout_slug = 'a" + '1' * 19 + "'\n")
        self.assertEqual(self.identity(main), ['CHECKOUT_KIND=main', 'CHECKOUT_SLUG=a' + '1' * 19])

    def test_too_long_derived_slug_requires_the_checkout_setting(self):
        linked = self.worktree(self.repository('proj'), 'proj-' + 'x' * 21)
        self.assert_rejected(linked, 'Cannot derive a checkout slug from the worktree directory name; '
                                     'set [tooling].checkout_slug.')

    def test_empty_derived_slug_requires_the_checkout_setting(self):
        linked = self.worktree(self.repository('proj'), 'proj--')
        self.assert_rejected(linked, 'Cannot derive a checkout slug from the worktree directory name; '
                                     'set [tooling].checkout_slug.')

    def test_project_outside_git_reports_none(self):
        root = self.project()
        self.assertEqual(self.identity(root), ["CHECKOUT_KIND=none", "CHECKOUT_SLUG=''"])

    def test_previous_assignments_are_unchanged_and_identity_is_appended(self):
        main = self.repository('proj')
        linked = self.worktree(main, 'proj-07.1')
        outside = self.project('outside')
        main_line = 'CHECKOUT_MAIN_ROOT=' + shlex.quote(str(main.resolve()))
        # Only LOGS_DIR (empty without [tooling].logs), WORKSPACE_ROOT (each checkout's own here) and
        # the Odoo series options, environment and DATA_DIR (APPENDED) follow the identity.
        for root, identity in ((main, ["CHECKOUT_KIND=main", "CHECKOUT_SLUG=''", main_line,
                                       "LOGS_DIR=''", self.workspace_root(main), *APPENDED]),
                               (linked, ['CHECKOUT_KIND=linked', 'CHECKOUT_SLUG=07_1', main_line,
                                         "LOGS_DIR=''", self.workspace_root(linked), *APPENDED]),
                               (outside, ["CHECKOUT_KIND=none", "CHECKOUT_SLUG=''", "CHECKOUT_MAIN_ROOT=''",
                                          "LOGS_DIR=''", self.workspace_root(outside), *APPENDED])):
            with self.subTest(root=root.name):
                self.assertEqual(self.assignments(root), self.previous_assignments(root) + identity)

    def test_main_root_names_the_main_checkout(self):
        main = self.repository('proj')
        linked = self.worktree(main, 'proj-07.1')
        quoted = 'CHECKOUT_MAIN_ROOT=' + shlex.quote(str(main.resolve()))
        self.assertEqual(self.main_root(main), quoted)
        self.assertEqual(self.main_root(linked), quoted)
        self.assertEqual(self.main_root(self.project('outside')), "CHECKOUT_MAIN_ROOT=''")

    def test_main_root_of_a_project_below_the_main_top_level_is_the_project(self):
        main = self.repository('repo')
        nested = main / 'sub project'
        nested.mkdir()
        (nested / 'oasis-workspace.toml').write_text(WORKSPACE)
        self.assertEqual(self.main_root(nested),
                         'CHECKOUT_MAIN_ROOT=' + shlex.quote(str(nested.resolve())))

    LINKED_FAILURE = ('Cannot determine the checkout identity: git failed in a linked worktree; '
                      'check git or set [tooling].checkout_slug.')

    def test_git_failure_in_a_linked_worktree_fails_closed(self):
        linked = self.worktree(self.repository('proj'), 'proj-07.1')
        for label, env, _reason in self.failures():
            with self.subTest(failure=label):
                self.assert_failure(linked, env, self.LINKED_FAILURE)
        # A project directory below the worktree's top level finds the same gitfile.
        nested = linked / 'sub'
        nested.mkdir()
        (nested / 'oasis-workspace.toml').write_text(WORKSPACE)
        self.assert_failure(nested, self.failures()[0][1], self.LINKED_FAILURE)

    def test_git_failure_in_a_linked_worktree_uses_the_checkout_file_slug(self):
        linked = self.worktree(self.repository('proj'), 'proj-07.1')
        self.slug(linked, "checkout_slug = 'mrp_2'\n")
        for label, env, _reason in self.failures():
            with self.subTest(failure=label):
                result = self.run_reader(linked, env)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                lines = result.stdout.splitlines()
                # The main checkout is unknown without git: CHECKOUT_MAIN_ROOT stays empty.
                self.assertEqual(lines[-12:], ['CHECKOUT_KIND=linked', 'CHECKOUT_SLUG=mrp_2', "CHECKOUT_MAIN_ROOT=''",
                                               "LOGS_DIR=''", self.workspace_root(linked), *APPENDED])
                self.assertEqual(lines[:-12], self.previous_assignments(linked))

    def test_git_failure_in_a_main_checkout_fails_closed(self):
        main = self.repository('proj')
        nested = main / 'sub'
        nested.mkdir()
        (nested / 'oasis-workspace.toml').write_text(WORKSPACE)
        for label, env, reason in self.failures():
            for root in (main, nested):
                with self.subTest(failure=label, root=root.name):
                    self.assert_failure(root, env, f'Cannot determine the checkout identity: git failed ({reason}).')
        # A checkout file slug does not replace the identity there: the checkout kind is unknown.
        self.slug(main, "checkout_slug = 'base'\n")
        self.assert_failure(main, self.failures()[0][1],
                            'Cannot determine the checkout identity: git failed (exit 1: fatal: broken).')

    def test_git_failure_outside_git_still_reports_none(self):
        root = self.project()
        for label, env, _reason in self.failures():
            with self.subTest(failure=label):
                result = self.run_reader(root, env)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(result.stdout.splitlines(), self.previous_assignments(root) + [
                    "CHECKOUT_KIND=none", "CHECKOUT_SLUG=''", "CHECKOUT_MAIN_ROOT=''", "LOGS_DIR=''",
                    self.workspace_root(root), *APPENDED])

    def test_a_repository_above_the_git_ceiling_is_not_searched(self):
        # Real git stops at GIT_CEILING_DIRECTORIES (the scratch directory): a .git above it
        # is not this project's, so its "not a git repository" failure keeps kind none.
        self.git(self.scratch, 'init', '-q')
        root = self.project()
        self.assertEqual(self.identity(root), ["CHECKOUT_KIND=none", "CHECKOUT_SLUG=''"])

    def test_git_location_overrides_do_not_change_the_identity(self):
        main = self.repository('proj')
        linked = self.worktree(main, 'proj-07.1')
        self.env.update({'GIT_DIR': str(main / '.git'), 'GIT_WORK_TREE': str(main)})
        self.assertEqual(self.identity(linked), ['CHECKOUT_KIND=linked', 'CHECKOUT_SLUG=07_1'])


if __name__ == '__main__':
    unittest.main()
