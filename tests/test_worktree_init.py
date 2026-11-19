"""`odoo19 --project <checkout> worktree-init <feature> <branch> [--dry-run] [--resume]` on synthetic repos.

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
SHARED_PROFILE = (PROFILE
                  .replace("config = 'dev/odoo.conf'", "config = '../config/odoo.conf'")
                  .replace("env_file = 'dev/runtime-env'", "env_file = '../config/runtime-env'")
                  .replace("compose = 'dev/compose.yml'", "compose = '../config/compose.yml'")
                  .replace("requirements = 'dev/requirements'", "requirements = '../config/requirements'"))
SHARED_KEYS = ('ODOO_CONFIG=', 'ENV_FILE=', 'COMPOSE_FILE=', 'REQUIREMENTS_DIR=')
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

    def shared_paths(self, root):
        result = subprocess.run([sys.executable, '-B', str(READER), str(root)],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        return [line for line in result.stdout.splitlines() if line.startswith(SHARED_KEYS)]

    def shared_repository(self, profile=SHARED_PROFILE):
        """Main checkout whose profile points at <scratch>/config, outside every checkout."""
        config = self.scratch / 'config'
        (config / 'requirements').mkdir(parents=True)
        (config / 'odoo.conf').write_text(CONF.format(main=self.main))
        (config / 'runtime-env').write_text('FIXTURE=1\n')
        (config / 'compose.yml').write_text('services: {}\n')
        return self.repository(profile=profile)

    def assert_shared(self, new):
        self.assertEqual(sorted(path.name for path in new.iterdir()),
                         ['.git', '.gitignore', '.odoo19-agent.toml', 'README.md'])
        self.assertFalse((new / '.odoo19-agent.toml').is_symlink())
        self.assertEqual((new / '.odoo19-agent.toml').read_text(), SHARED_PROFILE)
        self.assertEqual(self.shared_paths(new), self.shared_paths(self.main))
        self.assertEqual((self.scratch / 'config/odoo.conf').read_text(), CONF.format(main=self.main))

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

    def test_shared_layout_copies_only_the_profile(self):
        main = self.shared_repository()
        head = self.head(main)
        new = self.scratch / 'proj-shared'
        expected = (f'worktree: {new}\n'
                    f'branch: feature/shared (created from HEAD {head[:12]})\n'
                    'slug: shared\n'
                    f'shared config: {self.scratch / "config"}\n'
                    'copied .odoo19-agent.toml\n')
        before = (self.snapshot(), self.branches(main), self.worktrees(main))
        result = self.invoke(main, 'shared', 'feature/shared', '--dry-run')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, expected + 'dry run: nothing changed\n', ''))
        self.assertEqual((self.snapshot(), self.branches(main), self.worktrees(main)), before)
        result = self.invoke(main, 'shared', 'feature/shared')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, ''))
        self.assert_shared(new)
        self.assertEqual(self.identity(new), ['CHECKOUT_KIND=linked', 'CHECKOUT_SLUG=shared'])

    def test_shared_layout_from_a_linked_worktree(self):
        main = self.shared_repository()
        self.assertEqual(self.invoke(main, 'one', 'one').returncode, 0)
        head = self.head(main)
        new = self.scratch / 'proj-two'
        result = self.invoke(self.scratch / 'proj-one', 'two', 'two')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout, (f'worktree: {new}\n'
                                         f'branch: two (created from HEAD {head[:12]})\n'
                                         'slug: two\n'
                                         f'shared config: {self.scratch / "config"}\n'
                                         'copied .odoo19-agent.toml\n'))
        self.assert_shared(new)

    def test_partly_shared_profile_keeps_the_legacy_layout(self):
        profile = PROFILE.replace("config = 'dev/odoo.conf'", "config = '../config/odoo.conf'")
        (self.scratch / 'config').mkdir()
        (self.scratch / 'config/odoo.conf').write_text(CONF.format(main=self.main))
        main = self.repository(profile=profile)
        head = self.head(main)
        new = self.scratch / 'proj-part'
        result = self.invoke(main, 'part', 'part')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout, self.plan(new, f'part (created from HEAD {head[:12]})', 'part'))

    def logs_dir(self, root):
        result = subprocess.run([sys.executable, '-B', str(READER), str(root)],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        return [line for line in result.stdout.splitlines() if line.startswith('LOGS_DIR=')]

    def test_shared_layout_keeps_a_shared_logs_key(self):
        profile = SHARED_PROFILE + "logs = '../logs'\n"
        main = self.shared_repository(profile)
        head = self.head(main)
        new = self.scratch / 'proj-logs'
        result = self.invoke(main, 'logs', 'feature/logs')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout, (f'worktree: {new}\n'
                                         f'branch: feature/logs (created from HEAD {head[:12]})\n'
                                         'slug: logs\n'
                                         f'shared config: {self.scratch / "config"}\n'
                                         'copied .odoo19-agent.toml\n'))
        self.assertEqual((new / '.odoo19-agent.toml').read_text(), profile)
        self.assertEqual(self.logs_dir(new), ["LOGS_DIR=" + str(self.scratch / 'logs')])
        self.assertEqual(self.logs_dir(new), self.logs_dir(main))
        self.assertFalse((new / 'dev').exists())

    def test_shared_layout_refuses_a_logs_key_that_would_move(self):
        profile = SHARED_PROFILE + "logs = 'own-logs'\n"
        main = self.shared_repository(profile)
        new = self.scratch / 'proj-logs'
        self.assert_refused(main, ('logs', 'feature/logs'),
                            f'ERROR: The copied profile would resolve logs to {new}/own-logs instead of '
                            f'{main}/own-logs; prepare the worktree by hand.\n')

    def test_shared_layout_refuses_a_path_that_resolves_differently_from_the_new_folder(self):
        # The main checkout reaches the shared config through an untracked symlink of its own:
        # from the new folder (no such link) the same relative path names another file.
        elsewhere = self.scratch / 'elsewhere' / 'deep' / 'dir'
        elsewhere.mkdir(parents=True)
        config = self.scratch / 'elsewhere' / 'config'
        config.mkdir()
        (config / 'odoo.conf').write_text(CONF.format(main=self.main))
        profile = SHARED_PROFILE.replace("config = '../config/odoo.conf'", "config = 'link/../../config/odoo.conf'")
        main = self.shared_repository(profile)
        (main / 'link').symlink_to(elsewhere, target_is_directory=True)
        new = self.scratch / 'proj-moved'
        self.assert_refused(main, ('moved', 'moved'),
                            f'ERROR: The copied profile would resolve config to {self.scratch}/config/odoo.conf '
                            f'instead of {config}/odoo.conf; prepare the worktree by hand.\n')
        self.assertFalse(new.exists())

    def test_shared_layout_refuses_a_main_profile_without_a_shared_key(self):
        main = self.shared_repository()
        self.assertEqual(self.invoke(main, 'one', 'one').returncode, 0)
        for key in ('config', 'env_file', 'compose', 'requirements'):
            with self.subTest(key=key):
                (main / '.odoo19-agent.toml').write_text(
                    ''.join(line for line in SHARED_PROFILE.splitlines(keepends=True)
                            if not line.startswith(f'{key} = ')))
                self.assert_refused(self.scratch / 'proj-one', ('two', 'two'),
                                    f'ERROR: {main / ".odoo19-agent.toml"} does not set [tooling].{key}; '
                                    'prepare the worktree by hand.\n')
        (main / '.odoo19-agent.toml').write_text('[tooling\n')
        self.assert_refused(self.scratch / 'proj-one', ('two', 'two'),
                            f'ERROR: Invalid tooling configuration: {main / ".odoo19-agent.toml"}\n')

    # -- resume -----------------------------------------------------------------------------

    def test_resume_completes_missing_items_and_keeps_existing_ones(self):
        main = self.repository()
        new = self.scratch / 'proj-feat'
        self.git(main, 'worktree', 'add', '-q', '-b', 'feat', str(new))
        (new / '.odoo19-agent.toml').write_text(PROFILE + '# edited by hand\n')
        plan = self.plan(new, 'feat (resumed)', 'feat').replace(
            'copied .odoo19-agent.toml\n', 'kept existing .odoo19-agent.toml\n')
        before = (self.snapshot(), self.branches(main), self.worktrees(main))
        result = self.invoke(main, 'feat', 'feat', '--resume', '--dry-run')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, plan + 'dry run: nothing changed\n', ''))
        self.assertEqual((self.snapshot(), self.branches(main), self.worktrees(main)), before)
        result = self.invoke(main, 'feat', '--resume', 'feat')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, plan, ''))
        self.assertEqual((new / '.odoo19-agent.toml').read_text(), PROFILE + '# edited by hand\n')
        (new / '.odoo19-agent.toml').write_text(PROFILE)
        self.assert_prepared(new)
        self.assertEqual((self.branches(main), self.worktrees(main)), before[1:])
        result = self.invoke(main, 'feat', 'feat', '--resume')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout.splitlines()[3:],
                         ['kept existing .odoo19-agent.toml', 'kept existing dev',
                          'kept existing dev/compose.yml', 'kept existing dev/logs',
                          'kept existing dev/odoo.conf', 'kept existing dev/runtime',
                          'kept existing dev/runtime-env'])
        self.assert_prepared(new)

    def test_resume_without_a_folder_creates_the_worktree(self):
        main = self.repository()
        head = self.head(main)
        new = self.scratch / 'proj-feat'
        result = self.invoke(main, 'feat', 'feat', '--resume')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.plan(new, f'feat (created from HEAD {head[:12]})', 'feat'), ''))
        self.assert_prepared(new)

    def test_resume_refuses_a_folder_that_is_not_a_worktree_of_this_repository(self):
        main = self.repository()
        new = self.scratch / 'proj-feat'
        new.mkdir()
        self.assert_refused(main, ('feat', 'feat', '--resume'),
                            f'ERROR: {new} is not a worktree of this repository.\n')
        other = self.scratch / 'other'
        other.mkdir()
        self.git(other, 'init', '-q')
        self.git(other, 'commit', '-q', '--allow-empty', '-m', 'other')
        self.git(other, 'worktree', 'add', '-q', '-b', 'side', str(self.scratch / 'proj-side'))
        self.assert_refused(main, ('side', 'side', '--resume'),
                            f'ERROR: {self.scratch / "proj-side"} is not a worktree of this repository.\n')
        link = self.scratch / 'proj-link'
        self.git(main, 'worktree', 'add', '-q', '-b', 'real', str(self.scratch / 'proj-real'))
        link.symlink_to(self.scratch / 'proj-real', target_is_directory=True)
        self.assert_refused(main, ('link', 'real', '--resume'),
                            f'ERROR: {link} is not a worktree of this repository.\n')

    def test_resume_refuses_a_worktree_on_another_branch(self):
        main = self.repository()
        new = self.scratch / 'proj-feat'
        self.git(main, 'worktree', 'add', '-q', '-b', 'other', str(new))
        self.assert_refused(main, ('feat', 'feat', '--resume'),
                            f'ERROR: Worktree {new} is not on branch feat.\n')

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
        usage = 'ERROR: Usage: worktree-init <feature> <branch> [--dry-run] [--resume]\n'
        for args in ((), ('feat',), ('feat', 'branch', 'extra'), ('feat', '-b'), ('feat', 'b', '--force'),
                     ('feat', 'b', '--resume', '--resume'), ('feat', 'b', '--dry-run', '--dry-run')):
            with self.subTest(args=args):
                self.assert_refused(main, args, usage)

    def test_profile_with_checkout_slug_is_refused(self):
        main = self.repository(profile=PROFILE + "checkout_slug = 'base'\n")
        self.assert_refused(main, ('feat', 'feat'),
                            f'ERROR: {main / ".odoo19-agent.toml"} sets [tooling].checkout_slug, which the '
                            'new worktree would share with this checkout; prepare the worktree by hand.\n')


if __name__ == '__main__':
    unittest.main()
