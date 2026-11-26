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
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'oasis'
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
        (python.parent.parent / 'pyvenv.cfg').write_text('home = /usr/bin\n')  # an environment (S5)
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

    def migrate(self, *args, project=None, program=CLI, confirm=True):
        """migrate; with --apply, confirmed (v0.16.0 S1) with the workspace file it writes: under
        --workspace <dir>, else self.project, unless confirm is False."""
        if confirm and '--apply' in args:
            directory = args[args.index('--workspace') + 1] if '--workspace' in args else self.project
            args = (*args, '--confirm', str(Path(directory) / 'oasis-workspace.toml'))
        return subprocess.run([sys.executable, '-B', str(program), '--project', str(project or self.main),
                               'migrate', *args], capture_output=True, text=True, env=self.env, cwd=self.scratch)

    def legacy_reader(self, checkout):
        """What migrate reads for a checkout before converting it (config.py refuses a profile)."""
        spec = importlib.util.spec_from_file_location('oasis_migrate_under_test', ROOT / 'tools' / 'migrate.py')
        migrate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migrate)
        previous = {key: os.environ.get(key) for key in self.env}
        os.environ.update(self.env)
        try:
            values = migrate.legacy_load(migrate.sibling('config'), checkout)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        return [f'{name}={shlex.quote(value)}' for name, value in values.items()]

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
                f'rewrite {self.lock}: 4 entries relative to its directory, hashes unchanged\n'
                f'rename {main}/.odoo19-agent.toml to .odoo19-agent.toml.bak-<stamp>\n'
                f'rename {feature}/.odoo19-agent.toml to .odoo19-agent.toml.bak-<stamp>\n'
                f'back up {self.conf} as odoo.conf.bak-<stamp>\n'
                f'remove addons_path and data_dir from {self.conf}; data_dir moves to [tooling].data_dir\n'
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
        for program in (CLI,):
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

    def test_plan_prints_the_plan_and_never_applies(self):
        before = self.tree()
        for args in (('--plan',), ('--workspace', str(self.project), '--plan'), ('--plan', f'--workspace={self.project}')):
            with self.subTest(args=args):
                result = self.migrate(*args)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertEqual(STAMP.sub('.bak-<stamp>', result.stdout),
                                 self.plan('dry run: nothing changed; run with --apply to migrate'))
                self.assertEqual(self.tree(), before)
        # --plan with --apply is refused in the tool itself, whatever the order.
        for args in (('--plan', '--apply'), ('--apply', '--plan'), ('--plan', '--plan'),
                     ('--workspace', '--plan', '--apply')):
            with self.subTest(args=args):
                result = self.migrate(*args)
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertEqual(self.tree(), before)

    # -- apply ----------------------------------------------------------------------------------

    def test_apply_writes_the_workspace_and_keeps_every_configuration_equivalent(self):
        before = {checkout: self.legacy_reader(checkout) for checkout in (self.main, self.feature)}
        for checkout in (self.main, self.feature):
            refused = subprocess.run([sys.executable, '-B', str(READER), str(checkout)],
                                     capture_output=True, text=True, env=self.env)
            self.assertEqual((refused.returncode, refused.stdout), (2, ''))
            self.assertIn('is the old profile format, no longer read', refused.stderr)
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

    def test_profiles_without_logs_migrate_to_the_default_logs_next_to_the_workspace_file(self):
        # v0.17.0: a profile without logs used dev/logs/odoo19, a default that is gone; the migrated checkouts use
        # logs next to the workspace file, which is no verification mismatch.
        for checkout, text in ((self.main, PROFILE), (self.feature, FEATURE_PROFILE)):
            (checkout / '.odoo19-agent.toml').write_text(text.replace("logs = '../../logs'\n", ''))
        result = self.migrate('--apply')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertNotIn('logs', (self.project / 'oasis-workspace.toml').read_text())
        for checkout in (self.main, self.feature):
            with self.subTest(checkout=checkout.name):
                values = subprocess.run([sys.executable, '-B', str(READER), str(checkout)],
                                        capture_output=True, text=True, env=self.env)
                self.assertEqual((values.returncode, values.stderr), (0, ''))
                self.assertIn(f"LOGS_DIR={shlex.quote(str(self.project / 'logs'))}\n", values.stdout)

    def test_apply_without_confirm_prints_the_plan_and_names_the_exact_command(self):
        # v0.16.0 S1: --apply is Tier B; --confirm takes the workspace file the plan writes.
        before = self.tree()
        workspace = self.project / 'oasis-workspace.toml'
        for args, confirm, error in (
                (('--apply',), None, f'ERROR: migrate --apply rewrites the configuration files of every checkout and '
                                     f'writes {workspace} (Tier B: it needs explicit confirmation); nothing changed. '
                                     f'Run: oasis --project {self.main} migrate --apply --confirm {workspace}\n'),
                (('--apply', '--confirm', str(self.project)), str(self.project),
                 f'ERROR: --confirm {self.project} does not name the workspace file {workspace}; nothing changed. '
                 f'Run: oasis --project {self.main} migrate --apply --confirm {workspace}\n'),
                (('--workspace', str(self.project), '--apply', f'--confirm={self.project}/x'), None,
                 f'ERROR: --confirm {self.project}/x does not name the workspace file {workspace}; nothing changed. '
                 f'Run: oasis --project {self.main} migrate --workspace {self.project} --apply --confirm {workspace}\n')):
            with self.subTest(args=args):
                result = self.migrate(*args, confirm=False)
                self.assertEqual((result.returncode, result.stderr), (2, error))
                self.assertEqual(STAMP.sub('.bak-<stamp>', result.stdout), self.plan('')[:-1])
                self.assertEqual(self.tree(), before)
        # --confirm without --apply is a usage error.
        result = self.migrate('--confirm', str(workspace), confirm=False)
        self.assertEqual((result.returncode, result.stdout), (2, ''))

    def test_the_legacy_refusal_names_the_exact_commands_and_the_confirmed_one_migrates(self):
        # v0.16.0 S1 review: no placeholder. The workspace file is the one migrate --plan writes (its
        # `write <file>` line): the plan made read-only, the same from either checkout.
        before = self.tree()
        workspace = self.project / 'oasis-workspace.toml'
        for checkout in (self.main, self.feature):
            plan = shlex.join(['oasis', '--project', str(checkout), 'migrate', '--plan'])
            apply = shlex.join(['oasis', '--project', str(checkout), 'migrate', '--apply', '--confirm', str(workspace)])
            refusal = (f'{checkout}/.odoo19-agent.toml is the old profile format, no longer read: run {plan} to see '
                       f'its conversion to oasis-workspace.toml, then {apply}.')
            with self.subTest(checkout=checkout.name):
                result = subprocess.run([sys.executable, '-B', str(CLI), '--project', str(checkout), 'status'],
                                        capture_output=True, text=True, env=self.env, cwd=self.scratch)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', f'ERROR: {refusal}\n'))
                doctor = subprocess.run([sys.executable, '-B', str(CLI), '--project', str(checkout), 'doctor'],
                                        capture_output=True, text=True, env=self.env, cwd=self.scratch)
                self.assertEqual(doctor.returncode, 1, doctor.stdout)
                self.assertEqual(doctor.stdout.splitlines()[:2],
                                 [f'FAIL configuration={refusal}', f'  fix: {plan}, then {apply}'])
                self.assertEqual(self.tree(), before)
        # The command it names runs as written.
        words = shlex.split(apply)
        result = subprocess.run([sys.executable, '-B', str(CLI), *words[1:]], capture_output=True, text=True,
                                env=self.env, cwd=self.scratch)
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertTrue(result.stdout.endswith(f'verified: 2 checkouts load the same configuration from {workspace}\n'))

    def test_the_legacy_refusal_names_only_the_plan_when_migrate_cannot_make_one(self):
        (self.project / 'oasis-workspace.toml').write_text('# hand-written\n')
        result = subprocess.run([sys.executable, '-B', str(CLI), '--project', str(self.main), 'status'],
                                capture_output=True, text=True, env=self.env, cwd=self.scratch)
        plan = shlex.join(['oasis', '--project', str(self.main), 'migrate', '--plan'])
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
            f'ERROR: {self.main}/.odoo19-agent.toml is the old profile format, no longer read: run {plan} to see its '
            'conversion to oasis-workspace.toml or what stops it.\n')))
        self.assertEqual(self.migrate('--plan').stderr, f'ERROR: {self.project}/oasis-workspace.toml already exists.\n')

    def test_abbreviated_or_valued_flags_are_usage_errors(self):
        # The guard (pi/lib/bash-guard.ts) asks for them anyway; the tool never takes them as --apply.
        for args in (('--ap',), ('--appl',), ('--apply=x',), ('--pl',), ('--plan=x',), ('--apply', '--conf', 'x')):
            with self.subTest(args=args):
                self.assert_refused(args, f'Usage: {CLI} migrate [--workspace <dir>] [--apply --confirm <workspace file> | --plan]\n')

    def test_second_run_has_nothing_to_migrate(self):
        self.assertEqual(self.migrate('--apply').returncode, 0)
        before = self.tree()
        for args in ((), ('--apply',)):
            for checkout in (self.main, self.feature):
                with self.subTest(args=args, checkout=checkout.name):
                    result = self.migrate(*args, project=checkout)
                    self.assertEqual((result.returncode, result.stdout, result.stderr),
                                     (0, f'nothing to migrate: {checkout} has no .odoo19-agent.toml; it is already '
                                         f'configured by {self.project}/oasis-workspace.toml\n', ''))
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

    def test_an_unreadable_or_invalid_profile_is_refused_naming_it(self):
        profile = self.main / '.odoo19-agent.toml'
        for text, stderr in (('[tooling\n', f'ERROR: Invalid TOML in {profile}.\n'),
                             ("tooling = 'x'\n", f'ERROR: Invalid tooling configuration: {profile} has no [tooling] table.\n')):
            with self.subTest(text=text):
                profile.write_text(text)
                self.assert_refused((), stderr)
                self.assert_refused(('--apply',), stderr)
        if os.geteuid() == 0:
            return  # root reads a 000 file
        profile.write_text(PROFILE)
        before = self.tree()
        profile.chmod(0o000)
        try:
            result = self.migrate('--apply')
        finally:
            profile.chmod(0o644)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'ERROR: Cannot read {profile}: Permission denied.\n'))
        self.assertEqual(self.tree(), before)

    def test_existing_workspace_file_is_never_replaced(self):
        (self.project / 'oasis-workspace.toml').write_text('# hand-written\n')
        self.assert_refused(('--apply',), f'ERROR: {self.project}/oasis-workspace.toml already exists.\n')

    def test_usage(self):
        for args in (('--bogus',), ('--apply', '--apply'), ('--workspace',)):
            self.assert_refused(args, f'Usage: {CLI} migrate [--workspace <dir>] [--apply --confirm <workspace file> | --plan]\n')
        result = self.migrate('--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(f'Usage: {CLI} migrate [--workspace <dir>] [--apply --confirm <workspace file> | --plan]\n'))

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


    def test_read_only_conf_fails_cleanly_and_changes_nothing(self):
        self.conf.chmod(0o440)
        self.addCleanup(self.conf.chmod, 0o600)
        before = self.tree()
        result = self.migrate('--apply')
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('could not be undone', result.stderr)
        self.assertEqual(self.tree(), before)

    def test_conf_keeps_comments_crlf_and_other_sections(self):
        self.conf.write_bytes((f"# c\r\n[options]\r\n; x\r\nADDONS_PATH = {self.main},\r\n    {self.project}/source/odoo/addons\r\n"
            f"admin_passwd = S  \r\ndata_dir = {self.project}/data\r\nhttp_port = {self.port}\n[other]\naddons_path = keep\n").encode())
        original = self.conf.read_bytes()
        self.assertEqual(self.migrate('--apply').returncode, 0)
        self.assertEqual(self.conf.read_bytes(), b"# c\r\n[options]\r\n; x\r\nadmin_passwd = S  \r\n"
                         + f"http_port = {self.port}\n[other]\naddons_path = keep\n".encode())
        [backup] = self.backups(self.config, 'odoo.conf')
        self.assertEqual(backup.read_bytes(), original)

    def test_group_writable_workspace_dir_is_refused(self):
        os.chmod(self.project, 0o775)
        self.addCleanup(os.chmod, self.project, 0o755)
        before = self.tree()
        self.assertEqual(self.migrate('--apply').returncode, 2)
        self.assertEqual(self.tree(), before)


    def test_a_signal_during_apply_undoes_every_change(self):
        # A kill from a timeout or a closed terminal must not leave a half-migrated project.
        before = self.tree()
        env = dict(self.env, OASIS_PROJECT_ROOT=str(self.main))
        for name, number in (('SIGTERM', 15), ('SIGHUP', 1)):
            with self.subTest(signal=name):
                script = (
                    "import importlib.util, os, signal, sys\n"
                    "spec = importlib.util.spec_from_file_location('migrate', sys.argv[1])\n"
                    "migrate = importlib.util.module_from_spec(spec); spec.loader.exec_module(migrate)\n"
                    "original = migrate.Changes.apply\n"
                    "count = {'n': 0}\n"
                    "def apply(self, action):\n"
                    "    original(self, action)\n"
                    "    count['n'] += 1\n"
                    "    if count['n'] == 3:\n"
                    f"        os.kill(os.getpid(), signal.{name}); os.kill(os.getpid(), signal.{name})\n"
                    "migrate.Changes.apply = apply\n"
                    "sys.exit(migrate.main(['--apply', '--confirm', sys.argv[2]]))\n")
                result = subprocess.run([sys.executable, '-B', '-c', script, str(ROOT / 'tools' / 'migrate.py'),
                                         str(self.project / 'oasis-workspace.toml')],
                                        capture_output=True, text=True, env=env, cwd=self.scratch)
                self.assertEqual(result.returncode, 128 + number, result.stderr)
                self.assertIn('every change was undone', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual(self.tree(), before)

    def test_conf_rewrite_is_the_last_change(self):
        # Killed before the conf rewrite, the project still runs: the conf still names its paths
        # while the profiles are already renamed and the workspace file supplies the rest.
        script = (
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('migrate', sys.argv[1])\n"
            "migrate = importlib.util.module_from_spec(spec); spec.loader.exec_module(migrate)\n"
            "original = migrate.Changes.apply\n"
            "def apply(self, action):\n"
            "    print(action[0], getattr(action[1], 'name', action[1]), file=sys.stderr)\n"
            "    original(self, action)\n"
            "migrate.Changes.apply = apply\n"
            "sys.exit(migrate.main(['--apply', '--confirm', sys.argv[2]]))\n")
        env = dict(self.env, OASIS_PROJECT_ROOT=str(self.main))
        result = subprocess.run([sys.executable, '-B', '-c', script, str(ROOT / 'tools' / 'migrate.py'),
                                 str(self.project / 'oasis-workspace.toml')],
                                capture_output=True, text=True, env=env, cwd=self.scratch)
        self.assertEqual(result.returncode, 0, result.stderr)
        steps = [line for line in result.stderr.splitlines() if line.split(' ')[0] in ('create', 'replace', 'rename')]
        self.assertEqual(steps[-1], 'replace odoo.conf')
        self.assertLess(max(i for i, step in enumerate(steps) if step.startswith('rename')), len(steps) - 1)


class MigrateSurfaceTests(unittest.TestCase):
    def test_entry_point_lists_migrate(self):
        self.assertIn("'migrate'", (ROOT / 'oasis').read_text())

    def test_gentle_shell_command_shows_the_plan_then_applies(self):
        source = (ROOT / 'pi/extensions/oasis.ts').read_text()
        # The subcommand table (usage pinned in pi/tests/commands.test.ts) and its dispatch.
        self.assertIn('name: "migrate"', (ROOT / 'pi/lib/commands.ts').read_text())
        self.assertIn('migrate: (ctx) => migrate(ctx),', source)
        # v0.16.0 S1: the flow lives in lib/project.ts (migrateFlow, pi/tests/project.test.ts runs it):
        # confirmed with the workspace file the plan writes (planConfirmation).
        self.assertIn('await migrateFlow(planFlow(root, ctx.ui));', source)
        flow = (ROOT / 'pi/lib/project.ts').read_text()
        self.assertIn('flow.run(["migrate"])', flow)
        self.assertIn('const workspace = planConfirmation("migrate", plan.stdout);', flow)
        self.assertIn('flow.run(["migrate", "--apply", ...confirm])', flow)
        self.assertIn('flow.ui.confirm("oasis migrate"', flow)

    def test_readme_documents_migrate(self):
        # The section moved from the README to its own topic file, linked from the README.
        self.assertIn('](docs/migrating.md)', (ROOT / 'README.md').read_text())
        doc = (ROOT / 'docs/migrating.md').read_text()
        self.assertTrue(doc.startswith('# Migrating to the workspace file\n'))
        self.assertIn('oasis --project /absolute/checkout migrate [--workspace <dir>] [--apply --confirm <workspace file> | --plan]', doc)


if __name__ == '__main__':
    unittest.main()
