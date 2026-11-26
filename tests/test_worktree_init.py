"""`oasis --project <checkout> worktree-init <feature> <branch> [--dry-run] [--resume]` on synthetic repos.

Every repository lives in a fresh system temp directory, below an oasis-workspace.toml in that
directory; git runs with explicit -c identity flags, an empty global configuration and a ceiling
at the scratch directory, so it never reads or writes the user's configuration or a real
project.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'oasis'
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

    def create(self, project, *args):
        """worktree-init confirmed as v0.16.0 S1 requires: --confirm <the worktree path its dry run names>."""
        plan = self.invoke(project, *args, '--dry-run')
        lines = [line for line in plan.stdout.splitlines() if line.startswith('worktree: ')]
        self.assertEqual((plan.returncode, len(lines)), (0, 1), plan.stderr)
        return self.invoke(project, *args, '--confirm', lines[0][len('worktree: '):])

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
        result = self.create(main, 'Feat X', 'feature/x')
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
        result = self.create(main, '07.1', 'existing')
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
        result = self.create(main, 'remote', 'remote-only')
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
        self.assertEqual(self.create(main, 'one', 'one').returncode, 0)
        head = self.head(main)
        new = self.scratch / 'proj-two'
        result = self.create(first, 'two', 'two')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout, self.plan(new, f'two (created from HEAD {head[:12]})', 'two'))
        self.assert_prepared(new)

    # -- --path (v0.14.0 S4) ----------------------------------------------------------------

    def elsewhere(self):
        """A directory outside the workspace directory: no oasis-workspace.toml at or above it."""
        other = Path(tempfile.mkdtemp(prefix='oasis-worktree-elsewhere-')).resolve()
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        self.env['GIT_CEILING_DIRECTORIES'] += os.pathsep + str(other)
        return other

    def workspace_root(self, root):
        result = subprocess.run([sys.executable, '-B', str(READER), str(root)],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        return [line for line in result.stdout.splitlines() if line.startswith('WORKSPACE_ROOT=')]

    def test_path_creates_the_worktree_anywhere_reading_the_main_checkouts_workspace(self):
        main = self.repository()
        head = self.head(main)
        other = self.elsewhere()
        new = other / 'deep' / 'proj-feat'
        plan = self.plan(new, f'feature/f (created from HEAD {head[:12]})', 'feat')
        for args in (('feat', 'feature/f', '--path', str(new), '--dry-run'),
                     ('feat', 'feature/f', '--dry-run', f'--path={new}')):
            with self.subTest(args=args):
                before = (self.snapshot(), self.branches(main), self.worktrees(main))
                result = self.invoke(main, *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (0, plan + 'dry run: nothing changed\n', ''))
                self.assertEqual((self.snapshot(), self.branches(main), self.worktrees(main)), before)
                self.assertFalse(os.path.lexists(other / 'deep'))
        result = self.create(main, 'feat', 'feature/f', '--path', f'{other}/deep/../deep/proj-feat')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, plan, ''))
        self.assert_prepared(new)
        self.assertEqual(self.git(new, 'rev-parse', '--abbrev-ref', 'HEAD'), 'feature/f')
        self.assertEqual(self.identity(new), ['CHECKOUT_KIND=linked', 'CHECKOUT_SLUG=feat'])
        self.assertEqual(self.workspace_root(new), [f'WORKSPACE_ROOT={self.scratch}'])
        # From that worktree, the default folder still goes next to the main checkout.
        result = self.create(new, 'two', 'two')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.plan(self.scratch / 'proj-two', f'two (created from HEAD {head[:12]})', 'two'), ''))

    def test_path_accepts_an_empty_directory_and_resumes_a_worktree(self):
        main = self.repository()
        head = self.head(main)
        other = self.elsewhere()
        empty = other / 'feat'
        empty.mkdir()
        result = self.create(main, 'feat', 'feat', '--path', str(empty))
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.plan(empty, f'feat (created from HEAD {head[:12]})', 'feat'), ''))
        self.assert_prepared(empty)
        before = (self.snapshot(), self.branches(main), self.worktrees(main))
        result = self.invoke(main, 'feat', 'feat', '--path', str(empty), '--resume')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.plan(empty, 'feat (resumed)', 'feat'), ''))
        self.assertEqual((self.snapshot(), self.branches(main), self.worktrees(main)), before)

    def test_path_refuses_the_odoo_source_a_checkout_and_a_used_directory(self):
        main = self.repository()
        source = self.scratch / 'source' / 'odoo'
        source.mkdir(parents=True)
        self.assertEqual(self.create(main, 'one', 'one').returncode, 0)
        another = self.scratch / 'another'
        another.mkdir()
        self.git(another, 'init', '-q')
        other = self.elsewhere()
        used, afile, link = (other / name / 'proj-x' for name in ('used', 'file', 'link'))
        for folder in (used, afile, link):
            folder.parent.mkdir()
        used.mkdir()
        (used / 'notes.txt').write_text('kept\n')
        afile.write_text('kept\n')
        link.symlink_to(other / 'missing')
        cases = (
            ('rel/proj-x', 'ERROR: --path requires an absolute path.\n'),
            (str(source / 'proj-x'), f'ERROR: The new worktree {source / "proj-x"} would be inside the Odoo '
                                     f'source {source}.\n'),
            (str(main / 'sub' / 'proj-x'), f'ERROR: The new worktree {main / "sub" / "proj-x"} would be inside '
                                           f'the checkout {main}.\n'),
            (str(self.scratch / 'proj-one' / 'proj-x'),
             f'ERROR: The new worktree {self.scratch / "proj-one" / "proj-x"} would be inside the checkout '
             f'{self.scratch / "proj-one"}.\n'),
            (str(another / 'proj-x'), f'ERROR: The new worktree {another / "proj-x"} would be inside the checkout '
                                      f'{another}.\n'),
            (str(used), f'ERROR: Worktree folder already exists and is not empty: {used}\n'),
            (str(afile), f'ERROR: Worktree folder already exists and is not empty: {afile}\n'),
            (str(link), f'ERROR: Worktree folder already exists and is not empty: {link}\n'),
            # The slug still comes from the folder name.
            (str(other / 'unrelated'), 'ERROR: Folder unrelated would not give the checkout slug x.\n'),
        )
        for path, stderr in cases:
            with self.subTest(path=path):
                feature = 'x'
                self.assert_refused(main, (feature, 'feat-x', '--path', path), stderr)
                if path != str(afile):
                    self.assertFalse(os.path.lexists(Path(path) / '.git'))
        self.assertEqual(sorted(str(path.relative_to(other)) for path in other.rglob('*')),
                         ['file', 'file/proj-x', 'link', 'link/proj-x', 'used', 'used/proj-x', 'used/proj-x/notes.txt'])

    def test_path_refuses_a_folder_that_would_read_another_workspace_file(self):
        main = self.repository()
        other = self.elsewhere()
        nearer = other / 'oasis-workspace.toml'
        nearer.write_text(WORKSPACE)
        new = other / 'proj-x'
        self.assert_refused(main, ('x', 'x', '--path', str(new)),
                            f'ERROR: The new worktree {new} would read {nearer}, not the main checkout\'s '
                            f'{self.scratch / "oasis-workspace.toml"}; choose another --path.\n')
        self.assertFalse(os.path.lexists(new))

    def inside_workspace(self, main):
        """Move the workspace file into the main checkout (its source path from there)."""
        (self.scratch / 'oasis-workspace.toml').unlink()
        workspace = main / 'oasis-workspace.toml'
        workspace.write_text(WORKSPACE.replace("'source/odoo'", "'../source/odoo'"))
        return workspace

    def test_a_workspace_file_tracked_by_the_main_checkout_is_refused(self):
        # Each worktree would check out its own committed copy and read it, not the main one.
        main = self.repository()
        workspace = self.inside_workspace(main)
        self.git(main, 'add', 'oasis-workspace.toml')
        self.git(main, 'commit', '-q', '-m', 'track the workspace file')
        other = self.elsewhere()
        stderr = (f'ERROR: {workspace} is tracked by git in the main checkout {main}: each worktree would '
                  'read its own committed copy, not this file. Untrack it (git rm --cached '
                  'oasis-workspace.toml) or keep the workspace file above the checkouts.\n')
        for args in (('feat', 'feat'), ('feat', 'feat', '--dry-run'),
                     ('feat', 'feat', '--path', str(other / 'proj-feat'))):
            with self.subTest(args=args):
                self.assert_refused(main, args, stderr)
        self.assertFalse(os.path.lexists(self.scratch / 'proj-feat'))
        self.assertFalse(os.path.lexists(other / 'proj-feat'))

    def test_an_untracked_workspace_file_in_the_main_checkout_is_read_through_git(self):
        main = self.repository()
        self.inside_workspace(main)
        head = self.head(main)
        new = self.scratch / 'proj-feat'
        result = self.create(main, 'feat', 'feat')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'worktree: {new}\nbranch: feat (created from HEAD {head[:12]})\nslug: feat\n'
                             f'workspace: {main}\n', ''))
        self.assertEqual(self.workspace_root(new), [f'WORKSPACE_ROOT={main}'])

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

    def test_resume_refuses_an_explicit_wrong_confirmation(self):
        main = self.repository()
        new = self.scratch / 'proj-feat'
        self.git(main, 'worktree', 'add', '-q', '-b', 'feat', str(new))
        before = (self.snapshot(), self.branches(main), self.worktrees(main))
        result = self.invoke(main, 'feat', 'feat', '--resume', '--confirm', '/wrong')
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.assertIn(f'--confirm /wrong does not name the worktree {new}; nothing changed.', result.stderr)
        self.assertEqual((self.snapshot(), self.branches(main), self.worktrees(main)), before)
        result = self.invoke(main, 'feat', 'feat', '--resume', '--confirm', str(new))
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.plan(new, 'feat (resumed)', 'feat'), ''))

    def test_resume_without_a_folder_creates_the_worktree(self):
        main = self.repository()
        head = self.head(main)
        new = self.scratch / 'proj-feat'
        result = self.create(main, 'feat', 'feat', '--resume')
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

    # -- confirmation (v0.16.0 S1: Tier B) --------------------------------------------------

    def test_without_confirm_it_refuses_naming_the_exact_command(self):
        main = self.repository()
        new = self.scratch / 'proj-feat-x'
        command = f'oasis --project {main} worktree-init \'Feat X\' feature/x --confirm {new}'
        self.assert_refused(main, ('Feat X', 'feature/x'),
                            f'ERROR: worktree-init adds the git worktree {new} and its branch feature/x '
                            f'(Tier B: it needs explicit confirmation); nothing changed. Run: {command}\n')
        self.assert_refused(main, ('Feat X', 'feature/x', '--confirm', str(self.scratch / 'proj-other')),
                            f'ERROR: --confirm {self.scratch / "proj-other"} does not name the worktree {new}; '
                            f'nothing changed. Run: {command}\n')
        other = self.elsewhere()
        target = other / 'proj-feat'
        self.assert_refused(main, ('feat', 'feat', f'--path={target}', '--confirm=relative'),
                            f'ERROR: --confirm relative does not name the worktree {target}; nothing changed. '
                            f'Run: oasis --project {main} worktree-init feat feat --path={target} --confirm {target}\n')
        result = self.invoke(main, 'Feat X', 'feature/x', f'--confirm={new}')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assert_prepared(new)

    def test_resuming_an_existing_worktree_adds_nothing_and_needs_no_confirmation(self):
        main = self.repository()
        new = self.scratch / 'proj-feat'
        self.git(main, 'worktree', 'add', '-q', '-b', 'feat', str(new))
        result = self.invoke(main, 'feat', 'feat', '--resume')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.plan(new, 'feat (resumed)', 'feat'), ''))

    def test_a_prunable_worktree_entry_holding_the_branch_names_git_worktree_prune(self):
        # v0.16.0 S4.9: the folder of a worktree was removed by hand; git still lists its entry.
        main = self.repository()
        gone = self.scratch / 'proj-gone'
        self.git(main, 'worktree', 'add', '-q', '-b', 'feat', str(gone))
        shutil.rmtree(gone)
        self.assert_refused(main, ('feat', 'feat'),
                            f'ERROR: Branch feat is held by the prunable worktree entry {gone} (its folder is '
                            f'gone); run git -C {main} worktree prune, then run worktree-init again.\n')

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
        usage = ('ERROR: Usage: worktree-init <feature> <branch> [--path <dir>] [--dry-run] [--resume] '
                 '[--confirm <worktree path>]\n')
        for args in ((), ('feat',), ('feat', 'branch', 'extra'), ('feat', '-b'), ('feat', 'b', '--force'),
                     ('feat', 'b', '--resume', '--resume'), ('feat', 'b', '--dry-run', '--dry-run'),
                     ('feat', 'b', '--path'), ('feat', 'b', '--path='), ('feat', 'b', '--path', '--dry-run'),
                     ('feat', 'b', '--path', '/a/proj-feat', '--path', '/b/proj-feat'),
                     ('feat', 'b', '--path=/a/proj-feat', '--path', '/b/proj-feat'),
                     ('feat', 'b', '--confirm'), ('feat', 'b', '--confirm='),
                     ('feat', 'b', '--confirm', '/a', '--confirm', '/a')):
            with self.subTest(args=args):
                self.assert_refused(main, args, usage)

    def test_a_main_checkout_without_a_workspace_file_is_refused(self):
        # The linked worktree reads a workspace file of its own that the main checkout does not
        # find: the new worktree would not read it either.
        main = self.repository()
        first = self.scratch / 'proj-one'
        self.assertEqual(self.create(main, 'one', 'one').returncode, 0)
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
        self.assertEqual(self.create(main, 'one', 'one').returncode, 0)
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
