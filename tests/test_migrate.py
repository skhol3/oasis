"""`oasis --project <checkout> migrate [--workspace <dir>] [--apply]` on a corpus-like synthetic project.

Layout (every directory in a fresh system temp directory, git with an empty configuration and
a ceiling at the scratch directory, so nothing reads or writes a real project):

    <p>/codigo/shop              main checkout, legacy profile
    <p>/codigo/shop-feature      linked worktree, legacy profile with checkout_slug
    <p>/config/                  odoo.conf, runtime-env, compose.yml, requirements/
    <p>/logs/  <p>/source/odoo/  <p>/environments/corpus/

The odoo.conf carries an admin_passwd marker that must never be printed; the environment
file is named neutrally (runtime-env) and is never opened.
"""
import hashlib
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'oasis'
ALIAS = ROOT / 'odoo19'
READER = ROOT / 'tools' / 'config.py'
GIT = ['git', '-c', 'user.name=oasis tests', '-c', 'user.email=tests@example.invalid',
       '-c', 'init.defaultBranch=main', '-c', 'commit.gpgsign=false']
MARKER = 'migrate-must-not-print-this'
STAMP = re.compile(r'\.bak-\d{8}T\d{6}Z')
REQUIREMENTS = ('runtime.in', 'runtime.txt', 'dev.in', 'dev.txt')
PROFILE = '''[tooling]
version = '19.0'
python_version = '3.12'
community = '../../source/odoo'
environment = '../../environments/corpus'
config = '../../config/odoo.conf'
env_file = '../../config/runtime-env'
compose = '../../config/compose.yml'
requirements = '../../config/requirements'
addons_paths = ['.']
db_service = 'db'
dev_prefix = 'cc_dev_'
test_prefix = 'cc_test_'
logs = '../../logs'

[development]
administrator_login = 'admin'
users = [{login = 'sales', name = 'Sales User', groups = ['sales_team.group_sale_salesman']}]

[commands]
entrypoint = '~/.agents/skills/odoo19/oasis'
'''
FEATURE_PROFILE = PROFILE.replace("logs = '../../logs'\n", "logs = '../../logs'\ncheckout_slug = 'feature_2'\n")
WORKSPACE = '''# Written by oasis migrate. Paths are relative to this file, addons_paths to each checkout.
workspace_version = 1
odoo_version = '19.0'

[tooling]
community = 'source/odoo'
environment = 'environments/corpus'
config = 'config/odoo.conf'
env_file = 'config/runtime-env'
compose = 'config/compose.yml'
requirements = 'config/requirements'
addons_paths = ['.']
db_service = 'db'
dev_prefix = 'cc_dev_'
test_prefix = 'cc_test_'
logs = 'logs'
data_dir = 'data'

[development]
administrator_login = 'admin'
users = [{login = 'sales', name = 'Sales User', groups = ['sales_team.group_sale_salesman']}]
'''
CHECKOUT = "[tooling]\ncheckout_slug = 'feature_2'\n"
PYTHON = ('#!/bin/sh\n'
          'if [ "$1" = "-c" ]; then echo 3.12; exit 0; fi\n'
          'if [ "$2" = "--version" ]; then echo "Odoo Server 19.0"; exit 0; fi\n'
          'exit 0\n')
DOCKER = ('#!/bin/sh\n'
          'if [ "$*" = "compose version" ]; then echo "Docker Compose version v2.29.1"; fi\n'
          'exit 0\n')
# Variables that differ by design between a profile and the workspace file (L25).
WORKSPACE_ONLY = ('WORKSPACE_ROOT=', 'ENVIRONMENT_NAME=', 'DATA_DIR=')


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(shutil.which('git'), 'git is required')
class MigrateTests(unittest.TestCase):
    def setUp(self):
        previous = os.umask(0o022)
        self.addCleanup(os.umask, previous)
        self.scratch = Path(tempfile.mkdtemp(prefix='oasis-migrate-')).resolve()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        self.bindir = self.scratch / 'bin'
        self.bindir.mkdir()
        self.runtime = self.scratch / 'runtime'
        self.runtime.mkdir(mode=0o700)
        self.env.update({'GIT_CEILING_DIRECTORIES': str(self.scratch), 'GIT_CONFIG_GLOBAL': os.devnull,
                         'GIT_CONFIG_NOSYSTEM': '1', 'PYTHONDONTWRITEBYTECODE': '1',
                         'XDG_RUNTIME_DIR': str(self.runtime),
                         'PATH': f'{self.bindir}:{os.environ["PATH"]}'})
        for name, text in (('docker', DOCKER), ('flock', '#!/bin/sh\nexit 0\n')):
            (self.bindir / name).write_text(text)
            (self.bindir / name).chmod(0o755)
        self.project = self.scratch / 'projects' / 'corpus'
        self.main = self.project / 'codigo' / 'shop'
        self.feature = self.project / 'codigo' / 'shop-feature'
        self.config = self.project / 'config'
        self.conf = self.config / 'odoo.conf'
        self.lock = self.config / 'requirements' / 'lock.sha256'
        self.port = free_port()
        self.build()

    # -- fixture --------------------------------------------------------------------------------

    def git(self, cwd, *args):
        return subprocess.run([*GIT, '-C', str(cwd), *args], check=True, capture_output=True,
                              text=True, env=self.env).stdout.strip()

    def conf_text(self, addons=None):
        addons = addons or f'{self.main},{self.project}/source/odoo/addons'
        return (f'[options]\naddons_path = {addons}\ndata_dir = {self.project}/data\n'
                f'admin_passwd = {MARKER}\nhttp_port = {self.port}\n')

    def build(self):
        self.main.mkdir(parents=True)
        (self.main / 'README.md').write_text('fixture\n')
        self.git(self.main, 'init', '-q')
        self.git(self.main, 'add', 'README.md')
        self.git(self.main, 'commit', '-q', '-m', 'init')
        self.git(self.main, 'worktree', 'add', '-q', '-b', 'feature', str(self.feature))
        (self.main / '.odoo19-agent.toml').write_text(PROFILE)
        (self.feature / '.odoo19-agent.toml').write_text(FEATURE_PROFILE)
        source = self.project / 'source/odoo'
        (source / 'odoo').mkdir(parents=True)
        (source / 'addons').mkdir()
        (source / 'odoo-bin').touch()
        (source / 'odoo/release.py').write_text('version_info = (19, 0, 0, "final", 0)\n')
        python = self.project / 'environments/corpus/bin/python'
        python.parent.mkdir(parents=True)
        python.write_text(PYTHON)
        python.chmod(0o755)
        requirements = self.config / 'requirements'
        requirements.mkdir(parents=True)
        self.conf.write_text(self.conf_text())
        self.conf.chmod(0o640)
        (self.config / 'runtime-env').write_text(f'ODOO_DB_PASSWORD={MARKER}\n')
        (self.config / 'compose.yml').write_text('name: corpus\nservices:\n  db:\n    image: postgres:16\n')
        for name in REQUIREMENTS:
            (requirements / name).write_text(f'# {name}\n')
        # Legacy entries: relative to the checkout (check-environment ran from the project root).
        self.lock.write_text(''.join(f'{sha256(requirements / name)}  ../../config/requirements/{name}\n'
                                     for name in REQUIREMENTS))
        (self.project / 'logs').mkdir()

    def tree(self):
        """Every path below the scratch directory with its content (files), target (links) and mode."""
        result = {}
        for path in sorted(self.scratch.rglob('*')):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                value = os.readlink(path)
            elif stat.S_ISREG(info.st_mode):
                value = path.read_bytes()
            else:
                value = None
            result[str(path.relative_to(self.scratch))] = (value, stat.S_IMODE(info.st_mode))
        return result

    def migrate(self, *args, project=None, program=CLI):
        return subprocess.run([sys.executable, '-B', str(program), '--project', str(project or self.main),
                               'migrate', *args], capture_output=True, text=True, env=self.env, cwd=self.scratch)

    def reader(self, checkout):
        result = subprocess.run([sys.executable, '-B', str(READER), str(checkout)],
                                capture_output=True, text=True, env=self.env)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        return result.stdout.splitlines()

    def plan(self, last):
        p, main, feature = self.project, self.main, self.feature
        workspace = ''.join(f'  {line}\n' if line else '\n' for line in WORKSPACE.splitlines())
        return (f'workspace: {p}\n'
                f'checkout: {main} (main)\n'
                f'checkout: {feature} (linked)\n'
                f'write {p}/oasis-workspace.toml\n'
                f'{workspace}'
                f'write {feature}/oasis-checkout.toml\n'
                "  [tooling]\n"
                "  checkout_slug = 'feature_2'\n"
                f'back up {self.conf} as odoo.conf.bak-<stamp>\n'
                f'remove addons_path and data_dir from {self.conf}; data_dir moves to [tooling].data_dir\n'
                f'rewrite {self.lock}: 4 entries relative to its directory, hashes unchanged\n'
                f'rename {main}/.odoo19-agent.toml to .odoo19-agent.toml.bak-<stamp>\n'
                f'rename {feature}/.odoo19-agent.toml to .odoo19-agent.toml.bak-<stamp>\n'
                'not migrated: [commands] (kept in the profile backups)\n'
                f'{last}\n')

    def assert_refused(self, args, stderr, code=2):
        before = self.tree()
        result = self.migrate(*args)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (code, '', stderr))
        self.assertEqual(self.tree(), before)

    def backups(self, directory, name):
        return sorted(directory.glob(f'{name}.bak-*'))

    # -- dry run --------------------------------------------------------------------------------

    def test_dry_run_prints_the_exact_plan_and_changes_nothing(self):
        before = self.tree()
        for program in (CLI, ALIAS):
            with self.subTest(program=program.name):
                result = self.migrate(program=program)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(STAMP.sub('.bak-<stamp>', result.stdout),
                                 self.plan('dry run: nothing changed; run with --apply to migrate'))
                self.assertNotIn(MARKER, result.stdout)
                self.assertEqual(self.tree(), before)

    def test_dry_run_from_the_linked_worktree_prints_the_same_plan(self):
        before = self.tree()
        result = self.migrate(project=self.feature)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(STAMP.sub('.bak-<stamp>', result.stdout),
                         self.plan('dry run: nothing changed; run with --apply to migrate'))
        self.assertEqual(self.tree(), before)

    # -- apply ----------------------------------------------------------------------------------

    def test_apply_writes_the_workspace_and_keeps_every_configuration_equivalent(self):
        before = {checkout: self.reader(checkout) for checkout in (self.main, self.feature)}
        original_conf = self.conf.read_bytes()
        hashes = [line.split()[0] for line in self.lock.read_text().splitlines()]
        tree = self.tree()
        result = self.migrate('--apply')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(STAMP.sub('.bak-<stamp>', result.stdout), self.plan(
            f'verified: 2 checkouts load the same configuration from {self.project}/oasis-workspace.toml'))
        self.assertNotIn(MARKER, result.stdout)
        # The workspace and checkout files, exact and private.
        workspace = self.project / 'oasis-workspace.toml'
        self.assertEqual(workspace.read_text(), WORKSPACE)
        self.assertEqual(stat.S_IMODE(workspace.stat().st_mode), 0o600)
        checkout = self.feature / 'oasis-checkout.toml'
        self.assertEqual(checkout.read_text(), CHECKOUT)
        self.assertEqual(stat.S_IMODE(checkout.stat().st_mode), 0o600)
        self.assertFalse((self.main / 'oasis-checkout.toml').exists())
        # Profiles renamed, byte for byte.
        for directory, text in ((self.main, PROFILE), (self.feature, FEATURE_PROFILE)):
            self.assertFalse((directory / '.odoo19-agent.toml').exists())
            [backup] = self.backups(directory, '.odoo19-agent.toml')
            self.assertEqual(backup.read_text(), text)
        # odoo.conf: only the addons_path and data_dir lines removed, mode kept; backup identical, 0600.
        self.assertEqual(self.conf.read_text(), f'[options]\nadmin_passwd = {MARKER}\nhttp_port = {self.port}\n')
        self.assertEqual(stat.S_IMODE(self.conf.stat().st_mode), 0o640)
        [conf_backup] = self.backups(self.config, 'odoo.conf')
        self.assertEqual(conf_backup.read_bytes(), original_conf)
        self.assertEqual(stat.S_IMODE(conf_backup.stat().st_mode), 0o600)
        # lock.sha256: entries relative to its directory, the same hashes, and they verify there.
        self.assertEqual(self.lock.read_text(), ''.join(f'{digest}  {name}\n'
                                                       for digest, name in zip(hashes, REQUIREMENTS)))
        checked = subprocess.run(['sha256sum', '--check', '--strict', 'lock.sha256'], cwd=self.lock.parent,
                                 capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        # Nothing else changed.
        changed = {'projects/corpus/oasis-workspace.toml', 'projects/corpus/codigo/shop-feature/oasis-checkout.toml',
                   'projects/corpus/config/odoo.conf', 'projects/corpus/config/requirements/lock.sha256',
                   'projects/corpus/codigo/shop/.odoo19-agent.toml',
                   'projects/corpus/codigo/shop-feature/.odoo19-agent.toml'}
        after = self.tree()
        new = {STAMP.sub('', path) for path in after if STAMP.search(path)}
        self.assertEqual(new, {'projects/corpus/config/odoo.conf', 'projects/corpus/codigo/shop/.odoo19-agent.toml',
                               'projects/corpus/codigo/shop-feature/.odoo19-agent.toml'})
        self.assertEqual({path: value for path, value in after.items() if path not in changed and not STAMP.search(path)},
                         {path: value for path, value in tree.items() if path not in changed})
        # config.load equivalence: every variable but the workspace-only ones is unchanged.
        for checkout_root in (self.main, self.feature):
            after_lines = self.reader(checkout_root)
            self.assertEqual([line for line in after_lines if not line.startswith(WORKSPACE_ONLY)],
                             [line for line in before[checkout_root] if not line.startswith(WORKSPACE_ONLY)])
            self.assertIn(f'WORKSPACE_ROOT={self.project}', after_lines)
            self.assertIn(f'DATA_DIR={self.project}/data', after_lines)
        self.assertIn('CHECKOUT_SLUG=feature_2', self.reader(self.feature))

    def test_doctor_passes_on_both_checkouts_after_migration(self):
        result = self.migrate('--apply')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        for checkout in (self.main, self.feature):
            with self.subTest(checkout=checkout.name):
                doctor = subprocess.run([sys.executable, '-B', str(CLI), '--project', str(checkout), 'doctor'],
                                        capture_output=True, text=True, env=self.env, cwd=self.scratch)
                self.assertEqual((doctor.returncode, doctor.stderr), (0, ''), doctor.stdout)
                lines = doctor.stdout.splitlines()
                self.assertEqual(lines[0], 'PASS configuration=workspace')
                self.assertIn('PASS odoo_conf', lines)
                self.assertIn('PASS data_dir', lines)
                self.assertEqual(lines[-1], 'doctor_failures=0')
                self.assertNotIn(MARKER, doctor.stdout)

    def test_second_run_has_nothing_to_migrate(self):
        self.assertEqual(self.migrate('--apply').returncode, 0)
        before = self.tree()
        for args in ((), ('--apply',)):
            for checkout in (self.main, self.feature):
                with self.subTest(args=args, checkout=checkout.name):
                    result = self.migrate(*args, project=checkout)
                    self.assertEqual((result.returncode, result.stdout, result.stderr),
                                     (0, f'nothing to migrate: {checkout} has no .odoo19-agent.toml\n', ''))
        self.assertEqual(self.tree(), before)

    def test_explicit_workspace_above_the_default(self):
        target = self.project.parent
        result = self.migrate('--workspace', str(target), '--apply')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        text = (target / 'oasis-workspace.toml').read_text()
        self.assertIn("config = 'corpus/config/odoo.conf'\n", text)
        self.assertIn("data_dir = 'corpus/data'\n", text)
        self.assertIn("addons_paths = ['.']\n", text)
        self.assertFalse((self.project / 'oasis-workspace.toml').exists())

    # -- refusals -------------------------------------------------------------------------------

    def test_disagreeing_profiles_are_refused_listing_only_the_keys(self):
        profile = self.feature / '.odoo19-agent.toml'
        profile.write_text(FEATURE_PROFILE.replace("db_service = 'db'", "db_service = 'db2'")
                           .replace("env_file = '../../config/runtime-env'", "env_file = '../../config/other-env'")
                           .replace("administrator_login = 'admin'", "administrator_login = 'root'"))
        self.assert_refused((), 'ERROR: Cannot migrate: the profiles of the checkouts disagree on '
                                'development.administrator_login, tooling.db_service, tooling.env_file.\n')
        self.assert_refused(('--apply',), 'ERROR: Cannot migrate: the profiles of the checkouts disagree on '
                                          'development.administrator_login, tooling.db_service, tooling.env_file.\n')

    def test_workspace_that_is_not_above_every_checkout_is_refused(self):
        for target in (self.main, self.project / 'codigo' / 'shop-feature'):
            self.assert_refused(('--workspace', str(target), '--apply'),
                                f'ERROR: Refusing --workspace {target}: it is not above every checkout '
                                f'({self.main}, {self.feature}).\n')
        self.assert_refused(('--workspace', 'relative'),
                            'ERROR: --workspace requires an absolute existing directory.\n')

    def test_existing_workspace_file_is_never_replaced(self):
        (self.project / 'oasis-workspace.toml').write_text('# hand-written\n')
        self.assert_refused(('--apply',), f'ERROR: {self.project}/oasis-workspace.toml already exists.\n')

    def test_usage(self):
        for args in (('--bogus',), ('--apply', '--apply'), ('--workspace',)):
            self.assert_refused(args, f'Usage: {CLI} migrate [--workspace <dir>] [--apply]\n')
        result = self.migrate('--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(f'Usage: {CLI} migrate [--workspace <dir>] [--apply]\n'))

    def test_verification_mismatch_restores_every_file(self):
        # An addons_path item that no [tooling] root gives: the composed --addons-path would differ.
        self.conf.write_text(self.conf_text(f'{self.main},/srv/oca,{self.project}/source/odoo/addons'))
        self.conf.chmod(0o640)
        before = self.tree()
        result = self.migrate('--apply')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, 'ERROR: Verification failed; every change was undone:\n'
                                        f'  {self.main}: addons_path\n'
                                        f'  {self.feature}: addons_path\n')
        self.assertNotIn(MARKER, result.stdout + result.stderr)
        self.assertEqual(self.tree(), before)


class MigrateSurfaceTests(unittest.TestCase):
    def test_entry_point_lists_migrate(self):
        self.assertIn("'migrate'", (ROOT / 'oasis').read_text())

    def test_gentle_shell_command_shows_the_plan_then_applies(self):
        source = (ROOT / 'pi/extensions/odoo19.ts').read_text()
        self.assertIn('const USAGE = "Usage: /oasis [setup | doctor | migrate | worktree <feature> <branch>]";',
                      source)
        self.assertIn('run(root, ["migrate"]', source)
        self.assertIn('run(root, ["migrate", "--apply"]', source)
        self.assertIn('ctx.ui.confirm("oasis migrate"', source)

    def test_readme_documents_migrate(self):
        readme = (ROOT / 'README.md').read_text()
        self.assertIn('### Migrating to the workspace file\n', readme)
        self.assertIn('oasis --project /absolute/checkout migrate [--workspace <dir>] [--apply]', readme)


if __name__ == '__main__':
    unittest.main()
