"""`odoo19 --project <checkout> worktree-init <feature> <branch> [--dry-run] [--resume]` on synthetic repos.

Every repository lives in a fresh system temp directory, below an oasis-workspace.toml in that
directory; git runs with explicit -c identity flags, an empty global configuration and a ceiling
at the scratch directory, so it never reads or writes the user's configuration or a real
project.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'odoo19'
READER = ROOT / 'tools' / 'config.py'
GIT = ['git', '-c', 'user.name=oasis tests', '-c', 'user.email=tests@example.invalid',
       '-c', 'init.defaultBranch=main', '-c', 'commit.gpgsign=false']
WORKSPACE = (ROOT / 'tests' / 'fixture-workspace.toml').read_text().replace("'../../", "'")


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

    def repository(self):
        """Main checkout <scratch>/proj with committed README and .gitignore, below the workspace
        file <scratch>/oasis-workspace.toml."""
        main = self.main
        main.mkdir()
        (main / 'README.md').write_text('fixture\n')
        (main / '.gitignore').write_text('dev/\n')
        self.git(main, 'init', '-q')
        self.git(main, 'add', 'README.md', '.gitignore')
        self.git(main, 'commit', '-q', '-m', 'init')
        (self.scratch / 'oasis-workspace.toml').write_text(WORKSPACE)
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
        return (f'worktree: {new}\n'
                f'branch: {branch_line}\n'
                f'slug: {slug}\n'
                f'workspace: {self.scratch}\n')

    def assert_prepared(self, new):
        """Only git's checkout: nothing copied or linked, the main checkout untouched."""
        self.assertEqual(sorted(path.name for path in new.iterdir()), ['.git', '.gitignore', 'README.md'])
        self.assertEqual(sorted(path.name for path in self.main.iterdir()), ['.git', '.gitignore', 'README.md'])

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

    # -- resume -----------------------------------------------------------------------------

    def test_resume_accepts_the_existing_worktree_and_adds_nothing(self):
        main = self.repository()
        new = self.scratch / 'proj-feat'
        self.git(main, 'worktree', 'add', '-q', '-b', 'feat', str(new))
        (new / 'notes.txt').write_text('edited by hand\n')
        plan = self.plan(new, 'feat (resumed)', 'feat')
        before = (self.snapshot(), self.branches(main), self.worktrees(main))
        result = self.invoke(main, 'feat', 'feat', '--resume', '--dry-run')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, plan + 'dry run: nothing changed\n', ''))
        self.assertEqual((self.snapshot(), self.branches(main), self.worktrees(main)), before)
        result = self.invoke(main, 'feat', '--resume', 'feat')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, plan, ''))
        self.assertEqual((self.snapshot(), self.branches(main), self.worktrees(main)), before)
        self.assertEqual(self.identity(new), ['CHECKOUT_KIND=linked', 'CHECKOUT_SLUG=feat'])

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
        (self.scratch / 'oasis-workspace.toml').write_text(WORKSPACE)
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

    def test_a_main_checkout_without_a_workspace_file_is_refused(self):
        # The linked worktree reads a workspace file of its own that the main checkout does not
        # find: the new worktree would not read it either.
        main = self.repository()
        first = self.scratch / 'proj-one'
        self.assertEqual(self.invoke(main, 'one', 'one').returncode, 0)
        (self.scratch / 'oasis-workspace.toml').unlink()
        (first / 'oasis-workspace.toml').write_text(WORKSPACE.replace("'source/odoo'", "'../source/odoo'"))
        self.assert_refused(first, ('two', 'two'),
                            f'ERROR: The main checkout {main} has no oasis-workspace.toml at or above it; '
                            'prepare the worktree by hand.\n')

    def linked_with_its_own_workspace(self):
        """A linked worktree that reads a workspace file of its own, so only worktree-init reads the
        one above the main checkout (the one the new worktree would read)."""
        main = self.repository()
        first = self.scratch / 'proj-one'
        self.assertEqual(self.invoke(main, 'one', 'one').returncode, 0)
        (first / 'oasis-workspace.toml').write_text(WORKSPACE.replace("'source/odoo'", "'../source/odoo'"))
        return first

    def test_an_invalid_or_unreadable_workspace_of_the_main_checkout_is_refused(self):
        first = self.linked_with_its_own_workspace()
        workspace = self.scratch / 'oasis-workspace.toml'
        workspace.write_text('workspace_version = \n')
        self.assert_refused(first, ('two', 'two'), f'ERROR: Invalid TOML in {workspace}.\n')
        workspace.write_text(WORKSPACE)
        workspace.chmod(0o666)
        self.assert_refused(first, ('two', 'two'),
                            f'ERROR: Refusing untrusted workspace file {workspace}: '
                            f'{workspace} is writable by group or others.\n')
        if os.geteuid() != 0:  # root reads a 000 file
            workspace.chmod(0o000)
            try:
                self.assert_refused(first, ('two', 'two'), f'ERROR: Invalid TOML in {workspace}.\n')
            finally:
                workspace.chmod(0o644)

    @unittest.skipIf(os.geteuid() == 0, 'root reads every directory')
    def test_an_unreadable_parent_of_the_main_checkout_workspace_gives_one_error_line(self):
        # The workspace file above the main checkout links into a directory nobody may search.
        first = self.linked_with_its_own_workspace()
        locked = self.scratch / 'locked'
        locked.mkdir()
        (locked / 'oasis-workspace.toml').write_text(WORKSPACE)
        workspace = self.scratch / 'oasis-workspace.toml'
        workspace.unlink()
        workspace.symlink_to(locked / 'oasis-workspace.toml')
        locked.chmod(0o000)
        self.addCleanup(locked.chmod, 0o700)
        before = (self.snapshot(), self.branches(self.main), self.worktrees(self.main))
        result = self.invoke(first, 'two', 'two')
        self.assertEqual((result.returncode, result.stdout), (2, ''), result.stderr)
        self.assertRegex(result.stderr, r'\AERROR: [^\n]+\n\Z')
        self.assertEqual((self.snapshot(), self.branches(self.main), self.worktrees(self.main)), before)


if __name__ == '__main__':
    unittest.main()
