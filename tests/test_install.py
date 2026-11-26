import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / 'install.sh'
REPO_ONLY = {'AGENTS.md', '.gitignore', 'install.sh'}


def committed_files():
    output = subprocess.run(['git', '-C', str(ROOT), 'ls-tree', '-r', '--name-only', 'HEAD'], check=True,
                            capture_output=True, text=True).stdout
    return {line for line in output.splitlines() if line}


def head_version():
    package = subprocess.run(['git', '-C', str(ROOT), 'show', 'HEAD:package.json'],
                             capture_output=True, text=True, check=True).stdout
    return json.loads(package)['version']


def head_commit():
    return subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], check=True,
                          capture_output=True, text=True).stdout.strip()


@unittest.skipUnless((ROOT / '.git').exists() and INSTALL.is_file(),
                     'install.sh runs only from the source repository')
class InstallTest(unittest.TestCase):

    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix='oasis-install-'))
        self.target = self.scratch / 'skills' / 'oasis'
        self.target.parent.mkdir()
        self.state = self.scratch / 'state'
        self.env = dict(os.environ, OASIS_STATE_DIR=str(self.state))

    def tearDown(self):
        subprocess.run(['rm', '-rf', str(self.scratch)], check=True)

    def run_install(self, *args):
        return subprocess.run(['bash', str(INSTALL), *args], capture_output=True, text=True,
                              env=self.env, cwd=self.scratch)

    def installed_files(self):
        return {str(path.relative_to(self.target)) for path in self.target.rglob('*')
                if path.is_file()}

    def test_installs_committed_bundle_without_repo_only_files(self):
        result = self.run_install('--target', str(self.target))
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = {path for path in committed_files() if path not in REPO_ONLY}
        self.assertEqual(self.installed_files() - {'.oasis-install.json'}, expected)
        self.assertTrue(os.access(self.target / 'oasis', os.X_OK))
        self.assertTrue(os.access(self.target / 'tools' / 'test-module', os.X_OK))
        record = json.loads((self.target / '.oasis-install.json').read_text())
        self.assertEqual(record['commit'], head_commit())
        version = head_version()
        self.assertEqual(record['version'], version)
        self.assertEqual(result.stdout, f'oasis {version} ({head_commit()[:12]}) installed in {self.target}\n')

    def test_replaces_previous_install_and_keeps_backup_outside_target(self):
        self.target.mkdir()
        (self.target / 'stale.txt').write_text('old')
        result = self.run_install('--target', str(self.target))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.target / 'stale.txt').exists())
        backups = list((self.state / 'backups').iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'stale.txt').read_text(), 'old')
        self.assertNotIn(self.target, backups[0].parents)
        self.assertEqual([p.name for p in self.target.parent.iterdir()], ['oasis'])

    def test_refuses_package_without_semver_version_and_keeps_target(self):
        repo = self.scratch / 'repo'
        repo.mkdir()
        (repo / 'install.sh').write_bytes(INSTALL.read_bytes())
        (repo / 'install.sh').chmod(0o755)
        (repo / 'package.json').write_text('{"version": "first"}\n')
        git = ['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid']
        subprocess.run([*git, 'init', '-q'], check=True)
        subprocess.run([*git, 'add', '.'], check=True)
        subprocess.run([*git, 'commit', '-qm', 'fixture'], check=True)
        self.target.mkdir()
        (self.target / 'keep.txt').write_text('old')
        result = subprocess.run([str(repo / 'install.sh'), '--target', str(self.target)],
                                capture_output=True, text=True, env=self.env, cwd=self.scratch)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('package.json has no valid SemVer version', result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual((self.target / 'keep.txt').read_text(), 'old')

    def test_installs_the_one_entry_point_executable(self):
        # A fixture repository committing the working-tree entry point: `oasis` alone (v0.17.0 S3).
        repo = self.scratch / 'repo'
        repo.mkdir()
        for name in ('install.sh', 'package.json', 'oasis'):
            (repo / name).write_bytes((ROOT / name).read_bytes())
            (repo / name).chmod(0o755 if name != 'package.json' else 0o644)
        self.commit_fixture(repo)
        result = subprocess.run([str(repo / 'install.sh'), '--target', str(self.target)],
                                capture_output=True, text=True, env=self.env, cwd=self.scratch)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.access(self.target / 'oasis', os.X_OK))
        shown = subprocess.run([str(self.target / 'oasis'), '--help'], capture_output=True, text=True,
                               env=dict(self.env, PYTHONDONTWRITEBYTECODE='1'), cwd=self.scratch)
        self.assertEqual((shown.returncode, shown.stderr), (0, ''))
        self.assertTrue(shown.stdout.startswith('usage: oasis '), shown.stdout)
        self.assertEqual(sorted(p.name for p in self.target.iterdir()),
                         ['.oasis-install.json', 'oasis', 'package.json'])

    def test_the_repository_has_no_odoo19_entry_point(self):
        self.assertFalse((ROOT / 'odoo19').exists())

    def commit_fixture(self, repo):
        git = ['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid']
        subprocess.run([*git, 'init', '-q'], check=True)
        subprocess.run([*git, 'add', '.'], check=True)
        subprocess.run([*git, 'commit', '-qm', 'fixture'], check=True)

    def fixture_repo(self):
        """A committed fixture repository with this install.sh and a valid package.json."""
        repo = self.scratch / 'repo'
        repo.mkdir()
        (repo / 'install.sh').write_bytes(INSTALL.read_bytes())
        (repo / 'install.sh').chmod(0o755)
        (repo / 'package.json').write_text('{"version": "1.2.3"}\n')
        self.commit_fixture(repo)
        return repo

    def install_home(self, repo, *args):
        """install.sh of repo with HOME at a scratch home that has ~/.agents/skills."""
        home = self.scratch / 'home'
        (home / '.agents/skills').mkdir(parents=True, exist_ok=True)
        result = subprocess.run([str(repo / 'install.sh'), *args], capture_output=True, text=True,
                                env=dict(self.env, HOME=str(home)), cwd=self.scratch)
        return home / '.agents/skills', result

    def test_the_default_target_is_the_oasis_skill_directory(self):
        repo = self.fixture_repo()
        skills, result = self.install_home(repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        commit = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'], check=True, capture_output=True,
                                text=True).stdout.strip()
        self.assertEqual((result.stdout, result.stderr),
                         (f'oasis 1.2.3 ({commit[:12]}) installed in {skills / "oasis"}\n', ''))
        self.assertEqual(sorted(p.name for p in skills.iterdir()), ['oasis'])
        self.assertEqual(json.loads((skills / 'oasis/.oasis-install.json').read_text())['version'], '1.2.3')
        usage = subprocess.run([str(repo / 'install.sh'), '--help'], capture_output=True, text=True, env=self.env)
        self.assertEqual((usage.returncode, usage.stdout, usage.stderr),
                         (0, '', 'usage: install.sh [--target /absolute/path]\n'
                                 'default target: $HOME/.agents/skills/oasis\n'))

    def test_the_default_install_moves_a_previous_odoo19_install_to_the_backups(self):
        repo = self.fixture_repo()
        home = self.scratch / 'home'
        old = home / '.agents/skills/odoo19'
        (old / 'odoo19-backend').mkdir(parents=True)
        (old / '.oasis-install.json').write_text('{"version": "0.16.0"}\n')
        (old / 'odoo19-backend/SKILL.md').write_text('old skill\n')
        skills, result = self.install_home(repo)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(sorted(p.name for p in skills.iterdir()), ['oasis'])
        [backup] = list((self.state / 'backups').iterdir())
        self.assertRegex(backup.name, r'^odoo19-\d{8}T\d{6}Z$')
        self.assertEqual((backup / 'odoo19-backend/SKILL.md').read_text(), 'old skill\n')
        self.assertTrue(result.stdout.endswith(f'previous odoo19 install removed from {old}; kept in {backup}\n'),
                        result.stdout)
        self.assertEqual(len(result.stdout.splitlines()), 2, result.stdout)

    def test_a_previous_odoo19_install_and_a_previous_oasis_install_are_both_kept_as_backups(self):
        repo = self.fixture_repo()
        home = self.scratch / 'home'
        for name in ('odoo19', 'oasis'):
            (home / '.agents/skills' / name).mkdir(parents=True)
            (home / '.agents/skills' / name / '.oasis-install.json').write_text('{}\n')
            (home / '.agents/skills' / name / 'mark').write_text(name)
        skills, result = self.install_home(repo)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(sorted(p.name for p in skills.iterdir()), ['oasis'])
        marks = sorted((backup / 'mark').read_text() for backup in (self.state / 'backups').iterdir())
        self.assertEqual(marks, ['oasis', 'odoo19'])

    def test_a_directory_named_odoo19_that_is_not_an_oasis_install_is_never_removed(self):
        repo = self.fixture_repo()
        home = self.scratch / 'home'
        foreign = home / '.agents/skills/odoo19'
        foreign.mkdir(parents=True)
        (foreign / 'SKILL.md').write_text('someone else\n')
        link = self.scratch / 'linked'
        link.mkdir()
        (link / '.oasis-install.json').write_text('{}\n')
        for case in ('directory', 'symlink', 'file'):
            with self.subTest(case=case):
                if case == 'symlink':
                    subprocess.run(['rm', '-rf', str(foreign)], check=True)
                    foreign.symlink_to(link, target_is_directory=True)
                elif case == 'file':
                    foreign.unlink()
                    foreign.write_text('a file\n')
                skills, result = self.install_home(repo)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, f'install.sh: warning: {foreign} is not an oasis install '
                                                '(no .oasis-install.json); not removed\n')
                self.assertEqual(len(result.stdout.splitlines()), 1 if case == 'directory' else 2, result.stdout)
                self.assertEqual(sorted(p.name for p in skills.iterdir()), ['oasis', 'odoo19'])
                if case == 'directory':
                    self.assertEqual((foreign / 'SKILL.md').read_text(), 'someone else\n')
                elif case == 'symlink':
                    self.assertTrue(foreign.is_symlink())
                    self.assertTrue((link / '.oasis-install.json').is_file())
                else:
                    self.assertEqual(foreign.read_text(), 'a file\n')

    def test_an_explicit_target_never_touches_the_odoo19_directory(self):
        repo = self.fixture_repo()
        home = self.scratch / 'home'
        old = home / '.agents/skills/odoo19'
        old.mkdir(parents=True)
        (old / '.oasis-install.json').write_text('{}\n')
        _skills, result = self.install_home(repo, '--target', str(self.target))
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue((old / '.oasis-install.json').is_file())
        self.assertTrue((self.target / '.oasis-install.json').is_file())
        self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)

    def test_refuses_target_inside_repository(self):
        inside = ROOT / 'tmp-install-target'
        result = self.run_install('--target', str(inside))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('target overlaps the repository', result.stderr)
        self.assertFalse(inside.exists())

    def test_refuses_relative_target_and_missing_parent(self):
        result = self.run_install('--target', 'relative/oasis')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('target must be an absolute path', result.stderr)
        missing = self.scratch / 'missing' / 'oasis'
        result = self.run_install('--target', str(missing))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('target parent does not exist', result.stderr)
        self.assertFalse(missing.parent.exists())

    def test_rejects_unknown_option(self):
        result = self.run_install('--bogus')
        self.assertEqual(result.returncode, 2)
        self.assertIn('usage: install.sh', result.stderr)


if __name__ == '__main__':
    unittest.main()
