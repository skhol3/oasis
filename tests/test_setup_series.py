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

    # -- the adopted odoo.conf's data_dir and the folder's logs (L18) ---------------------------

    def adopted_conf(self, data_dir, workspace=V1):
        """config/odoo-15 with its files, its odoo.conf setting data_dir (a password line kept in it)."""
        self.workspace.write_text(workspace)
        self.write_machine(f"[series.\"19.0\"]\ncommunity = '{self.source19}'\n"
                           f"[series.\"15.0\"]\ncommunity = '{self.source15}'\n")
        folder = self.project / 'config/odoo-15'
        self.series_files(folder, 5415, 'corpus-cafe-15')
        with (folder / 'odoo.conf').open('a') as stream:
            stream.write(f'data_dir = {data_dir}\ndb_password = {MARKER}\n')
        return folder

    def test_the_adopted_odoo_conf_data_dir_and_the_folder_logs_are_the_section_ones(self):
        folder = self.adopted_conf(self.project / 'data/odoo-15')
        (self.project / 'logs/odoo-15').mkdir(parents=True)
        before = self.tree()
        result = self.setup_cmd('--exception', 'report_xlsx')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn("  dev_prefix = 'cc15_dev_'\n  test_prefix = 'cc15_test_'\n  logs = 'logs/odoo-15'\n"
                      "  data_dir = 'data/odoo-15'\n  series_exceptions = ['report_xlsx']\n"
                      f'adopt {folder} (found): odoo.conf, compose.yml, .env\n'
                      f'data_dir: {self.project / "data/odoo-15"} (data_dir from {folder / "odoo.conf"})\n'
                      f'logs: {self.project / "logs/odoo-15"} (named for {folder})\n', result.stdout)
        self.assertIn(f'kept {self.project / "logs/odoo-15"}/\ncreate {self.project / "data/odoo-15"}/\n',
                      result.stdout)
        self.assertNotIn('logs/15.0', result.stdout)
        self.assertNotIn('data/15.0', result.stdout)
        self.assertNotIn(MARKER, result.stdout)
        self.assertTrue(result.stdout.endswith(DRY_RUN))
        self.assertEqual(self.tree(), before)
        applied = self.setup_cmd('--apply', '--exception', 'report_xlsx')
        self.assertEqual((applied.returncode, applied.stderr), (0, ''), applied.stdout)
        self.assertNotIn(MARKER, applied.stdout)
        self.assertIn("logs = 'logs/odoo-15'\ndata_dir = 'data/odoo-15'\n", self.workspace.read_text())
        values = self.reader(self.checkout)
        self.assertEqual((values.returncode, values.stderr), (0, ''))
        self.assertIn(f'LOGS_DIR={self.project / "logs/odoo-15"}\n', values.stdout)
        self.assertIn(f'DATA_DIR={self.project / "data/odoo-15"}\n', values.stdout)
        self.assertFalse((self.project / 'data/15.0').exists())
        self.assertFalse((self.project / 'logs/15.0').exists())

    def test_a_relative_or_home_data_dir_is_read_as_odoo_reads_it_and_logs_keep_the_default(self):
        # Odoo makes a relative data_dir absolute from its working directory (setup_cmd runs in the scratch
        # directory) and expands ~; a directory outside the workspace is written absolute.
        for value, expected, written in (
                ('corpus-cafe/data/odoo-15', self.project / 'data/odoo-15', 'data/odoo-15'),
                ('~/filestore15', self.scratch / 'home/filestore15', str(self.scratch / 'home/filestore15'))):
            with self.subTest(value=value):
                folder = self.adopted_conf(value)
                result = self.setup_cmd('--exception', 'report_xlsx')
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertIn(f"  logs = 'logs/15.0'\n  data_dir = '{written}'\n", result.stdout)
                self.assertIn(f'adopt {folder} (found): odoo.conf, compose.yml, .env\n'
                              f'data_dir: {expected} (data_dir from {folder / "odoo.conf"})\nkept ', result.stdout)
                self.assertNotIn('logs: ', result.stdout)
                self.assertIn(f'create {self.project / "logs/15.0"}/\ncreate {expected}/\n', result.stdout)
                self.assertNotIn(MARKER, result.stdout)

    def test_a_data_dir_with_series_in_tooling_is_overridden_unless_it_is_the_same(self):
        folder = self.adopted_conf(self.project / 'data/odoo-15', workspace=V2)
        result = self.setup_cmd('--exception', 'report_xlsx')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn("  test_prefix = 'cc15_test_'\n  data_dir = 'data/odoo-15'\n  series_exceptions", result.stdout)
        self.assertIn(f'data_dir: {self.project / "data/odoo-15"} (data_dir from {folder / "odoo.conf"})\n',
                      result.stdout)
        # The data_dir [tooling] already gives the series is not repeated.
        folder = self.adopted_conf(self.project / 'data/15.0', workspace=V2)
        result = self.setup_cmd('--exception', 'report_xlsx')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn("  test_prefix = 'cc15_test_'\n  series_exceptions", result.stdout)
        self.assertIn(f'data_dir: {self.project / "data/15.0"} (data_dir from {folder / "odoo.conf"})\n',
                      result.stdout)

    def test_an_adopted_odoo_conf_without_data_dir_keeps_the_default_data_dir(self):
        self.workspace.write_text(V1)
        folder = self.project / 'config/odoo-15'
        self.series_files(folder, 5415, 'corpus-cafe-15')
        (self.project / 'data/odoo-15').mkdir(parents=True)
        for conf in ('[options]\ndb_port = 5415\n', '[options]\ndb_port = 5415\ndata_dir =\n'):
            with self.subTest(conf=conf):
                (folder / 'odoo.conf').write_text(conf + f'admin_passwd = {MARKER}\n')
                result = self.setup_cmd('--community', str(self.source15), '--no-enterprise',
                                        '--exception', 'report_xlsx')
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertIn("  logs = 'logs/15.0'\n  data_dir = 'data/15.0'\n", result.stdout)
                self.assertNotIn('data_dir: ', result.stdout)
                self.assertNotIn(MARKER, result.stdout)

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
        for flag in (('--exception', 'report_xlsx'), ('--config-dir', str(self.project)),
                     ('--environment', str(self.project))):
            with self.subTest(flag=flag[0]):
                self.assert_refused(self.setup_cmd(*flag, root=self.checkout19),
                                    f'{flag[0]}: {self.checkout19} is already configured by {self.workspace}; setup '
                                    'only fills what is missing.', before)

    # -- ports another series uses --------------------------------------------------------------

    def test_a_kept_port_that_another_series_uses_is_refused(self):
        # The adopted folder's odoo.conf, compose file or both use the 19.0 series' port: setup never
        # plans a compose file publishing it, nor a section whose series would share it.
        self.workspace.write_text(V1)
        folder = self.project / 'config/odoo-15'
        conf, compose, used = folder / 'odoo.conf', folder / 'compose.yml', self.project / 'config/odoo.conf'
        fixes = {
            'conf': (conf, 'connects to', f'set db_port in {conf} to a port no other series uses'),
            'compose': (compose, 'publishes', f'publish a port no other series uses to 5432 in {compose}'),
            'both': (conf, 'connects to', f'set db_port in {conf} to a port no other series uses and publish the '
                                         f'same port to 5432 in {compose}')}
        for kept, (path, verb, fix) in fixes.items():
            with self.subTest(kept=kept):
                shutil.rmtree(folder, ignore_errors=True)
                self.series_files(folder, self.port19, 'corpus-cafe-15')
                if kept == 'conf':
                    compose.unlink()
                elif kept == 'compose':
                    conf.unlink()
                before = self.tree()
                self.assert_refused(
                    self.setup_cmd(*(('--apply',) if kept == 'both' else ()), '--community', str(self.source15),
                                   '--no-enterprise', '--exception', 'report_xlsx'),
                    f'Port {self.port19} of Odoo 15.0 ({path} {verb} it) is already used by Odoo 19.0 ({used}); two '
                    f'series of a workspace cannot share a PostgreSQL port: {fix}, then run oasis setup again.',
                    before)
        # An odoo.conf without db_port connects to 5432: taken when the 19.0 series uses it.
        shutil.rmtree(folder)
        self.series_files(self.project / 'config', 5432, 'oasis-cc-19')
        folder.mkdir()
        conf.write_text('[options]\ndb_host = 127.0.0.1\n')
        before = self.tree()
        self.assert_refused(
            self.setup_cmd('--community', str(self.source15), '--no-enterprise', '--exception', 'report_xlsx'),
            f'Port 5432 of Odoo 15.0 ({conf} connects to it) is already used by Odoo 19.0 ({used}); two series of a '
            f'workspace cannot share a PostgreSQL port: set db_port in {conf} to a port no other series uses, then '
            'run oasis setup again.', before)

    # -- named environments ---------------------------------------------------------------------

    def named(self, text, path, python):
        return (text.replace(re.search(r"environment = '[^']*'\n", text).group(0), '')
                + f"\n[environments.default]\npath = '{path}'\npython = '{python}'\n")

    def apply_named(self, text):
        """Apply the 15.0 setup to a workspace with named environments; the section written, and the 15.0 and
        19.0 checkouts' values before and after."""
        self.workspace.write_text(text)
        before19 = self.reader(self.checkout19)
        self.assertEqual((before19.returncode, before19.stderr), (0, ''))
        result = self.setup_cmd('--apply', '--community', str(self.source15), '--no-enterprise',
                                '--exception', 'report_xlsx')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        section = self.workspace.read_text()[len(text):]
        values, after19 = self.reader(self.checkout), self.reader(self.checkout19)
        self.assertEqual((values.returncode, values.stderr, after19.returncode, after19.stderr), (0, '', 0, ''))
        tail = '' if 'workspace_version = 2' in text else "WORKSPACE_VERSION=2\nSERIES_EXCEPTIONS=''\n"
        self.assertEqual(after19.stdout, before19.stdout + tail)
        return result.stdout, section, values.stdout

    def test_named_environments_whose_path_uses_series_give_the_series_its_own_environment(self):
        stdout, section, values = self.apply_named(self.named(V2, 'environments/cc-{series}', '3.12'))
        environment = self.project / 'environments/cc-15.0'
        self.assertNotIn('environment', section.split('[series."15.0"]')[1])
        self.assertIn(f'create the environment {environment} with Python 3.12 (uv venv)', stdout)
        for line in (f'PROJECT_ENVIRONMENT={environment}', 'ENVIRONMENT_NAME=default', 'PYTHON_VERSION=3.12',
                     'DEV_PREFIX=cc15_dev_'):
            self.assertIn(line + '\n', values)

    def test_named_environments_of_a_version_1_file_give_the_series_an_environment_next_to_the_default(self):
        stdout, section, values = self.apply_named(self.named(V1, 'environments/cc', '3.12'))
        environment = self.project / 'environments/cc-15.0'
        self.assertIn("[series.\"15.0\"]\nenvironment = 'environments/cc-15.0'\n", section)
        self.assertIn(f'create the environment {environment} with Python {PYTHON_15} (uv venv)', stdout)
        for line in (f'PROJECT_ENVIRONMENT={environment}', "ENVIRONMENT_NAME=''", f'PYTHON_VERSION={PYTHON_15}'):
            self.assertIn(line + '\n', values)

    def test_a_named_environment_whose_python_the_series_does_not_support_gives_the_series_its_own(self):
        # 3.13 is a 19.0 Python but not a 15.0 one: the section sets the 15.0 path, with the 15.0 default.
        stdout, section, values = self.apply_named(self.named(V2, 'environments/cc-{series}', '3.13'))
        environment = self.project / 'environments/cc-15.0'
        self.assertIn("[series.\"15.0\"]\nenvironment = 'environments/cc-15.0'\n", section)
        self.assertIn(f'create the environment {environment} with Python {PYTHON_15} (uv venv)', stdout)
        for line in (f'PROJECT_ENVIRONMENT={environment}', "ENVIRONMENT_NAME=''", f'PYTHON_VERSION={PYTHON_15}'):
            self.assertIn(line + '\n', values)

    def test_an_unsupported_named_python_with_machine_environments_places_the_series_environment_there(self):
        self.workspace.write_text(self.named(V2, 'environments/cc-{series}', '3.13'))
        self.write_machine(f"[series.\"19.0\"]\ncommunity = '{self.source19}'\n"
                           f"[series.\"15.0\"]\ncommunity = '{self.source15}'\nenvironments = '/srv/envs15'\n")
        result = self.setup_cmd('--exception', 'report_xlsx')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn("  [series.\"15.0\"]\n  environment = '/srv/envs15/cc15'\n", result.stdout)
        self.assertIn(f'create the environment /srv/envs15/cc15 with Python {PYTHON_15} (uv venv)', result.stdout)

    # -- a failure after the workspace edit -----------------------------------------------------

    def assert_undone(self, result, stderr, before):
        self.assertEqual((result.returncode, result.stderr), (2, stderr), result.stdout)
        self.assertIn(f'add [series."15.0"] to {self.workspace}:\n', result.stdout)
        self.assertNotIn('next steps', result.stdout)
        # The workspace and machine files' bytes and modes, and nothing created is left.
        self.assertEqual(self.tree(), before)

    def test_a_failed_verification_after_the_workspace_edit_undoes_every_change(self):
        # The 19.0 logs directory holds the 15.0 environment's path: creating the 15.0 logs creates it, which
        # the plan cannot see and the verification refuses.
        self.workspace.write_text(V1.replace("logs = 'logs'", "logs = 'environments/cc-15.0/logs'"))
        self.workspace.chmod(0o640)
        environment = self.project / 'environments/cc-15.0'
        before = self.tree()
        result = self.setup_cmd('--apply', '--community', str(self.source15), '--no-enterprise',
                                '--exception', 'report_xlsx')
        self.assertEqual((result.returncode, result.stderr), (1, (
            f'ERROR: Verification failed (Unsafe tooling environment target: {environment} exists and is not a '
            'Python environment (no pyvenv.cfg).); every change was undone.\n')), result.stdout)
        self.assertIn(f'add [series."15.0"] to {self.machine}:\n', result.stdout)
        self.assertNotIn('verified:', result.stdout)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.workspace.stat().st_mode & 0o777, 0o640)
        self.assertFalse(self.log.exists())

    def test_a_failed_compile_after_the_workspace_edit_undoes_every_change(self):
        self.workspace.write_text(V1)
        self.workspace.chmod(0o640)
        requirements = self.project / 'config/15.0/requirements'
        before = self.tree()
        self.env['FAKE_COMPILE_FAIL'] = '1'
        result = self.setup_cmd('--apply', '--community', str(self.source15), '--no-enterprise',
                                '--exception', 'report_xlsx')
        self.assert_undone(result, (
            'error: No solution found\nuv pip compile of runtime.in failed (exit 1); lock.sha256 was left as it was.\n'
            f'Fix {requirements / "runtime.in"} or its access to the package index, then run oasis setup --apply '
            'again.\nERROR: uv pip compile failed; every change was undone.\n'), before)
        self.assertIn(f'verified: {self.checkout} loads its configuration from {self.workspace}\n', result.stdout)
        # Run again without the failure: the same plan applies.
        del self.env['FAKE_COMPILE_FAIL']
        again = self.setup_cmd('--apply', '--community', str(self.source15), '--no-enterprise',
                               '--exception', 'report_xlsx')
        self.assertEqual((again.returncode, again.stderr), (0, ''), again.stdout)
        self.assertEqual(self.workspace.read_text(),
                         V1.replace('workspace_version = 1', 'workspace_version = 2') + '\n' + SECTION)

    def test_a_failed_uv_venv_after_the_workspace_edit_undoes_every_change_and_restores_the_locks(self):
        # An adopted folder with stale locks: the compile rewrites them before uv venv fails.
        self.workspace.write_text(V1)
        folder = self.project / 'config/odoo-15'
        self.series_files(folder, 5415, 'corpus-cafe-15', requirements=True)
        (folder / 'requirements/runtime.in').write_text('# runtime.in, changed\n')
        (folder / 'requirements/runtime.txt').chmod(0o600)
        before = self.tree()
        self.env['FAKE_VENV_FAIL'] = '1'
        result = self.setup_cmd('--apply', '--community', str(self.source15), '--no-enterprise',
                                '--exception', 'report_xlsx')
        self.assert_undone(result, (
            'error: no interpreter\nERROR: uv venv failed (exit 3); every change was undone: fix it, then run oasis '
            'setup --apply again.\n'), before)
        self.assertIn(f'compiled {folder / "requirements"}/runtime.txt, dev.txt and lock.sha256\n', result.stdout)
        self.assertFalse((self.project / 'environments').exists())

    # -- an adopted environment and the project's requirement files (S7) ------------------------

    def existing_environment(self, path, cfg):
        """An environment that setup may adopt: its pyvenv.cfg, and a bin/python that leaves a mark when run."""
        (path / 'bin').mkdir(parents=True)
        (path / 'pyvenv.cfg').write_text(cfg)
        (path / 'bin/python').write_text(f'#!/bin/sh\ntouch {self.scratch / "python-ran"}\n')
        (path / 'bin/python').chmod(0o755)
        (path / 'lib/site-packages').mkdir(parents=True)
        (path / 'lib/site-packages/cryptography.py').write_text('# installed\n')
        return path

    def billing_o15(self):
        """The corpus-cafe case (L14): config/odoo-15 with the project's requirement files, and billing-o15."""
        self.workspace.write_text(V1)
        self.write_machine(f"[series.\"19.0\"]\ncommunity = '{self.source19}'\n"
                           f"[series.\"15.0\"]\ncommunity = '{self.source15}'\n")
        folder = self.project / 'config/odoo-15'
        self.series_files(folder, 5415, 'corpus-cafe-15')
        (folder / 'requirements-extra.txt').write_text('xmlsig==0.1.2\n')
        (folder / 'requirements-overrides.txt').write_text('cryptography==3.4.8\npyopenssl==21.0.0\n'
                                                           'python-ldap==3.4.4\n')
        environment = self.existing_environment(self.scratch / 'environments/billing-o15',
                                                'home = /usr/bin\nimplementation = CPython\nversion = 3.8.20\n')
        return folder, environment

    def test_an_adopted_environment_and_the_project_requirement_files_set_up_the_series_locks(self):
        folder, environment = self.billing_o15()
        requirements = folder / 'requirements'
        held = {path: data for path, data in self.tree().items()
                if path.startswith(('corpus-cafe/config/odoo-15', 'environments'))}
        section = SECTION_COMMENT + f'''
[series."15.0"]
environment = '{environment}'
python = '3.8'
config = 'config/odoo-15/odoo.conf'
env_file = 'config/odoo-15/.env'
compose = 'config/odoo-15/compose.yml'
requirements = 'config/odoo-15/requirements'
dev_prefix = 'cc15_dev_'
test_prefix = 'cc15_test_'
logs = 'logs/15.0'
data_dir = 'data/15.0'
series_exceptions = ['report_xlsx']
'''
        plan = '\n'.join([
            f'checkout: {self.checkout} (main)', f'workspace: {self.workspace} (existing)',
            f'series: 15.0 (from the module manifests; {self.workspace} has no [series."15.0"] section)',
            f'community: {self.source15} (from the machine file)', 'enterprise: none (from the machine file)',
            f'kept {self.machine}: [series."15.0"] gives the Odoo source',
            f'change workspace_version = 1 to workspace_version = 2 in {self.workspace} (that line only)',
            f'add [series."15.0"] to {self.workspace}:', *self.indented(section),
            f'adopt {folder} (found): odoo.conf, compose.yml, .env, requirements-extra.txt, '
            'requirements-overrides.txt',
            f'kept {folder / "odoo.conf"}', f'kept {folder / "compose.yml"}', f'kept {folder / ".env"}',
            f'create {requirements / "runtime.in"}: -r {self.source15}/requirements.txt, -r ../requirements-extra.txt',
            f'create {requirements / "dev.in"}: -c runtime.txt, -r runtime.in',
            f'create {requirements / "overrides.txt"}: -r ../requirements-overrides.txt (uv pip compile --override)',
            f'create {self.project / "logs/15.0"}/', f'create {self.project / "data/15.0"}/',
            f'compile {requirements}/runtime.txt, dev.txt and lock.sha256 with Python 3.8 (uv pip compile)',
            f'adopt the environment {environment} (from --environment): Python 3.8 (its pyvenv.cfg); setup never '
            'creates, syncs or deletes it']) + '\n'
        before = self.tree()
        result = self.setup_cmd('--environment', str(environment), '--exception', 'report_xlsx')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, plan + DRY_RUN, ''))
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.log.exists())
        applied = self.setup_cmd('--apply', '--environment', str(environment), '--exception', 'report_xlsx')
        self.assertEqual((applied.returncode, applied.stderr), (0, ''), applied.stdout)
        self.assertEqual(applied.stdout, plan + '\n'.join([
            f'verified: {self.checkout} loads its configuration from {self.workspace}',
            f'compiled {requirements}/runtime.txt, dev.txt and lock.sha256',
            'next steps:',
            f'  1. the locks in {requirements} describe runtime.in, dev.in and overrides.txt: oasis --project '
            f'{self.checkout} bootstrap --apply syncs the adopted environment {environment} to them (it changes '
            'the packages installed there)',
            f'  2. docker compose --env-file {folder / ".env"} -f {folder / "compose.yml"} up -d --wait',
            f'  3. oasis --project {self.checkout} doctor',
            f'  4. add a [development] table with administrator_login to {self.workspace} (docs/dev-database.md)',
            f'  5. oasis --project {self.checkout} init-dev-database <module> cc15_dev_manual']) + '\n')
        self.assertEqual(self.workspace.read_text(),
                         V1.replace('workspace_version = 1', 'workspace_version = 2') + '\n' + section)
        # Both compiles with the overrides, with the environment's Python; no uv venv, no uv pip sync.
        self.assertEqual(self.log.read_text().splitlines(), [
            f'uv pip compile --python-version 3.8 --override overrides.txt runtime.in -o runtime.txt (in {requirements})',
            f'uv pip compile --python-version 3.8 --override overrides.txt dev.in -o dev.txt (in {requirements})'])
        self.assertEqual((requirements / 'runtime.in').read_text(), (
            '# Written by oasis setup: the requirements of the Odoo source.\n'
            f'-r {self.source15}/requirements.txt\n'
            "# The project's own requirements (oasis setup found them in the series folder).\n"
            '-r ../requirements-extra.txt\n'))
        self.assertEqual((requirements / 'overrides.txt').read_text(), (
            "# Written by oasis setup: the project's pins that replace Odoo's, given to uv pip compile as "
            '--override for runtime.txt and dev.txt.\n-r ../requirements-overrides.txt\n'))
        self.assertEqual((requirements / 'lock.sha256').read_text(), ''.join(
            f'{hashlib.sha256((requirements / name).read_bytes()).hexdigest()}  {name}\n'
            for name in ('runtime.in', 'runtime.txt', 'dev.in', 'dev.txt', 'overrides.txt')))
        # The project's files and the environment are as they were; its Python never ran.
        self.assertEqual({path: data for path, data in self.tree().items()
                          if path.startswith(('corpus-cafe/config/odoo-15', 'environments'))
                          and not path.startswith('corpus-cafe/config/odoo-15/requirements/')
                          and path != 'corpus-cafe/config/odoo-15/requirements'}, held)
        self.assertFalse((self.scratch / 'python-ran').exists())
        values = self.reader(self.checkout)
        self.assertEqual((values.returncode, values.stderr), (0, ''))
        for line in (f'PROJECT_ENVIRONMENT={environment}', 'PYTHON_VERSION=3.8', f'REQUIREMENTS_DIR={requirements}'):
            self.assertIn(line + '\n', values.stdout)
        # A second run keeps everything; --environment is then an option that does not apply.
        before = self.tree()
        self.log.unlink()
        again = self.setup_cmd('--apply')
        self.assertEqual((again.returncode, again.stderr), (0, ''))
        self.assertIn(f'kept {requirements / "overrides.txt"}\n', again.stdout)
        self.assertTrue(again.stdout.endswith(f'kept the locks in {requirements}: current\n'
                                              f'kept the environment {environment}\n'
                                              f'nothing to set up: run oasis --project {self.checkout} doctor\n'),
                        again.stdout)
        self.assert_refused(self.setup_cmd('--environment', str(environment)),
                            f'--environment: {self.checkout} is already configured by {self.workspace}; setup only '
                            'fills what is missing.', before)

    def test_the_documented_billing_o15_example_plans_the_documented_lines(self):
        _folder, environment = self.billing_o15()
        docs = (ROOT / 'docs/setup.md').read_text()
        start = docs.index('# corpus-cafe/oasis-workspace.toml before, example only.\n')
        self.workspace.write_text(docs[start:docs.index('```', start)])
        command = docs.index('--environment <environments>/billing-o15 --apply\n')
        start = docs.index('add [series."15.0"] to <corpus-cafe>/oasis-workspace.toml:\n', command)
        documented = docs[start:docs.index('```', start)].replace('<corpus-cafe>', str(self.project)).replace(
            '<15.0 source>', str(self.source15)).replace('<environments>', str(environment.parent))
        result = self.setup_cmd('--exception', 'report_xlsx', '--environment', str(environment))
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.endswith(documented + DRY_RUN), result.stdout)

    def test_an_environment_under_the_workspace_is_written_relative_and_its_default_python_is_not(self):
        self.workspace.write_text(V1)
        environment = self.existing_environment(self.project / 'environments/cc15-own',
                                                'home = /usr/bin\nuv = 0.13.10\nversion_info = 3.10.12\n')
        before = self.tree()
        result = self.setup_cmd('--environment', str(environment), '--community', str(self.source15),
                                '--no-enterprise', '--exception', 'report_xlsx')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn("  [series.\"15.0\"]\n  environment = 'environments/cc15-own'\n  config = 'config/15.0/odoo.conf'\n",
                      result.stdout)
        # Without the project's requirement files: runtime.in from Odoo's only, no overrides.txt.
        self.assertIn(f'create {self.project / "config/15.0/requirements/runtime.in"}: -r '
                      f'{self.source15}/requirements.txt\n', result.stdout)
        self.assertNotIn('overrides', result.stdout)
        self.assertTrue(result.stdout.endswith(
            f'adopt the environment {environment} (from --environment): Python {PYTHON_15} (its pyvenv.cfg); setup '
            'never creates, syncs or deletes it\n' + DRY_RUN), result.stdout)
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.log.exists())

    def test_an_environment_setup_cannot_adopt_is_refused(self):
        self.workspace.write_text(V1)
        before = self.tree()
        self.assert_refused(self.setup_cmd('--environment', 'environments/billing-o15'),
                            '--environment requires an absolute existing directory.', before)
        plain = self.scratch / 'plain'
        plain.mkdir()
        before = self.tree()
        self.assert_refused(self.setup_cmd('--environment', str(plain), '--exception', 'report_xlsx'),
                            f'--environment {plain} is not a Python environment (no pyvenv.cfg).', before)
        low, high = table().capability('15.0', 'python')
        for name, cfg, message in (
                ('unknown', 'home = /usr/bin\n', 'has no Python version in its pyvenv.cfg (version or version_info)'),
                ('old', 'version = 3.6.15\n', f'has Python 3.6, which Odoo 15.0 does not support ({low} to {high})'),
                ('new', 'version_info = 3.13.1\n',
                 f'has Python 3.13, which Odoo 15.0 does not support ({low} to {high})')):
            with self.subTest(name=name):
                environment = self.existing_environment(self.scratch / name, cfg)
                before = self.tree()
                self.assert_refused(self.setup_cmd('--environment', str(environment), '--community',
                                                   str(self.source15), '--no-enterprise', '--exception', 'report_xlsx'),
                                    f'--environment {environment} {message}.', before)
        self.assertFalse((self.scratch / 'python-ran').exists())

    def test_a_failed_compile_with_an_adopted_environment_undoes_every_change_and_leaves_it_alone(self):
        _folder, environment = self.billing_o15()
        before = self.tree()
        self.env['FAKE_COMPILE_FAIL'] = '1'
        result = self.setup_cmd('--apply', '--environment', str(environment), '--exception', 'report_xlsx')
        self.assertEqual((result.returncode, result.stderr.splitlines()[-1]),
                         (2, 'ERROR: uv pip compile failed; every change was undone.'), result.stdout)
        self.assertEqual(self.tree(), before)
        self.assertFalse((self.scratch / 'python-ran').exists())

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
