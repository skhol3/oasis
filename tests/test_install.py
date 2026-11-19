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
        self.target = self.scratch / 'skills' / 'odoo19'
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
        self.assertTrue(os.access(self.target / 'odoo19', os.X_OK))
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
        self.assertEqual([p.name for p in self.target.parent.iterdir()], ['odoo19'])

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

    def test_installs_both_entry_points_executable(self):
        # A fixture repository committing the working-tree entry points: `oasis` and its alias `odoo19`.
        repo = self.scratch / 'repo'
        repo.mkdir()
        for name in ('install.sh', 'package.json', 'oasis', 'odoo19'):
            (repo / name).write_bytes((ROOT / name).read_bytes())
            (repo / name).chmod(0o755 if name != 'package.json' else 0o644)
        git = ['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid']
        subprocess.run([*git, 'init', '-q'], check=True)
        subprocess.run([*git, 'add', '.'], check=True)
        subprocess.run([*git, 'commit', '-qm', 'fixture'], check=True)
        result = subprocess.run([str(repo / 'install.sh'), '--target', str(self.target)],
                                capture_output=True, text=True, env=self.env, cwd=self.scratch)
        self.assertEqual(result.returncode, 0, result.stderr)
        for program in ('oasis', 'odoo19'):
            with self.subTest(program=program):
                self.assertTrue(os.access(self.target / program, os.X_OK))
                shown = subprocess.run([str(self.target / program), '--help'], capture_output=True, text=True,
                                       env=dict(self.env, PYTHONDONTWRITEBYTECODE='1'), cwd=self.scratch)
                self.assertEqual((shown.returncode, shown.stderr), (0, ''))
                self.assertTrue(shown.stdout.startswith(f'usage: {program} '), shown.stdout)
        self.assertEqual(sorted(p.name for p in self.target.iterdir()),
                         ['.oasis-install.json', 'oasis', 'odoo19', 'package.json'])

    def test_refuses_target_inside_repository(self):
        inside = ROOT / 'tmp-install-target'
        result = self.run_install('--target', str(inside))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('target overlaps the repository', result.stderr)
        self.assertFalse(inside.exists())

    def test_refuses_relative_target_and_missing_parent(self):
        result = self.run_install('--target', 'relative/odoo19')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('target must be an absolute path', result.stderr)
        missing = self.scratch / 'missing' / 'odoo19'
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
