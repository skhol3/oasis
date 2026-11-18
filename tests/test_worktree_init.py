"""`odoo19 --project <checkout> worktree-init <feature> <branch> [--dry-run]` on synthetic repos.

Every repository lives in a fresh system temp directory; git runs with explicit -c identity
flags, an empty global configuration and a ceiling at the scratch directory, so it never
reads or writes the user's configuration or a real project. The environment file is named
neutrally (`dev/runtime-env`) through the profile's `env_file`.
"""
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'odoo19'
READER = ROOT / 'tools' / 'config.py'
GIT = ['git', '-c', 'user.name=oasis tests', '-c', 'user.email=tests@example.invalid',
       '-c', 'init.defaultBranch=main', '-c', 'commit.gpgsign=false']
PROFILE = (ROOT / 'tests' / 'fixture-profile.toml').read_text().replace(
    "env_file = 'dev/.env'", "env_file = 'dev/runtime-env'")
CONF = ('[options]\n'
        'addons_path = /x,{main},{main}/extra,{main}-other/addons,/y\n'
        'db_name = cc_dev_main\n'
        'logfile = {main}/dev/logs/odoo.log\n'
        'admin_passwd = fixture-only\n')


@unittest.skipUnless(shutil.which('git'), 'git is required')
class WorktreeInitTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix='oasis-worktree-')).resolve()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        self.env.update({'GIT_CEILING_DIRECTORIES': str(self.scratch), 'GIT_CONFIG_GLOBAL': os.devnull,
                         'GIT_CONFIG_NOSYSTEM': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
        self.main = self.scratch / 'proj'

    # -- fixtures ---------------------------------------------------------------------------

    def git(self, cwd, *args):
        result = subprocess.run([*GIT, '-C', str(cwd), *args], check=True, capture_output=True,
                                text=True, env=self.env)
        return result.stdout.strip()

    def repository(self, gitignore='dev/\n', profile=PROFILE):
        """Main checkout: committed README and .gitignore, untracked profile, ignored dev/."""
        main = self.main
        main.mkdir()
        (main / 'README.md').write_text('fixture\n')
        (main / '.gitignore').write_text(gitignore)
        self.git(main, 'init', '-q')
        self.git(main, 'add', 'README.md', '.gitignore')
        self.git(main, 'commit', '-q', '-m', 'init')
        (main / '.odoo19-agent.toml').write_text(profile)
        dev = main / 'dev'
        (dev / 'logs' / 'odoo19').mkdir(parents=True)
        (dev / 'logs' / 'odoo19' / 'run.log').write_text('log\n')
        (dev / 'runtime').mkdir()
        (dev / 'runtime' / 'odoo.pid').write_text('1\n')
        (dev / 'compose.yml').write_text('services: {}\n')
        (dev / 'odoo.conf').write_text(CONF.format(main=main))
        (dev / 'runtime-env').write_text('FIXTURE=1\n')
        return main

    def invoke(self, project, *args):
        return subprocess.run([sys.executable, '-B', str(CLI), '--project', str(project),
                               'worktree-init', *args],
                              capture_output=True, text=True, env=self.env, cwd=self.scratch)

    def head(self, cwd):
        return self.git(cwd, 'rev-parse', 'HEAD')

    def branches(self, cwd):
        return self.git(cwd, 'for-each-ref', '--format=%(refname)', 'refs/heads')

    def worktrees(self, cwd):
        return self.git(cwd, 'worktree', 'list', '--porcelain')

    def snapshot(self):
        return sorted(str(path.relative_to(self.scratch)) for path in self.scratch.rglob('*')
                      if '.git' not in path.relative_to(self.scratch).parts)

    def identity(self, root):
        result = subprocess.run([sys.executable, '-B', str(READER), str(root)],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        return [line for line in result.stdout.splitlines()
                if line.startswith(('CHECKOUT_KIND=', 'CHECKOUT_SLUG='))]

    def plan(self, new, branch_line, slug):
        main = self.main
        return (f'worktree: {new}\n'
                f'branch: {branch_line}\n'
                f'slug: {slug}\n'
                'copied .odoo19-agent.toml\n'
                'created dir dev\n'
                f'linked dev/compose.yml -> {main}/dev/compose.yml\n'
                f'linked dev/logs -> {main}/dev/logs\n'
                'copied dev/odoo.conf\n'
                'rewrote addons_path in dev/odoo.conf\n'
                'removed db_name from dev/odoo.conf\n'
                'created dir dev/runtime\n'
                f'linked dev/runtime-env -> {main}/dev/runtime-env\n')

    def assert_prepared(self, new):
        main = self.main
        self.assertEqual((new / '.odoo19-agent.toml').read_text(), PROFILE)
        self.assertFalse((new / '.odoo19-agent.toml').is_symlink())
        dev = new / 'dev'
        self.assertTrue(dev.is_dir() and not dev.is_symlink())
        conf = dev / 'odoo.conf'
        self.assertFalse(conf.is_symlink())
        self.assertEqual(conf.read_text(), (
            '[options]\n'
            f'addons_path = /x,{new},{new}/extra,{main}-other/addons,/y\n'
            f'logfile = {main}/dev/logs/odoo.log\n'
            'admin_passwd = fixture-only\n'))
        self.assertEqual(stat.S_IMODE(conf.stat().st_mode), 0o600)
        runtime = dev / 'runtime'
        self.assertTrue(runtime.is_dir() and not runtime.is_symlink())
        self.assertEqual(list(runtime.iterdir()), [])
        self.assertEqual(stat.S_IMODE(runtime.stat().st_mode), 0o700)
        for name in ('compose.yml', 'logs', 'runtime-env'):
            self.assertTrue((dev / name).is_symlink(), name)
            self.assertEqual(os.readlink(dev / name), str(main / 'dev' / name))
        self.assertEqual(sorted(path.name for path in dev.iterdir()),
                         ['compose.yml', 'logs', 'odoo.conf', 'runtime', 'runtime-env'])
        # The main checkout is untouched.
        self.assertEqual((main / 'dev/odoo.conf').read_text(), CONF.format(main=main))
        self.assertEqual((main / 'dev/runtime/odoo.pid').read_text(), '1\n')

    def assert_refused(self, project, args, stderr):
        before = (self.snapshot(), self.branches(self.main), self.worktrees(self.main))
        result = self.invoke(project, *args)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', stderr))
        self.assertEqual((self.snapshot(), self.branches(self.main), self.worktrees(self.main)), before)

    # -- behaviour --------------------------------------------------------------------------

    def test_new_branch_is_created_from_main_head(self):
        main = self.repository()
        head = self.head(main)
        new = self.scratch / 'proj-feat-x'
        result = self.invoke(main, 'Feat X', 'feature/x')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout,
                         self.plan(new, f'feature/x (created from HEAD {head[:12]})', 'feat_x'))
        self.assert_prepared(new)
        self.assertEqual(self.git(new, 'rev-parse', '--abbrev-ref', 'HEAD'), 'feature/x')
        self.assertEqual(self.head(new), head)
        self.assertEqual(self.identity(new), ['CHECKOUT_KIND=linked', 'CHECKOUT_SLUG=feat_x'])

    def test_existing_local_branch_is_checked_out(self):
        main = self.repository()
        self.git(main, 'branch', 'existing')
        new = self.scratch / 'proj-07-1'
        result = self.invoke(main, '07.1', 'existing')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout, self.plan(new, 'existing (existing)', '07_1'))
        self.assert_prepared(new)
        self.assertEqual(self.git(new, 'rev-parse', '--abbrev-ref', 'HEAD'), 'existing')
        self.assertEqual(self.identity(new), ['CHECKOUT_KIND=linked', 'CHECKOUT_SLUG=07_1'])

    def test_remote_branch_is_tracked(self):
        main = self.repository()
        origin = self.scratch / 'origin.git'
        self.git(self.scratch, 'init', '-q', '--bare', str(origin))
        self.git(main, 'remote', 'add', 'origin', str(origin))
        self.git(main, 'branch', 'remote-only')
        self.git(main, 'push', '-q', 'origin', 'remote-only')
        self.git(main, 'branch', '-q', '-D', 'remote-only')
        new = self.scratch / 'proj-remote'
        result = self.invoke(main, 'remote', 'remote-only')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout,
                         self.plan(new, 'remote-only (tracking origin/remote-only)', 'remote'))
        self.assert_prepared(new)
        self.assertEqual(self.git(new, 'rev-parse', '--abbrev-ref', '@{upstream}'), 'origin/remote-only')

    def test_dry_run_prints_the_plan_and_changes_nothing(self):
        main = self.repository()
        head = self.head(main)
        before = (self.snapshot(), self.branches(main), self.worktrees(main))
        result = self.invoke(main, 'feat', 'feature/dry', '--dry-run')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout,
                         self.plan(self.scratch / 'proj-feat', f'feature/dry (created from HEAD {head[:12]})',
                                   'feat') + 'dry run: nothing changed\n')
        self.assertEqual((self.snapshot(), self.branches(main), self.worktrees(main)), before)

    def test_from_a_linked_worktree_the_folder_goes_next_to_the_main_checkout(self):
        main = self.repository()
        first = self.scratch / 'proj-one'
        self.assertEqual(self.invoke(main, 'one', 'one').returncode, 0)
        head = self.head(main)
        new = self.scratch / 'proj-two'
        result = self.invoke(first, 'two', 'two')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout, self.plan(new, f'two (created from HEAD {head[:12]})', 'two'))
        self.assert_prepared(new)

    def test_partly_tracked_dev_links_untracked_and_ignored_entries_and_the_env_file(self):
        profile = PROFILE.replace("env_file = 'dev/runtime-env'", "env_file = 'local/runtime-env'")
        main = self.repository(gitignore='dev/*\n!dev/tracked.txt\n!dev/notes.txt\nlocal/\n',
                               profile=profile)
        (main / 'dev' / 'tracked.txt').write_text('tracked\n')
        self.git(main, 'add', 'dev/tracked.txt', '.gitignore')
        self.git(main, 'commit', '-q', '-m', 'tracked dev file')
        (main / 'dev' / 'notes.txt').write_text('untracked, not ignored\n')
        (main / 'local').mkdir()
        (main / 'local' / 'runtime-env').write_text('FIXTURE=1\n')
        head = self.head(main)
        new = self.scratch / 'proj-part'
        result = self.invoke(main, 'part', 'part')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout, (
            f'worktree: {new}\n'
            f'branch: part (created from HEAD {head[:12]})\n'
            'slug: part\n'
            'copied .odoo19-agent.toml\n'
            f'linked dev/compose.yml -> {main}/dev/compose.yml\n'
            f'linked dev/logs -> {main}/dev/logs\n'
            f'linked dev/notes.txt -> {main}/dev/notes.txt\n'
            'copied dev/odoo.conf\n'
            'rewrote addons_path in dev/odoo.conf\n'
            'removed db_name from dev/odoo.conf\n'
            'created dir dev/runtime\n'
            f'linked dev/runtime-env -> {main}/dev/runtime-env\n'
            'created dir local\n'
            f'linked local/runtime-env -> {main}/local/runtime-env\n'))
        self.assertFalse((new / 'dev' / 'tracked.txt').is_symlink())
        self.assertEqual((new / 'dev' / 'tracked.txt').read_text(), 'tracked\n')
        self.assertEqual(os.readlink(new / 'local' / 'runtime-env'), str(main / 'local' / 'runtime-env'))
        self.assertEqual(os.readlink(new / 'dev' / 'notes.txt'), str(main / 'dev' / 'notes.txt'))

    # -- refusals ---------------------------------------------------------------------------

    def test_existing_folder_is_refused(self):
        main = self.repository()
        (self.scratch / 'proj-taken').mkdir()
        self.assert_refused(main, ('taken', 'taken'),
                            f'ERROR: Worktree folder already exists: {self.scratch / "proj-taken"}\n')

    def test_bad_feature_is_refused(self):
        main = self.repository()
        for feature in ('..', '!!', 'a' * 21, '_'):
            with self.subTest(feature=feature):
                self.assert_refused(main, (feature, 'branch'),
                                    'ERROR: Invalid feature name: it must give 1-20 characters of '
                                    'a-z, 0-9 and _ starting with a letter or digit.\n')

    def test_bad_branch_is_refused(self):
        main = self.repository()
        for branch in ('bad..name', 'with space', '@{-1}', 'end.lock'):
            with self.subTest(branch=branch):
                self.assert_refused(main, ('feat', branch), f'ERROR: Invalid branch name: {branch}\n')

    def test_branch_checked_out_elsewhere_is_refused(self):
        main = self.repository()
        self.assert_refused(main, ('feat', 'main'),
                            f'ERROR: Branch main is already checked out in {main}.\n')

    def test_outside_git_is_refused(self):
        root = self.scratch / 'plain'
        root.mkdir()
        (root / '.odoo19-agent.toml').write_text(PROFILE)
        self.main = root
        before = self.snapshot()
        result = self.invoke(root, 'feat', 'feat')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'ERROR: worktree-init needs a git checkout.\n'))
        self.assertEqual(self.snapshot(), before)

    def test_usage_errors_are_refused(self):
        main = self.repository()
        usage = 'ERROR: Usage: worktree-init <feature> <branch> [--dry-run]\n'
        for args in ((), ('feat',), ('feat', 'branch', 'extra'), ('feat', '-b'), ('feat', 'b', '--force')):
            with self.subTest(args=args):
                self.assert_refused(main, args, usage)

    def test_profile_with_checkout_slug_is_refused(self):
        main = self.repository(profile=PROFILE + "checkout_slug = 'base'\n")
        self.assert_refused(main, ('feat', 'feat'),
                            f'ERROR: {main / ".odoo19-agent.toml"} sets [tooling].checkout_slug, which the '
                            'new worktree would share with this checkout; prepare the worktree by hand.\n')


if __name__ == '__main__':
    unittest.main()
