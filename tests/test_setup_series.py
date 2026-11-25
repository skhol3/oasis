"""`oasis setup` in a checkout of a series its workspace file has no section for (v0.15.0 S5).

The plan adds a `[series."x.y"]` section to the existing workspace file (a version 1 file becomes
version 2, that line only), the machine file entry of that series when it is missing, and only the
files that are missing; a folder that already holds the series' files (config/odoo-15/, or
--config-dir) is adopted. `--exception <module>` writes series_exceptions.

Every directory lives in a fresh system temp directory: git runs with an empty configuration and a
ceiling at the scratch directory, the machine file is a scratch XDG_CONFIG_HOME's and uv is a fake
(tests/test_setup.py), so nothing reads or writes a real project, the real ~/.config or an index.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

from test_setup import GIT, UV

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'oasis'
READER = ROOT / 'tools' / 'config.py'
MARKER = 'setup-must-not-print-this'
DRY_RUN = 'dry run: nothing changed; run with --apply to set up\n'
V1 = '''# Mine: corpus-cafe.
workspace_version = 1
odoo_version = '19.0'

[tooling]
environment = 'environments/cc'
config = 'config/odoo.conf'
env_file = 'config/.env'
compose = 'config/compose.yml'
requirements = 'config/requirements'
addons_paths = ['.']
db_service = 'db'
dev_prefix = 'cc_dev_'
test_prefix = 'cc_test_'
logs = 'logs'
data_dir = 'data'
'''
# The documented corpus-cafe layout (docs/workspace-file.md#example) before its 15.0 section.
V2 = '''workspace_version = 2
odoo_version = '19.0'

[tooling]
environment = 'environments/corpus-cafe-{series}'
config = 'config/odoo.conf'
env_file = 'config/.env'
compose = 'config/compose.yml'
requirements = 'config/requirements/{series}'
addons_paths = ['.']
db_service = 'db'
dev_prefix = 'cc_dev_'
test_prefix = 'cc_test_'
logs = 'logs/{series}'
data_dir = 'data/{series}'
'''
SECTION_COMMENT = ('# Added by oasis setup: what differs for the Odoo 15.0 checkouts '
                   '(docs/setup.md#another-odoo-series).')
SECTION = SECTION_COMMENT + '''
[series."15.0"]
environment = 'environments/cc-15.0'
config = 'config/15.0/odoo.conf'
env_file = 'config/15.0/.env'
compose = 'config/15.0/compose.yml'
requirements = 'config/15.0/requirements'
dev_prefix = 'cc15_dev_'
test_prefix = 'cc15_test_'
logs = 'logs/15.0'
data_dir = 'data/15.0'
series_exceptions = ['report_xlsx']
'''
ADOPTED = SECTION_COMMENT + '''
[series."15.0"]
config = 'config/odoo-15/odoo.conf'
env_file = 'config/odoo-15/.env'
compose = 'config/odoo-15/compose.yml'
requirements = 'config/odoo-15/requirements'
dev_prefix = 'cc15_dev_'
test_prefix = 'cc15_test_'
series_exceptions = ['report_xlsx']
'''


def table():
    spec = importlib.util.spec_from_file_location('oasis_series_setup_table', ROOT / 'tools' / 'odoo_versions.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PYTHON_15 = table().capability('15.0', 'python_default')
POSTGRES_15 = table().capability('15.0', 'postgres_default')


def first_free_port():
    for port in range(5432, 5532):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                continue
            return port
    raise AssertionError('no free port to run the test with')


@unittest.skipUnless(shutil.which('git'), 'git is required')
class SeriesSetupTests(unittest.TestCase):
    def setUp(self):
        previous = os.umask(0o022)
        self.addCleanup(os.umask, previous)
        self.scratch = Path(tempfile.mkdtemp(prefix='oasis-setup-series-')).resolve()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        bindir = self.scratch / 'bin'
        bindir.mkdir()
        (bindir / 'uv').write_text(UV)
        (bindir / 'uv').chmod(0o755)
        self.log = self.scratch / 'uv.log'
        (self.scratch / 'home').mkdir()
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(('GIT_', 'OASIS_', 'ODOO19_'))}
        self.env.update({'GIT_CEILING_DIRECTORIES': str(self.scratch), 'GIT_CONFIG_GLOBAL': os.devnull,
                         'GIT_CONFIG_NOSYSTEM': '1', 'PYTHONDONTWRITEBYTECODE': '1',
                         'XDG_CONFIG_HOME': str(self.scratch / 'xdg'), 'HOME': str(self.scratch / 'home'),
                         'FAKE_LOG': str(self.log), 'PATH': f'{bindir}:{os.environ["PATH"]}'})
        self.machine = self.scratch / 'xdg' / 'oasis' / 'config.toml'
        self.source19 = self.odoo_source(self.scratch / 'sources' / '19.0', (19, 0))
        self.source15 = self.odoo_source(self.scratch / 'sources' / '15.0', (15, 0))
        self.write_machine(f"[series.\"19.0\"]\ncommunity = '{self.source19}'\n")
        self.project = self.scratch / 'corpus-cafe'
        self.workspace = self.project / 'oasis-workspace.toml'
        # The 19.0 series' files, on the first free port: the 15.0 series must get another one.
        self.port19 = first_free_port()
        self.series_files(self.project / 'config', self.port19, 'oasis-cc-19')
        # A 19.0 checkout (outside git) and the 15.0 branch whose report_xlsx declares 16.0.
        self.checkout19 = self.make_module(self.project / 'codigo' / 'corpus-cafe', 'cafe_sale', '19.0.1.0.0')
        self.checkout = self.make_module(self.project / 'codigo' / 'facturacion', 'cafe_sale', '15.0.1.0.0')
        self.make_module(self.checkout, 'report_xlsx', '16.0.2.0.2')
        self.git(self.checkout, 'init', '-q')
        self.git(self.checkout, 'add', '.')
        self.git(self.checkout, 'commit', '-q', '-m', 'init')

    # -- fixture --------------------------------------------------------------------------------

    def git(self, cwd, *args):
        return subprocess.run([*GIT, '-C', str(cwd), *args], check=True, capture_output=True,
                              text=True, env=self.env).stdout.strip()

    def odoo_source(self, path, series):
        (path / 'odoo').mkdir(parents=True)
        (path / 'odoo' / 'release.py').write_text(f"version_info = {series + (0, 'final', 0, '')}\n")
        (path / 'requirements.txt').write_text('psycopg2\n')
        return path

    def make_module(self, root, name, version):
        (root / name).mkdir(parents=True)
        (root / name / '__manifest__.py').write_text(f"{{'name': '{name}', 'version': '{version}'}}\n")
        return root

    def write_machine(self, text):
        self.machine.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.machine.write_text(text)
        self.machine.chmod(0o600)

    def series_files(self, directory, port, name, requirements=False):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'odoo.conf').write_text(f'[options]\ndb_port = {port}\ndbfilter = ^cc15_\n'
                                             f'admin_passwd = {MARKER}\n')
        (directory / 'compose.yml').write_text(
            f"name: {name}\nservices:\n  db:\n    image: postgres:14-alpine\n    ports:\n"
            f"      - '127.0.0.1:{port}:5432'\n")
        (directory / '.env').write_text(f'ODOO_DB_PASSWORD={MARKER}\n')
        if requirements:
            locks = directory / 'requirements'
            locks.mkdir()
            names = ('runtime.in', 'runtime.txt', 'dev.in', 'dev.txt')
            for item in names:
                (locks / item).write_text(f'# {item}\n')
            (locks / 'lock.sha256').write_text(''.join(
                f'{hashlib.sha256((locks / item).read_bytes()).hexdigest()}  {item}\n' for item in names))

    def setup_cmd(self, *args, root=None):
        return subprocess.run([sys.executable, '-B', str(CLI), '--project', str(root or self.checkout), 'setup',
                               *args], capture_output=True, text=True, env=self.env, stdin=subprocess.DEVNULL,
                              cwd=self.scratch)

    def reader(self, root):
        return subprocess.run([sys.executable, '-B', str(READER), str(root)], capture_output=True, text=True,
                              env=self.env)

    def tree(self):
        found = {}
        for path in sorted(self.scratch.rglob('*')):
            if path == self.log:
                continue
            info = path.lstat()
            found[str(path.relative_to(self.scratch))] = (
                info.st_mode, path.read_bytes() if path.is_file() and not path.is_symlink() else None)
        return found

    def compose_name(self, name):
        return f'oasis-{name}-' + hashlib.sha256(str(self.project).encode()).hexdigest()[:6]

    def port_of(self, stdout):
        match = re.search(r'db_port (\d+);', stdout)
        self.assertIsNotNone(match, stdout)
        return int(match.group(1))

    def assert_refused(self, result, message, before):
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', f'ERROR: {message}\n'))
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.log.exists())

    def indented(self, text):
        return [f'  {line}' if line else '' for line in text.splitlines()]

    def new_plan(self, port):
        """The plan for the 15.0 checkout of the V1 workspace, with nothing of 15.0 on disk."""
        project, series = self.project, self.project / 'config/15.0'
        return '\n'.join([
            f'checkout: {self.checkout} (main)', f'workspace: {self.workspace} (existing)',
            f'series: 15.0 (from the module manifests; {self.workspace} has no [series."15.0"] section)',
            f'community: {self.source15} (from --community)', 'enterprise: none (from --no-enterprise)',
            f'add [series."15.0"] to {self.machine}:', '  [series."15.0"]', f"  community = '{self.source15}'",
            f'change workspace_version = 1 to workspace_version = 2 in {self.workspace} (that line only)',
            f'add [series."15.0"] to {self.workspace}:', *self.indented(SECTION),
            f'create {series / "odoo.conf"} (mode 0600): path-free; db_port {port}; db_user and db_password empty',
            f'create {series / "compose.yml"}: PostgreSQL {POSTGRES_15} (postgres:{POSTGRES_15}) as service db on '
            f'127.0.0.1:{port}, compose project {self.compose_name("cc15")}',
            f'create {series / ".env"} (mode 0600): ODOO_DB_USER and ODOO_DB_PASSWORD, empty',
            f'create {series / "requirements/runtime.in"}: -r {self.source15}/requirements.txt',
            f'create {series / "requirements/dev.in"}: -c runtime.txt, -r runtime.in',
            f'create {project / "logs/15.0"}/', f'create {project / "data/15.0"}/',
            f'compile {series / "requirements"}/runtime.txt, dev.txt and lock.sha256 with Python {PYTHON_15} '
            '(uv pip compile)',
            f'create the environment {project / "environments/cc-15.0"} with Python {PYTHON_15} (uv venv) and sync '
            'dev.txt (uv pip sync)']) + '\n'

    # -- a version 1 workspace ------------------------------------------------------------------

    def test_the_plan_adds_the_section_and_the_machine_entry_and_changes_nothing(self):
        self.workspace.write_text(V1)
        before = self.tree()
        result = self.setup_cmd('--community', str(self.source15), '--no-enterprise', '--exception', 'report_xlsx')
        port = self.port_of(result.stdout)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, self.new_plan(port) + DRY_RUN, ''))
        # A free port, and not the one the 19.0 series' files use (nothing listens there in this test).
        self.assertNotEqual(port, self.port19)
        self.assertTrue(5432 <= port < 5532)
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.log.exists())

    def test_apply_writes_the_section_keeps_the_other_series_and_a_second_run_keeps_everything(self):
        self.workspace.write_text(V1)
        self.workspace.chmod(0o600)
        before19 = self.reader(self.checkout19)
        self.assertEqual((before19.returncode, before19.stderr), (0, ''))
        result = self.setup_cmd('--apply', '--community', str(self.source15), '--no-enterprise',
                                '--exception', 'report_xlsx')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        port = self.port_of(result.stdout)
        series = self.project / 'config/15.0'
        requirements = series / 'requirements'
        environment = self.project / 'environments/cc-15.0'
        self.assertTrue(result.stdout.startswith(self.new_plan(port)), result.stdout)
        self.assertEqual(result.stdout[len(self.new_plan(port)):], '\n'.join([
            f'verified: {self.checkout} loads its configuration from {self.workspace}',
            f'compiled {requirements}/runtime.txt, dev.txt and lock.sha256',
            f'created the environment {environment}',
            'next steps:',
            f'  1. fill in ODOO_DB_USER and ODOO_DB_PASSWORD in {series / ".env"}, and the same values as db_user '
            f'and db_password in {series / "odoo.conf"}',
            f'  2. docker compose --env-file {series / ".env"} -f {series / "compose.yml"} up -d --wait',
            f'  3. oasis --project {self.checkout} doctor',
            f'  4. add a [development] table with administrator_login to {self.workspace} (docs/dev-database.md)',
            f'  5. oasis --project {self.checkout} init-dev-database <module> cc15_dev_manual']) + '\n')
        # Only the version line changed; the section is appended; the mode is kept.
        self.assertEqual(self.workspace.read_text(),
                         V1.replace('workspace_version = 1', 'workspace_version = 2') + '\n' + SECTION)
        self.assertEqual(self.workspace.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.machine.read_text(), f"[series.\"19.0\"]\ncommunity = '{self.source19}'\n\n"
                                                   f"[series.\"15.0\"]\ncommunity = '{self.source15}'\n")
        compose = (series / 'compose.yml').read_text()
        self.assertIn(f'    image: postgres:{POSTGRES_15}\n', compose)
        self.assertIn(f"      - '127.0.0.1:{port}:5432'\n", compose)
        self.assertIn(f'name: {self.compose_name("cc15")}\n', compose)
        self.assertIn(f'db_port = {port}\n', (series / 'odoo.conf').read_text())
        self.assertEqual((series / '.env').stat().st_mode & 0o777, 0o600)
        self.assertEqual((series / '.env').read_text().splitlines()[1:], ['ODOO_DB_USER=', 'ODOO_DB_PASSWORD='])
        self.assertEqual((requirements / 'runtime.in').read_text().splitlines()[-1],
                         f'-r {self.source15}/requirements.txt')
        self.assertEqual([line.split(' (in ')[0] for line in self.log.read_text().splitlines()], [
            f'uv pip compile --python-version {PYTHON_15} runtime.in -o runtime.txt',
            f'uv pip compile --python-version {PYTHON_15} dev.in -o dev.txt',
            f'uv venv --python {PYTHON_15} {environment}',
            f'uv pip sync --python {environment}/bin/python {requirements}/dev.txt'])
        self.assertNotIn(MARKER, result.stdout)
        # The 15.0 checkout loads with its section; the 19.0 checkout is unchanged but the version 2 tail.
        values = self.reader(self.checkout)
        self.assertEqual((values.returncode, values.stderr), (0, ''))
        for line in ('ODOO_VERSION=15.0', f'ODOO_SOURCE={self.source15}', 'DEV_PREFIX=cc15_dev_',
                     f'PYTHON_VERSION={PYTHON_15}', 'SERIES_EXCEPTIONS=report_xlsx',
                     f'LOGS_DIR={self.project / "logs/15.0"}', f'PROJECT_ENVIRONMENT={environment}'):
            self.assertIn(line + '\n', values.stdout)
        after19 = self.reader(self.checkout19)
        self.assertEqual((after19.returncode, after19.stderr), (0, ''))
        self.assertEqual(after19.stdout, before19.stdout + "WORKSPACE_VERSION=2\nSERIES_EXCEPTIONS=''\n")
        # A second run adopts the section and every file it wrote.
        before = self.tree()
        self.log.unlink()
        again = self.setup_cmd('--apply')
        self.assertEqual((again.returncode, again.stderr), (0, ''))
        self.assertIn(f'kept {self.machine}: [series."15.0"] gives the Odoo source\n', again.stdout)
        self.assertTrue(again.stdout.endswith(f'kept the environment {environment}\n'
                                              f'nothing to set up: run oasis --project {self.checkout} doctor\n'),
                        again.stdout)
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.log.exists())

    # -- adopting the files of an earlier setup -------------------------------------------------

    def test_a_folder_that_holds_the_series_files_is_adopted_and_nothing_is_created_there(self):
        self.workspace.write_text(V2)
        self.write_machine(f"[series.\"19.0\"]\ncommunity = '{self.source19}'\n"
                           f"[series.\"15.0\"]\ncommunity = '{self.source15}'\n")
        folder = self.project / 'config/odoo-15'
        self.series_files(folder, 5415, 'corpus-cafe-15', requirements=True)
        held = {path: data for path, data in self.tree().items() if path.startswith('corpus-cafe/config/odoo-15')}
        project = self.project
        plan = '\n'.join([
            f'checkout: {self.checkout} (main)', f'workspace: {self.workspace} (existing)',
            f'series: 15.0 (from the module manifests; {self.workspace} has no [series."15.0"] section)',
            f'community: {self.source15} (from the machine file)', 'enterprise: none (from the machine file)',
            f'kept {self.machine}: [series."15.0"] gives the Odoo source',
            f'add [series."15.0"] to {self.workspace}:', *self.indented(ADOPTED),
            f'adopt {folder} (found): odoo.conf, compose.yml, .env, requirements/',
            f'kept {folder / "odoo.conf"}', f'kept {folder / "compose.yml"}', f'kept {folder / ".env"}',
            f'kept {folder / "requirements/runtime.in"}', f'kept {folder / "requirements/dev.in"}',
            f'create {project / "logs/15.0"}/', f'create {project / "data/15.0"}/',
            f'kept the locks in {folder / "requirements"}: current',
            f'create the environment {project / "environments/corpus-cafe-15.0"} with Python {PYTHON_15} (uv venv) '
            'and sync dev.txt (uv pip sync)']) + '\n'
        before = self.tree()
        result = self.setup_cmd('--exception', 'report_xlsx')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, plan + DRY_RUN, ''))
        self.assertEqual(self.tree(), before)
        applied = self.setup_cmd('--apply', '--exception', 'report_xlsx')
        self.assertEqual((applied.returncode, applied.stderr), (0, ''), applied.stdout)
        self.assertTrue(applied.stdout.startswith(plan), applied.stdout)
        self.assertNotIn(MARKER, applied.stdout)
        self.assertNotIn('fill in', applied.stdout)
        # A version 2 file only gets the section; the adopted folder is left as it was.
        self.assertEqual(self.workspace.read_text(), V2 + '\n' + ADOPTED)
        self.assertEqual({path: data for path, data in self.tree().items()
                          if path.startswith('corpus-cafe/config/odoo-15')}, held)
        values = self.reader(self.checkout)
        self.assertEqual((values.returncode, values.stderr), (0, ''))
        self.assertIn(f'ODOO_CONFIG={folder / "odoo.conf"}\n', values.stdout)
        self.assertIn(f'COMPOSE_FILE={folder / "compose.yml"}\n', values.stdout)

    def test_the_documented_corpus_cafe_example_plans_the_documented_section(self):
        docs = (ROOT / 'docs/setup.md').read_text()
        start = docs.index('# corpus-cafe/oasis-workspace.toml before, example only.\n')
        self.workspace.write_text(docs[start:docs.index('```', start)])
        start = docs.index('add [series."15.0"] to <corpus-cafe>/oasis-workspace.toml:\n')
        documented = docs[start:docs.index('\n...\n', start)].replace('<corpus-cafe>', str(self.project)).replace(
            '<15.0 source>', str(self.source15))
        folder = self.project / 'config/odoo-15'
        self.series_files(folder, 5415, 'corpus-cafe-15')
        result = self.setup_cmd('--community', str(self.source15), '--no-enterprise', '--exception', 'report_xlsx')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn(documented + '\n', result.stdout)
        self.assertIn(f'create the environment {self.project / "environments/corpus-cafe-15.0"} with Python '
                      f'{PYTHON_15} (uv venv)', result.stdout)

    def test_config_dir_names_the_folder_to_adopt_and_missing_pieces_are_created_there(self):
        self.workspace.write_text(V1)
        folder = self.scratch / 'legacy15'
        folder.mkdir()
        (folder / 'odoo.conf').write_text(f'[options]\ndb_port = 5415\nadmin_passwd = {MARKER}\n')
        result = self.setup_cmd('--config-dir', str(folder), '--community', str(self.source15), '--no-enterprise',
                                '--exception', 'report_xlsx')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn(f"  config = '{folder / 'odoo.conf'}'\n  env_file = '{folder / '.env'}'\n"
                      f"  compose = '{folder / 'compose.yml'}'\n  requirements = '{folder / 'requirements'}'\n",
                      result.stdout)
        self.assertIn(f'adopt {folder} (from --config-dir): odoo.conf\nkept {folder / "odoo.conf"}\n'
                      f'create {folder / "compose.yml"}: PostgreSQL {POSTGRES_15} (postgres:{POSTGRES_15}) as service '
                      'db on 127.0.0.1:5415, ', result.stdout)
        self.assertIn(f'create {folder / ".env"} (mode 0600)', result.stdout)
        before = self.tree()
        self.assert_refused(self.setup_cmd('--config-dir', 'legacy15'),
                            '--config-dir requires an absolute existing directory.', before)

    def test_the_machine_file_environments_of_the_series_place_its_environment(self):
        self.workspace.write_text(V1)
        self.write_machine(f"[series.\"19.0\"]\ncommunity = '{self.source19}'\n"
                           f"[series.\"15.0\"]\ncommunity = '{self.source15}'\nenvironments = '/srv/envs15'\n")
        result = self.setup_cmd('--exception', 'report_xlsx')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn("  [series.\"15.0\"]\n  environment = '/srv/envs15/cc15'\n  config = 'config/15.0/odoo.conf'\n",
                      result.stdout)
        self.assertIn('create the environment /srv/envs15/cc15 with Python', result.stdout)

    def test_several_folders_that_hold_series_files_need_config_dir(self):
        self.workspace.write_text(V1)
        for name in ('odoo-15', '15.0'):
            (self.project / 'config' / name).mkdir()
            (self.project / 'config' / name / 'odoo.conf').write_text('[options]\n')
        before = self.tree()
        self.assert_refused(self.setup_cmd('--community', str(self.source15), '--no-enterprise',
                                           '--exception', 'report_xlsx'),
                            f'Several folders hold Odoo 15.0 files: {self.project / "config/15.0"}, '
                            f'{self.project / "config/odoo-15"}; pass --config-dir <dir>.', before)

    # -- the checkout's series and its exceptions -----------------------------------------------

    def test_a_module_of_another_series_needs_an_exception_before_any_question(self):
        self.workspace.write_text(V1)
        before = self.tree()
        manifest = self.checkout / 'report_xlsx/__manifest__.py'
        self.assert_refused(self.setup_cmd(), (
            f'The module report_xlsx declares Odoo 16.0 (version 16.0.2.0.2 in {manifest}), but {self.checkout} is '
            'an Odoo 15.0 checkout: pass --exception report_xlsx to list it in series_exceptions under '
            '[series."15.0"], or set its version to 15.0.x.y.z if it is an Odoo 15.0 module.'), before)
        self.assert_refused(self.setup_cmd('--exception', 'report xlsx'),
                            'Invalid --exception report xlsx: use a module name.', before)

    def test_the_checkout_file_series_wins_and_existing_exceptions_count(self):
        # A version 2 file whose 19.0 section already lists report_xlsx: the manifests say 15.0 without a flag.
        self.workspace.write_text(V2 + "\n[series.\"19.0\"]\nseries_exceptions = ['report_xlsx']\n")
        result = self.setup_cmd('--community', str(self.source15), '--no-enterprise')
        self.assertEqual(result.returncode, 2)
        self.assertIn('pass --exception report_xlsx', result.stderr)
        (self.checkout / 'report_xlsx/__manifest__.py').write_text("{'name': 'x', 'version': '1.0'}\n")
        (self.checkout / 'cafe_sale/__manifest__.py').write_text("{'name': 'x', 'version': '1.0'}\n")
        (self.checkout / 'oasis-checkout.toml').write_text("odoo_version = '15.0'\n")
        result = self.setup_cmd('--community', str(self.source15), '--no-enterprise')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn(f'series: 15.0 (from {self.checkout / "oasis-checkout.toml"}; {self.workspace} has no '
                      '[series."15.0"] section)\n', result.stdout)
        self.assertNotIn('series_exceptions', result.stdout.split('add [series."15.0"] to ' + str(self.workspace))[1])

    def test_options_that_do_not_apply_are_refused(self):
        self.workspace.write_text(V1)
        before = self.tree()
        for flag in (('--name', 'other'), ('--series', '15.0'), ('--workspace', str(self.project))):
            with self.subTest(flag=flag[0]):
                self.assert_refused(self.setup_cmd(*flag, '--exception', 'report_xlsx'),
                                    f'{flag[0]}: {self.checkout} is already configured by {self.workspace}; setup '
                                    'only fills what is missing.', before)
        # In a checkout of the workspace's own series there is no section to add.
        for flag in (('--exception', 'report_xlsx'), ('--config-dir', str(self.project))):
            with self.subTest(flag=flag[0]):
                self.assert_refused(self.setup_cmd(*flag, root=self.checkout19),
                                    f'{flag[0]}: {self.checkout19} is already configured by {self.workspace}; setup '
                                    'only fills what is missing.', before)

    # -- files setup cannot extend safely -------------------------------------------------------

    def test_a_workspace_file_that_cannot_be_extended_safely_is_refused(self):
        program = 'oasis'
        for text, message in (
                (V1.replace('workspace_version = 1', 'workspace_version = 0x1'),
                 f'Cannot convert {self.workspace} to workspace_version 2: no single line workspace_version = 1; set '
                 f'workspace_version = 2 yourself, then run {program} setup again.'),
                (V1.replace("logs = 'logs'", "logs = 'logs/{series}'"),
                 f'Cannot add [series."15.0"] to {self.workspace}: the change would alter the configuration of Odoo '
                 '19.0 ({series} or a [series] table that version 1 does not read); edit the file yourself.'),
                (V2.replace('[tooling]', "series = { \"19.0\" = { db_service = 'db' } }\n\n[tooling]"),
                 f'Cannot add [series."15.0"] to {self.workspace}: the result is not the same file with that section '
                 'added; edit the file yourself.')):
            with self.subTest(text=text[:40]):
                self.workspace.write_text(text)
                before = self.tree()
                self.assert_refused(self.setup_cmd('--community', str(self.source15), '--no-enterprise',
                                                   '--exception', 'report_xlsx'), message, before)


if __name__ == '__main__':
    unittest.main()
