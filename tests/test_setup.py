"""`oasis setup [--apply]` on synthetic checkouts (v0.14.0 S1, S6, S7, S9, S10; L12).

Every directory lives in a fresh system temp directory: git runs with an empty configuration and a
ceiling at the scratch directory, the machine file is looked for under a scratch XDG_CONFIG_HOME
(HOME is scratch too), and uv is a fake that records its calls, so nothing reads or writes a real
project, the real ~/.config or a package index.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'oasis'
READER = ROOT / 'tools' / 'config.py'
GIT = ['git', '-c', 'user.name=oasis tests', '-c', 'user.email=tests@example.invalid',
       '-c', 'init.defaultBranch=main', '-c', 'commit.gpgsign=false']
RELEASE = "version_info = (19, 0, 0, 'final', 0, '')\n"
MANIFEST = "{'name': 'Shop Sale', 'version': '19.0.1.0.0', 'depends': ['sale']}\n"
MARKER = 'setup-must-not-print-this'
# A fake uv: records `uv <args> (in <cwd>)`, writes the lock `pip compile ... -o <lock>` names, and
# makes `venv --python <v> <target>` an environment (pyvenv.cfg and bin/python). FAKE_COMPILE_FAIL,
# FAKE_VENV_FAIL (exit 3) and FAKE_SYNC_FAIL (exit 4) make that step fail; FAKE_SYNC_BREAK=<file> makes
# `pip sync` overwrite that file with invalid TOML (a file broken after the verification). `uv --version`
# (tools/locks.py uv_version, v0.16.0 S3) prints a version before 0.13 and is not recorded.
UV = '''#!/bin/sh
if [ "$1" = --version ]; then echo 'uv 0.9.0 (fake)'; exit 0; fi
printf 'uv %s (in %s)\\n' "$*" "$PWD" >> "$FAKE_LOG"
case "$1 $2" in
  'pip compile')
    prev= output=
    for arg; do
      if [ "$prev" = -o ]; then output=$arg; fi
      prev=$arg
    done
    if [ -n "${FAKE_COMPILE_FAIL:-}" ]; then echo 'error: No solution found' >&2; exit 1; fi
    printf '# fake lock\\n' > "$output" ;;
  'venv --python')
    if [ -n "${FAKE_VENV_FAIL:-}" ]; then echo 'error: no interpreter' >&2; exit 3; fi
    mkdir -p "$4/bin"
    echo 'home = /usr/bin' > "$4/pyvenv.cfg"
    printf '#!/bin/sh\\necho 3.12\\n' > "$4/bin/python"
    chmod +x "$4/bin/python" ;;
  'pip sync')
    if [ -n "${FAKE_SYNC_BREAK:-}" ]; then printf 'broken = [\n' > "$FAKE_SYNC_BREAK"; fi
    if [ -n "${FAKE_SYNC_FAIL:-}" ]; then echo 'error: no index' >&2; exit 4; fi ;;
esac
exit 0
'''
# The [development] table of a new workspace (v0.16.0 S6: the question development, recommended add), and the
# step that names its lines when a workspace has none.
DEVELOPMENT = ("\n# The administrator of the databases init-dev-database creates; its password is generated "
               "(docs/dev-database.md).\n[development]\nadministrator_login = 'admin'\n")
ADD_DEVELOPMENT = ("add these lines to {workspace} (docs/dev-database.md):\n       [development]\n"
                   "       administrator_login = 'admin'")
WORKSPACE = '''# Written by oasis setup. Paths are relative to this file, addons_paths to each checkout;
# the Odoo source comes from the machine file (docs/workspace-file.md#machine-file).
workspace_version = 1
odoo_version = '19.0'

[tooling]
environment = '{base}venv'
config = '{base}config/odoo.conf'
env_file = '{base}config/.env'
compose = '{base}config/compose.yml'
requirements = '{base}config/requirements'
addons_paths = ['.']
db_service = 'db'
dev_prefix = 'shop_dev_'
test_prefix = 'shop_test_'
logs = '{base}logs'
data_dir = '{base}data'
''' + DEVELOPMENT
MACHINE_HEADER = ('# Written by oasis setup: the Odoo source of each series on this machine '
                  '(docs/workspace-file.md#machine-file).\n')
# v0.16.0 S2: the account is generated (tests/test_credentials.py); the password is random.
ENV_FILE = re.compile(r'# Written by oasis setup: the PostgreSQL account of the compose service and of Odoo '
                      r'\(docs/setup\.md#the-database-account\)\.\n# No oasis command needs it read, copied or '
                      r'typed\. Never commit this file\.\nODOO_DB_USER=oasis_shop\nODOO_DB_PASSWORD=[A-Za-z0-9_-]{32}\n')
DRY_RUN = 'dry run: nothing changed; run with --apply to set up\n'
# The section setup adds for the modules of another series (v0.16.0 S4).
SECTION = ('# Added by oasis setup: what differs for the Odoo 19.0 checkouts (docs/setup.md#another-odoo-series).\n'
           '[series."19.0"]\nseries_exceptions = [{modules}]\n')
OPEN_PLAN = ('nothing changed: answer the open questions above (docs/setup.md#questions-and-answers), then run '
             'with --apply to set up\n')
# The recommended answers of the environment questions (v0.20.0 S1), as an agent relays them.
CREATE = ('--answer', 'environment=create', '--answer', 'python=3.12')
NOT_TTY_SERIES = ('ERROR: Cannot infer the Odoo series of {root}: no module manifest declares one and the '
                  'machine file has no single series; pass --series <x.y> (supported: 19.0, 15.0).\n')


@unittest.skipUnless(shutil.which('git'), 'git is required')
class SetupTests(unittest.TestCase):
    def setUp(self):
        previous = os.umask(0o022)
        self.addCleanup(os.umask, previous)
        self.scratch = Path(tempfile.mkdtemp(prefix='oasis-setup-')).resolve()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.bindir = self.scratch / 'bin'
        self.bindir.mkdir()
        (self.bindir / 'uv').write_text(UV)
        (self.bindir / 'uv').chmod(0o755)
        self.log = self.scratch / 'uv.log'
        (self.scratch / 'home').mkdir()
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        self.env.update({'GIT_CEILING_DIRECTORIES': str(self.scratch), 'GIT_CONFIG_GLOBAL': os.devnull,
                         'GIT_CONFIG_NOSYSTEM': '1', 'PYTHONDONTWRITEBYTECODE': '1',
                         'XDG_CONFIG_HOME': str(self.scratch / 'xdg'), 'HOME': str(self.scratch / 'home'),
                         'FAKE_LOG': str(self.log), 'PATH': f'{self.bindir}:{os.environ["PATH"]}'})
        self.machine = self.scratch / 'xdg' / 'oasis' / 'config.toml'
        self.source = self.odoo_source(self.scratch / 'sources' / 'community')
        self.checkout = self.scratch / 'work' / 'shop'
        self.module('shop_sale', MANIFEST)
        self.git(self.checkout, 'init', '-q')
        self.git(self.checkout, 'add', '.')
        self.git(self.checkout, 'commit', '-q', '-m', 'init')

    # -- fixture --------------------------------------------------------------------------------

    def git(self, cwd, *args):
        return subprocess.run([*GIT, '-C', str(cwd), *args], check=True, capture_output=True,
                              text=True, env=self.env).stdout.strip()

    def odoo_source(self, path):
        (path / 'odoo').mkdir(parents=True)
        (path / 'odoo' / 'release.py').write_text(RELEASE)
        (path / 'requirements.txt').write_text('psycopg2\n')
        return path

    def module(self, name, manifest):
        (self.checkout / name).mkdir(parents=True, exist_ok=True)
        (self.checkout / name / '__manifest__.py').write_text(manifest)

    def setup_cmd(self, *args, project=True, **kwargs):
        prefix = ['--project', str(self.checkout)] if project else []
        return subprocess.run([sys.executable, '-B', str(CLI), *prefix, 'setup', *args], capture_output=True,
                              text=True, env=self.env, stdin=subprocess.DEVNULL, cwd=kwargs.get('cwd', self.scratch))

    def tree(self):
        """Every path below the scratch directory but the fake uv's log, with its mode and content."""
        found = {}
        for path in sorted(self.scratch.rglob('*')):
            if path == self.log:
                continue
            info = path.lstat()
            found[str(path.relative_to(self.scratch))] = (
                info.st_mode, path.read_bytes() if path.is_file() and not path.is_symlink() else None)
        return found

    def write_machine(self, text):
        self.machine.parent.mkdir(parents=True, mode=0o700)
        self.machine.write_text(text)
        self.machine.chmod(0o600)

    def compose_name(self, directory=None):
        return 'oasis-shop-' + hashlib.sha256(str(directory or self.checkout).encode()).hexdigest()[:6]

    def plan(self, port, base='.oasis/', directory=None, machine='create', environment=None, enterprise='none'):
        """The plan of a new workspace in directory (default: the checkout) for the fixture."""
        directory = directory or self.checkout
        prefix = directory / base
        config = prefix / 'config'
        environment = environment or (prefix / 'venv')
        lines = [f'checkout: {self.checkout} (main)', 'series: 19.0 (from the module manifests)',
                 f'community: {self.source} (from --community)', f'enterprise: {enterprise} (from --no-enterprise)',
                 f'workspace: {directory} (new)']
        if machine == 'create':
            lines += [f'create {self.machine} (mode 0600):', '  ' + MACHINE_HEADER.rstrip('\n'),
                      '  [series."19.0"]', f"  community = '{self.source}'"]
        lines += [f'create {directory / "oasis-workspace.toml"} (mode 0600):']
        lines += [f'  {line}' if line else '' for line in WORKSPACE.format(base=base).splitlines()]
        if directory == self.checkout:
            lines.append(f'exclude /oasis-workspace.toml and /.oasis/ in {self.checkout / ".git/info/exclude"} '
                         '(this clone only; .gitignore unchanged)')
        lines += [
            f'create {config / "odoo.conf"} (mode 0600): path-free; db_port {port}; db_user and db_password empty',
            f'create {config / "compose.yml"}: PostgreSQL 17 (postgres:17) as service db on 127.0.0.1:{port}, '
            f'compose project {self.compose_name(directory)}',
            f'create {config / ".env"} (mode 0600): ODOO_DB_USER oasis_shop and a generated ODOO_DB_PASSWORD',
            f'create {config / "requirements/runtime.in"}: -r {self.source}/requirements.txt',
            f'create {config / "requirements/dev.in"}: -c runtime.txt, -r runtime.in',
            f'create {prefix / "logs"}/', f'create {prefix / "data"}/',
            f'compile {config / "requirements"}/runtime.txt, dev.txt and lock.sha256 with Python 3.12 '
            '(uv pip compile)',
            f'create the environment {environment} with Python 3.12 (uv venv) and sync dev.txt (uv pip sync)']
        return '\n'.join(lines) + '\n'

    def port_of(self, stdout):
        match = re.search(r'db_port (\d+);', stdout)
        self.assertIsNotNone(match, stdout)
        return int(match.group(1))

    def assert_refused(self, result, message, before):
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', f'ERROR: {message}\n'))
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.log.exists())

    # -- plan -----------------------------------------------------------------------------------

    def test_the_default_prints_the_plan_of_a_new_workspace_and_changes_nothing(self):
        before = self.tree()
        result = self.setup_cmd('--community', str(self.source), '--no-enterprise', *CREATE)
        port = self.port_of(result.stdout)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, self.plan(port) + DRY_RUN, ''))
        self.assertTrue(5432 <= port < 5532)
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.log.exists())
        # --plan asks for the same plan explicitly; without --project the checkout is the git top level.
        explicit = self.setup_cmd('--plan', '--community', str(self.source), '--no-enterprise', *CREATE,
                                  project=False,
                                  cwd=self.checkout / 'shop_sale')
        self.assertEqual((explicit.returncode, explicit.stderr), (0, ''))
        self.assertEqual(re.sub(r'\b\d{4}\b', 'P', explicit.stdout), re.sub(r'\b\d{4}\b', 'P', result.stdout))
        self.assertEqual(self.tree(), before)

    def test_usage_errors_change_nothing(self):
        before = self.tree()
        usage = (f'Usage: {CLI} setup [--series <x.y>] [--community <dir>] [--enterprise <dir> | --no-enterprise] '
                 '[--workspace <dir>] [--name <name>] [--exception <module>]... [--config-dir <dir>] '
                 '[--environment <dir> | --python <x.y>] [--answer <id>=<value>]... [--answers <file.json>] '
                 '[--apply | --plan [--json]]\n')
        for args in (('--apply', '--plan'), ('--plan', '--apply'), ('--enterprise', '/x', '--no-enterprise'),
                     ('--app',), ('--community',), ('--apply', '--apply'), ('extra',), ('--',), ('--a',),
                     ('--apply=x',), ('--apply=',), ('--appl',),
                     ('--exception',), ('--config-dir', '/x', '--config-dir', '/y')):
            with self.subTest(args=args):
                result = self.setup_cmd(*args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', usage))
        result = self.setup_cmd('--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(usage))
        self.assertNotIn('Odoo 19', result.stdout)
        self.assertEqual(self.tree(), before)

    # -- apply ----------------------------------------------------------------------------------

    def test_apply_creates_the_missing_pieces_and_a_second_run_keeps_them(self):
        result = self.setup_cmd('--apply', '--community', str(self.source), '--no-enterprise', *CREATE)
        port = self.port_of(result.stdout)
        config = self.checkout / '.oasis/config'
        requirements = config / 'requirements'
        environment = self.checkout / '.oasis/venv'
        workspace = self.checkout / 'oasis-workspace.toml'
        steps = (f'verified: {self.checkout} loads its configuration from {workspace}\n'
                 f'compiled {requirements}/runtime.txt, dev.txt and lock.sha256\n'
                 f'created the environment {environment}\n'
                 'next steps:\n'
                 f'  1. oasis --project {self.checkout} start-database\n'
                 f'  2. oasis --project {self.checkout} doctor\n'
                 f'  3. oasis --project {self.checkout} init-dev-database --plan\n')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, self.plan(port) + steps, ''))
        # S10: the source goes to the machine file (0600), not to the workspace file.
        self.assertEqual(self.machine.read_text(), MACHINE_HEADER + f"[series.\"19.0\"]\ncommunity = '{self.source}'\n")
        self.assertEqual(self.machine.stat().st_mode & 0o777, 0o600)
        self.assertEqual(workspace.read_text(), WORKSPACE.format(base='.oasis/'))
        self.assertEqual(workspace.stat().st_mode & 0o777, 0o600)
        # v0.16.0 S2: the generated account, 0600.
        self.assertRegex((config / '.env').read_text(), ENV_FILE)
        self.assertEqual((config / '.env').stat().st_mode & 0o777, 0o600)
        conf = (config / 'odoo.conf').read_text()
        self.assertEqual(conf.split('[options]\n')[1],
                         f'db_host = 127.0.0.1\ndb_port = {port}\ndb_user =\ndb_password =\n')
        self.assertNotIn('addons_path', conf.split('[options]')[1])
        self.assertNotIn('data_dir', conf.split('[options]')[1])
        self.assertEqual((config / 'odoo.conf').stat().st_mode & 0o777, 0o600)
        compose = (config / 'compose.yml').read_text()
        for line in (f'name: {self.compose_name()}\n', '    image: postgres:17\n',
                     f"      - '127.0.0.1:{port}:5432'\n", '      POSTGRES_USER: ${ODOO_DB_USER}\n',
                     '      ODOO_DB_PASSWORD: ${ODOO_DB_PASSWORD}\n', '      POSTGRES_DB: postgres\n'):
            self.assertIn(line, compose)
        # 19.0 needs nothing besides the source's requirements (v0.15.0 S9: only 15.0 adds setuptools<81).
        self.assertEqual((requirements / 'runtime.in').read_text(), '# Written by oasis setup: the requirements of the '
                         f'Odoo source.\n-r {self.source}/requirements.txt\n')
        # v0.18.0: HttpCase tours need websocket-client (Odoo skips them without it and the run passes).
        self.assertEqual((requirements / 'dev.in').read_text().splitlines()[1:], [
            '-c runtime.txt', '-r runtime.in',
            '# HttpCase browser tests (tours) need it: without it Odoo skips them and the run still passes.',
            'websocket-client'])
        self.assertTrue((self.checkout / '.oasis/logs').is_dir() and (self.checkout / '.oasis/data').is_dir())
        # S9: the locks through the code bootstrap uses, then the environment.
        self.assertEqual(self.log.read_text().splitlines(), [
            f'uv pip compile --python-version 3.12 runtime.in -o runtime.txt (in {requirements})',
            f'uv pip compile --python-version 3.12 dev.in -o dev.txt (in {requirements})',
            f'uv venv --python 3.12 {environment} (in {self.scratch})',
            f'uv pip sync --python {environment}/bin/python {requirements}/dev.txt (in {self.scratch})'])
        check = subprocess.run(['sha256sum', '--check', '--strict', 'lock.sha256'], cwd=requirements,
                               capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        # git: the new files are excluded locally, never through the tracked .gitignore.
        self.assertEqual(self.git(self.checkout, 'status', '--porcelain', '--untracked-files=all'), '')
        self.assertFalse((self.checkout / '.gitignore').exists())
        exclude = (self.checkout / '.git/info/exclude').read_text()
        self.assertTrue(exclude.endswith('/oasis-workspace.toml\n/.oasis/\n'), exclude)
        # The checkout now loads, with the source from the machine file.
        values = subprocess.run([sys.executable, '-B', str(READER), str(self.checkout)], capture_output=True,
                                text=True, env=self.env)
        self.assertEqual((values.returncode, values.stderr), (0, ''))
        self.assertIn(f'ODOO_SOURCE={self.source}\n', values.stdout)
        self.assertIn(f"ADDON_ROOTS={self.checkout}\n", values.stdout)
        # A second run adopts everything: kept, nothing to set up, nothing changed.
        before = self.tree()
        self.log.unlink()
        again = self.setup_cmd('--apply')
        self.assertEqual((again.returncode, again.stderr), (0, ''))
        self.assertEqual(again.stdout, '\n'.join([
            f'checkout: {self.checkout} (main)', f'workspace: {workspace} (existing)',
            f'kept {self.machine}: [series."19.0"] gives the Odoo source',
            f'kept {config / "odoo.conf"}', f'kept {config / "compose.yml"}', f'kept {config / ".env"}',
            f'kept {requirements / "runtime.in"}', f'kept {requirements / "dev.in"}',
            f'kept {self.checkout / ".oasis/logs"}/', f'kept {self.checkout / ".oasis/data"}/',
            f'kept the locks in {requirements}: current', f'kept the environment {environment}',
            f'nothing to set up: run oasis --project {self.checkout} doctor']) + '\n')
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.log.exists())

    def test_a_failed_compile_keeps_the_written_files_and_says_how_to_continue(self):
        self.env['FAKE_COMPILE_FAIL'] = '1'
        result = self.setup_cmd('--apply', '--community', str(self.source), '--no-enterprise', *CREATE)
        requirements = self.checkout / '.oasis/config/requirements'
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, 'error: No solution found\n'
                         'uv pip compile of runtime.in failed (exit 1); lock.sha256 was left as it was.\n'
                         f'Fix {requirements / "runtime.in"} or its access to the package index, then run '
                         'oasis setup --apply again.\n')
        self.assertTrue((self.checkout / 'oasis-workspace.toml').is_file())
        self.assertFalse((requirements / 'lock.sha256').exists())
        self.assertFalse((self.checkout / '.oasis/venv').exists())

    def test_workspace_option_puts_the_layout_in_another_directory(self):
        directory = self.scratch / 'work'
        before = self.tree()
        result = self.setup_cmd('--workspace', str(directory), '--community', str(self.source), '--no-enterprise',
                                *CREATE)
        port = self.port_of(result.stdout)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, self.plan(port, base='', directory=directory) + DRY_RUN, ''))
        self.assertEqual(self.tree(), before)
        refused = self.setup_cmd('--workspace', str(self.scratch / 'sources'), '--community', str(self.source),
                                 '--no-enterprise')
        self.assert_refused(refused, f'Refusing --workspace {self.scratch / "sources"}: it is not at or above the '
                                     f'checkout {self.checkout}.', before)
        relative = self.setup_cmd('--workspace', 'work')
        self.assert_refused(relative, '--workspace requires an absolute existing directory.', before)

    # -- inference and questions ----------------------------------------------------------------

    def test_series_comes_from_the_manifests_else_the_machine_file_else_a_flag(self):
        before = self.tree()
        (self.checkout / 'shop_sale' / '__manifest__.py').write_text("{'name': 'Shop', 'version': '1.0'}\n")
        before = self.tree()
        # v0.16.0 S3: without a terminal the plan lists the open question; --apply refuses as before.
        self.assert_refused(self.setup_cmd('--apply', '--community', str(self.source), '--no-enterprise'),
                            NOT_TTY_SERIES.format(root=self.checkout)[len('ERROR: '):-1], before)
        listed = self.setup_cmd('--community', str(self.source), '--no-enterprise')
        self.assertEqual((listed.returncode, listed.stdout, listed.stderr), (
            0, f'checkout: {self.checkout} (main)\nopen question series: '
               f'{NOT_TTY_SERIES.format(root=self.checkout)[len("ERROR: "):]}{OPEN_PLAN}', ''))
        self.assertEqual(self.tree(), before)
        flagged = self.setup_cmd('--series', '19.0', '--community', str(self.source), '--no-enterprise')
        self.assertEqual((flagged.returncode, flagged.stderr), (0, ''))
        self.assertIn('series: 19.0 (from --series)\n', flagged.stdout)
        self.write_machine(f"[series.\"19.0\"]\ncommunity = '{self.source}'\n")
        before = self.tree()
        machine = self.setup_cmd()
        self.assertEqual((machine.returncode, machine.stderr), (0, ''))
        self.assertIn('series: 19.0 (from the machine file)\n'
                      f'community: {self.source} (from the machine file)\n'
                      'enterprise: none (from the machine file)\n', machine.stdout)
        self.assertIn(f'kept {self.machine}: [series."19.0"] gives the Odoo source\n', machine.stdout)
        self.assertEqual(self.tree(), before)
        self.assert_refused(self.setup_cmd('--series', '18.0'),
                            'Unsupported series 18.0; supported: 19.0, 15.0.', before)

    def test_modules_of_another_series_or_of_several_are_refused(self):
        self.module('old_sale', "{'name': 'Old', 'version': '18.0.1.0.0'}\n")
        before = self.tree()
        self.assert_refused(self.setup_cmd('--community', str(self.source), '--no-enterprise'),
                            f'The module manifests of {self.checkout} declare several Odoo series (18.0, 19.0); '
                            'pass --series <x.y>.', before)
        (self.checkout / 'shop_sale' / '__manifest__.py').unlink()
        before = self.tree()
        self.assert_refused(self.setup_cmd('--community', str(self.source), '--no-enterprise'),
                            f'The module manifests of {self.checkout} declare Odoo 18.0, which oasis does not '
                            'support (supported: 19.0, 15.0).', before)

    def test_without_a_terminal_a_missing_answer_names_its_flag_and_a_found_path_is_only_suggested(self):
        before = self.tree()
        # v0.16.0 S3: --apply refuses; the plan lists the open question (tests/test_setup_plan.py).
        self.assert_refused(self.setup_cmd('--apply', '--no-enterprise'),
                            f'No Odoo Community source for 19.0 in the machine file {self.machine}: '
                            'pass --community <dir>.', before)
        found = self.odoo_source(self.scratch / 'work' / 'odoo')
        before = self.tree()
        self.assert_refused(self.setup_cmd('--apply', '--no-enterprise'),
                            f'No Odoo Community source for 19.0 in the machine file {self.machine}: '
                            f'pass --community <dir>; found {found}, a suggestion only: pass it to use it.', before)
        self.assert_refused(self.setup_cmd('--apply', '--community', str(self.source)),
                            'Enterprise or not for 19.0: pass --enterprise <dir> or --no-enterprise.', before)
        self.assert_refused(self.setup_cmd('--community', str(self.scratch / 'work'), '--no-enterprise'),
                            f'--community {self.scratch / "work"} is not an Odoo 19.0 source '
                            '(no odoo/release.py that declares it).', before)

    def test_on_a_terminal_setup_asks_what_it_cannot_infer(self):
        found = self.odoo_source(self.scratch / 'work' / 'odoo')
        enterprise = self.scratch / 'sources' / 'enterprise'
        enterprise.mkdir()
        before = self.tree()
        master, slave = pty.openpty()
        process = subprocess.Popen([sys.executable, '-B', str(CLI), '--project', str(self.checkout), 'setup'],
                                   stdin=slave, stdout=subprocess.PIPE, stderr=slave, env=self.env, text=True)
        os.close(slave)
        self.addCleanup(os.close, master)
        prompts = ''
        for expected, answer in ((f'Odoo Community source for 19.0 (absolute path) [Enter: {found}]: ', ''),
                                 ('Odoo Enterprise source for 19.0 (absolute path, empty for none): ',
                                  str(enterprise)),
                                 # v0.15.0 S8: the environment setup would create, and its Python.
                                 ('Python environment for Odoo 19.0: Enter creates '
                                  f'{self.checkout / ".oasis/venv"}, or type the absolute path of an existing '
                                  'environment to use instead: ', ''),
                                 (f'Python of the new environment {self.checkout / ".oasis/venv"}, one of 3.10, '
                                  '3.11, 3.12, 3.13, 3.14 [Enter: 3.12]: ', ''),
                                 # v0.16.0 S6: the [development] table of init-dev-database.
                                 ('init-dev-database needs a [development] table in '
                                  f'{self.checkout / "oasis-workspace.toml"}: add one with administrator_login = '
                                  "'admin' (its password is generated)? (add/none) [Enter: add]: ", 'none')):
            deadline = time.monotonic() + 30
            while expected not in prompts and time.monotonic() < deadline:
                if select.select([master], [], [], 1)[0]:
                    prompts += os.read(master, 4096).decode()
            self.assertIn(expected, prompts)
            os.write(master, (answer + '\n').encode())
        stdout, _ = process.communicate(timeout=60)
        self.assertEqual(process.returncode, 0, prompts)
        self.assertIn(f'community: {found} (answered)\nenterprise: {enterprise} (answered)\n', stdout)
        self.assertIn(f"  community = '{found}'\n  enterprise = '{enterprise}'\n", stdout)
        self.assertNotIn('[development]', stdout)
        self.assertEqual(self.tree(), before)

    # -- adopting what exists -------------------------------------------------------------------

    def test_an_existing_machine_file_is_extended_but_an_existing_entry_is_never_edited(self):
        self.write_machine('# my machine\n')
        result = self.setup_cmd('--apply', '--community', str(self.source), '--no-enterprise', *CREATE)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn(f'add [series."19.0"] to {self.machine}:\n  [series."19.0"]\n', result.stdout)
        self.assertEqual(self.machine.read_text(), f"# my machine\n\n[series.\"19.0\"]\ncommunity = '{self.source}'\n")
        self.assertEqual(self.machine.stat().st_mode & 0o777, 0o600)
        # An existing entry: a flag that disagrees with it is refused, the file left alone.
        (self.checkout / 'oasis-workspace.toml').unlink()
        self.log.unlink()
        other = self.odoo_source(self.scratch / 'other')
        before = self.tree()
        self.assert_refused(self.setup_cmd('--community', str(other), '--no-enterprise'),
                            f'The machine file {self.machine} already sets community for 19.0; setup never edits '
                            'an existing entry: drop --community, or change the machine file yourself.', before)
        self.machine.write_text('[series."19.0"]\nenvironments = \'/srv/envs\'\n')
        before = self.tree()
        self.assert_refused(self.setup_cmd('--community', str(self.source), '--no-enterprise'),
                            f'The machine file {self.machine} has [series."19.0"] without community; setup never '
                            'edits an existing entry: add community there yourself.', before)

    def test_an_existing_workspace_is_adopted_and_only_its_gaps_are_planned(self):
        project = self.scratch / 'work'
        (project / 'config').mkdir()
        conf = project / 'config' / 'odoo.conf'
        conf.write_text(f'[options]\ndb_port = 6543\nadmin_passwd = {MARKER}\n')
        (project / 'config' / 'compose.yml').write_text('name: mine\n')
        env_file = project / 'config' / 'runtime-env'
        env_file.write_text(f'ODOO_DB_PASSWORD={MARKER}\n')
        (project / 'oasis-workspace.toml').write_text(
            f"workspace_version = 1\nodoo_version = '19.0'\n\n[tooling]\ncommunity = '{self.source}'\n"
            "environment = 'envs/shop'\nconfig = 'config/odoo.conf'\nenv_file = 'config/runtime-env'\n"
            "compose = 'config/compose.yml'\nrequirements = 'config/requirements'\naddons_paths = ['.']\n"
            "db_service = 'pg'\ndev_prefix = 'shop_dev_'\ntest_prefix = 'shop_test_'\n")
        requirements = project / 'config/requirements'
        before = self.tree()
        result = self.setup_cmd()
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout, '\n'.join([
            f'checkout: {self.checkout} (main)', f'workspace: {project / "oasis-workspace.toml"} (existing)',
            f'kept {conf}', f'kept {project / "config/compose.yml"}', f'kept {env_file}',
            f'create {requirements / "runtime.in"}: -r {self.source}/requirements.txt',
            f'create {requirements / "dev.in"}: -c runtime.txt, -r runtime.in',
            f'compile {requirements}/runtime.txt, dev.txt and lock.sha256 with Python 3.12 (uv pip compile)',
            f'create the environment {project / "envs/shop"} with Python 3.12 (uv venv) and sync dev.txt '
            '(uv pip sync)']) + '\n' + DRY_RUN)
        self.assertEqual(self.tree(), before)
        for flag in (('--community', str(self.source)), ('--name', 'other'), ('--series', '19.0'),
                     ('--exception', 'shop_sale'), ('--config-dir', str(project / 'config'))):
            with self.subTest(flag=flag[0]):
                self.assert_refused(self.setup_cmd(*flag), f'{flag[0]}: {self.checkout} is already configured by '
                                    f'{project / "oasis-workspace.toml"}; setup only fills what is missing.', before)
        applied = self.setup_cmd('--apply')
        self.assertEqual((applied.returncode, applied.stderr), (0, ''))
        self.assertNotIn(MARKER, applied.stdout)
        self.assertEqual(conf.read_text(), f'[options]\ndb_port = 6543\nadmin_passwd = {MARKER}\n')
        self.assertEqual(env_file.read_text(), f'ODOO_DB_PASSWORD={MARKER}\n')
        self.assertEqual((project / 'config/compose.yml').read_text(), 'name: mine\n')
        self.assertFalse(self.machine.exists())
        self.assertNotIn('fill in', applied.stdout)
        self.assertIn(f'  1. oasis --project {self.checkout} start-database\n', applied.stdout)
        self.assertNotIn(str(env_file), applied.stdout.split('next steps:')[1])

    def test_a_workspace_without_a_source_gets_the_machine_entry(self):
        project = self.scratch / 'work'
        (project / 'oasis-workspace.toml').write_text(
            "workspace_version = 1\nodoo_version = '19.0'\n\n[tooling]\nenvironment = 'envs/shop'\n"
            "config = 'config/odoo.conf'\nenv_file = 'config/.env'\ncompose = 'config/compose.yml'\n"
            "requirements = 'config/requirements'\naddons_paths = ['.']\ndb_service = 'db'\n"
            "dev_prefix = 'shop_dev_'\ntest_prefix = 'shop_test_'\n")
        result = self.setup_cmd('--community', str(self.source), '--no-enterprise')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn(f'create {self.machine} (mode 0600):\n', result.stdout)
        self.assertIn(f'create {project / "config/odoo.conf"} (mode 0600): path-free; db_port ', result.stdout)

    def test_a_linked_worktree_without_a_workspace_is_sent_to_its_main_checkout(self):
        self.git(self.checkout, 'worktree', 'add', '-q', '-b', 'feat', '../shop-feat')
        before = self.tree()
        result = subprocess.run([sys.executable, '-B', str(CLI), '--project', str(self.scratch / 'work/shop-feat'),
                                 'setup'], capture_output=True, text=True, env=self.env, stdin=subprocess.DEVNULL)
        self.assert_refused(result, f'{self.scratch / "work/shop-feat"} is a linked worktree of {self.checkout}: '
                                    'run oasis setup in the main checkout.', before)

    def test_an_untrusted_checkout_directory_is_refused(self):
        self.checkout.chmod(0o775)
        self.addCleanup(self.checkout.chmod, 0o755)
        before = self.tree()
        self.assert_refused(self.setup_cmd('--community', str(self.source), '--no-enterprise'),
                            f'Refusing to write {self.checkout / "oasis-workspace.toml"}: {self.checkout} is '
                            'writable by group or others.', before)

    def test_a_project_name_that_gives_no_prefixes_needs_name(self):
        named = self.setup_cmd('--name', 'acme', '--community', str(self.source), '--no-enterprise')
        self.assertEqual((named.returncode, named.stderr), (0, ''))
        self.assertIn("  dev_prefix = 'acme_dev_'\n  test_prefix = 'acme_test_'\n", named.stdout)
        before = self.tree()
        self.assert_refused(self.setup_cmd('--name', '9x', '--community', str(self.source), '--no-enterprise'),
                            'Invalid --name 9x: use 2 to 20 lowercase letters, digits or underscores, starting '
                            'with a letter.', before)

    def test_series_section_options_are_refused_without_a_workspace_file(self):
        # v0.15.0 S5: --exception and --config-dir only apply when setup adds a series section.
        before = self.tree()
        for flag in (('--exception', 'shop_sale'), ('--config-dir', str(self.scratch))):
            with self.subTest(flag=flag[0]):
                self.assert_refused(self.setup_cmd(*flag, '--community', str(self.source), '--no-enterprise'),
                                    f'{flag[0]}: {self.checkout} has no workspace file; it only applies when setup '
                                    'adds a [series."<x.y>"] section to one.', before)


    # -- an existing environment (v0.15.0 S7) ---------------------------------------------------

    def existing_environment(self, name, version):
        """An environment outside the checkout: pyvenv.cfg declares version; bin/python leaves a mark when run."""
        path = self.scratch / 'envs' / name
        (path / 'bin').mkdir(parents=True)
        (path / 'pyvenv.cfg').write_text(f'home = /usr/bin\nversion = {version}\n')
        (path / 'bin/python').write_text(f'#!/bin/sh\ntouch {self.scratch / "python-ran"}\n')
        (path / 'bin/python').chmod(0o755)
        return path

    def test_environment_adopts_an_existing_environment_of_the_default_python_in_tooling(self):
        environment = self.existing_environment('shop', '3.12.3')
        workspace = self.checkout / 'oasis-workspace.toml'
        config = self.checkout / '.oasis/config'
        requirements = config / 'requirements'
        result = self.setup_cmd('--apply', '--environment', str(environment), '--community', str(self.source),
                                '--no-enterprise')
        port = self.port_of(result.stdout)
        plan = self.plan(port).replace(f"  environment = '.oasis/venv'", f"  environment = '{environment}'").replace(
            f'create the environment {self.checkout / ".oasis/venv"} with Python 3.12 (uv venv) and sync dev.txt '
            '(uv pip sync)',
            f'adopt the environment {environment} (from --environment): Python 3.12 (its pyvenv.cfg); setup never '
            'creates, syncs or deletes it')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertEqual(result.stdout, plan + (
            f'verified: {self.checkout} loads its configuration from {workspace}\n'
            f'compiled {requirements}/runtime.txt, dev.txt and lock.sha256\n'
            'next steps:\n'
            f'  1. the locks in {requirements} describe runtime.in and dev.in: oasis --project {self.checkout} '
            f'bootstrap --apply syncs the adopted environment {environment} to them (it changes the packages '
            'installed there)\n'
            f'  2. oasis --project {self.checkout} start-database\n'
            f'  3. oasis --project {self.checkout} doctor\n'
            f'  4. oasis --project {self.checkout} init-dev-database --plan\n'))
        self.assertEqual(workspace.read_text(), WORKSPACE.format(base='.oasis/').replace(
            "environment = '.oasis/venv'", f"environment = '{environment}'"))
        self.assertEqual(self.log.read_text().splitlines(), [
            f'uv pip compile --python-version 3.12 runtime.in -o runtime.txt (in {requirements})',
            f'uv pip compile --python-version 3.12 dev.in -o dev.txt (in {requirements})'])
        self.assertEqual(sorted(path.name for path in environment.rglob('*')), ['bin', 'python', 'pyvenv.cfg'])
        self.assertFalse((self.scratch / 'python-ran').exists())
        self.assertFalse((self.checkout / '.oasis/venv').exists())

    def test_environment_of_another_python_of_the_series_becomes_the_default_named_environment(self):
        environment = self.existing_environment('shop-313', '3.13.1')
        workspace = self.checkout / 'oasis-workspace.toml'
        result = self.setup_cmd('--apply', '--environment', str(environment), '--community', str(self.source),
                                '--no-enterprise')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn(f'adopt the environment {environment} (from --environment): Python 3.13 (its pyvenv.cfg)',
                      result.stdout)
        self.assertEqual(workspace.read_text(), WORKSPACE.format(base='.oasis/').replace(
            "environment = '.oasis/venv'\n", '') + f"\n[environments.default]\npath = '{environment}'\npython = '3.13'\n")
        self.assertIn('--python-version 3.13 runtime.in', self.log.read_text())
        values = subprocess.run([sys.executable, '-B', str(READER), str(self.checkout)], capture_output=True,
                                text=True, env=self.env)
        self.assertEqual((values.returncode, values.stderr), (0, ''))
        for line in (f'PROJECT_ENVIRONMENT={environment}', 'ENVIRONMENT_NAME=default', 'PYTHON_VERSION=3.13'):
            self.assertIn(line + '\n', values.stdout)
        self.assertFalse((self.scratch / 'python-ran').exists())
        # Outside the series' range: refused before anything is written.
        other = self.existing_environment('shop-39', '3.9.18')
        self.checkout = self.scratch / 'work' / 'other'
        self.module('other_sale', MANIFEST)
        self.git(self.checkout, 'init', '-q')
        self.log.unlink()
        before = self.tree()
        self.assert_refused(self.setup_cmd('--environment', str(other), '--community', str(self.source),
                                           '--no-enterprise'),
                            f'--environment {other} has Python 3.9, which Odoo 19.0 does not support (3.10 to 3.14).',
                            before)

    # -- the environment and its Python, open until answered (v0.20.0 S1) -----------------------

    def test_without_a_terminal_the_environment_and_its_python_are_open_questions_until_answered(self):
        # The v0.17.0 field run: `setup --plan --json` (an agent: no terminal) listed no environment question and
        # silently chose the environment and the series' default Python. They are open, with a recommended answer.
        environment = self.checkout / '.oasis/venv'
        flags = ('--community', str(self.source), '--no-enterprise')
        environment_text = (f'Python environment for Odoo 19.0: create {environment}, or use an existing '
                            'environment')
        python_text = f'Python of the new environment {environment}'
        refusals = (f'{environment_text}. Answer with --answer environment=create | --environment <dir> '
                    '(recommended: create).',
                    f'{python_text}, one of 3.10, 3.11, 3.12, 3.13, 3.14. Answer with --python <x.y> (recommended: '
                    '3.12).')
        before = self.tree()
        result = self.setup_cmd('--plan', '--json', *flags)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        plan = json.loads(result.stdout)
        self.assertEqual((plan['complete'], plan['ready_to_apply'], plan['open']),
                         (True, False, ['environment', 'python']))
        asked = {question['id']: question for question in plan['questions']}
        self.assertEqual(asked['environment'], {
            'id': 'environment', 'text': environment_text,
            'options': [{'value': 'create', 'label': f'create {environment}'}], 'recommended': 'create',
            'flag': '--answer environment=create | --environment <dir>', 'answer': None, 'origin': None})
        self.assertEqual(asked['python'], {
            'id': 'python', 'text': python_text,
            'options': [{'value': python, 'label': f'Python {python}'} for python in ('3.10', '3.11', '3.12', '3.13',
                                                                                      '3.14')],
            'recommended': '3.12', 'flag': '--python <x.y>', 'answer': None, 'origin': None})
        # The plan still shows what the recommended answers would create.
        self.assertEqual(plan['inferred']['environment'], {'value': str(environment), 'origin': 'new'})
        self.assertIn(f'create the environment {environment} with Python 3.12 (uv venv) and sync dev.txt '
                      '(uv pip sync)', plan['lines'])
        # The text plan lists them too, and --apply refuses them; nothing changes.
        text = self.setup_cmd(*flags)
        port = self.port_of(text.stdout)
        self.assertEqual((text.returncode, text.stdout, text.stderr), (
            0, self.plan(port) + f'open question environment: {refusals[0]}\nopen question python: {refusals[1]}\n'
            + OPEN_PLAN, ''))
        refused = self.setup_cmd('--apply', *flags)
        self.assertEqual((refused.returncode, refused.stdout, refused.stderr), (2, '', (
            f'ERROR: open question environment: {refusals[0]}\nERROR: open question python: {refusals[1]}\n'
            'ERROR: nothing changed: answer the open questions, then run oasis setup --apply again.\n')))
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.log.exists())
        # Answered: the recommended answers an agent relays, or --python alone (a new environment of that Python).
        for answers, expected in (
                (('--answer', 'environment=create', '--answer', 'python=3.12'),
                 [('environment', 'create', 'from --answer'), ('python', '3.12', 'from --answer python')]),
                (('--python', '3.13'),
                 [('environment', 'create', 'from --python'), ('python', '3.13', 'from --python')])):
            with self.subTest(answers=answers):
                plan = json.loads(self.setup_cmd('--plan', '--json', *flags, *answers).stdout)
                self.assertEqual((plan['ready_to_apply'], plan['open']), (True, []))
                self.assertEqual([(question['id'], question['answer'], question['origin'])
                                  for question in plan['questions'] if question['id'] in ('environment', 'python')],
                                 expected)
                self.assertEqual(plan['inferred']['python'], {'value': expected[1][1], 'origin': expected[1][2]})
        # --environment answers where the environment goes; its Python is the environment's: nothing is open.
        adopted = self.existing_environment('shop', '3.12.3')
        plan = json.loads(self.setup_cmd('--plan', '--json', *flags, '--environment', str(adopted)).stdout)
        self.assertEqual((plan['ready_to_apply'], plan['open']), (True, []))
        self.assertEqual(plan['inferred']['environment'], {'value': str(adopted), 'origin': 'from --environment'})
        self.assertEqual(self.tree(), {**before, **{path: data for path, data in self.tree().items()
                                                    if path.startswith('envs')}})
        self.assertFalse(self.log.exists())
        # Once answered, --apply sets up with those answers.
        applied = self.setup_cmd('--apply', *flags, '--answer', 'environment=create', '--python', '3.13')
        self.assertEqual((applied.returncode, applied.stderr), (0, ''), applied.stdout)
        self.assertIn(f'uv venv --python 3.13 {environment}', self.log.read_text())

    # -- review follow-ups (review-f6708244dde86835) and the series guard (S11) ----------------

    def existing_workspace(self, community=True):
        """A workspace file in work/ (above the checkout) with config/ paths and envs/shop."""
        project = self.scratch / 'work'
        (project / 'config').mkdir(exist_ok=True)
        source = f"community = '{self.source}'\n" if community else ''
        (project / 'oasis-workspace.toml').write_text(
            f"workspace_version = 1\nodoo_version = '19.0'\n\n[tooling]\n{source}"
            "environment = 'envs/shop'\nconfig = 'config/odoo.conf'\nenv_file = 'config/.env'\n"
            "compose = 'config/compose.yml'\nrequirements = 'config/requirements'\naddons_paths = ['.']\n"
            "db_service = 'db'\ndev_prefix = 'shop_dev_'\ntest_prefix = 'shop_test_'\n")
        return project

    def test_a_new_odoo_conf_takes_the_port_the_kept_compose_file_publishes(self):
        project = self.existing_workspace()
        compose = project / 'config/compose.yml'
        conf = project / 'config/odoo.conf'
        for published in ("      - '127.0.0.1:6001:5432'", '      - "6001:5432"', '      - 6001:5432/tcp  # db'):
            with self.subTest(published=published):
                compose.write_text(f'name: mine\nservices:\n  db:\n    ports:\n{published}\n')
                result = self.setup_cmd()
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertIn(f'kept {compose}\n', result.stdout)
                self.assertIn(f'create {conf} (mode 0600): path-free; db_port 6001; db_user and db_password '
                              'empty\n', result.stdout)
        # No port published to 5432 that the narrow pattern reads: a free port, and the plan says so.
        compose.write_text('name: mine\nservices:\n  db:\n    ports:\n      - target: 5432\n        published: 6001\n')
        result = self.setup_cmd()
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        port = self.port_of(result.stdout)
        self.assertIn(f'check {conf}: no port published to 5432 found in {compose}; set db_port {port} to the '
                      'port it publishes\n', result.stdout)

    def test_a_new_compose_file_publishes_the_port_the_kept_odoo_conf_connects_to(self):
        project = self.existing_workspace()
        conf = project / 'config/odoo.conf'
        compose = project / 'config/compose.yml'
        for options, port in (('db_port = 6002\n', 6002), ('db_host = 127.0.0.1\n', 5432)):
            with self.subTest(options=options):
                conf.write_text(f'[options]\n{options}admin_passwd = {MARKER}\n')
                result = self.setup_cmd()
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertIn(f'kept {conf}\n', result.stdout)
                self.assertIn(f'create {compose}: PostgreSQL 17 (postgres:17) as service db on 127.0.0.1:{port}, ',
                              result.stdout)
                self.assertNotIn(MARKER, result.stdout)

    def test_a_kept_odoo_conf_and_compose_file_that_disagree_are_reported(self):
        project = self.existing_workspace()
        conf = project / 'config/odoo.conf'
        compose = project / 'config/compose.yml'
        compose.write_text("name: mine\nservices:\n  db:\n    ports:\n      - '127.0.0.1:6001:5432'\n")
        for options, port in (('db_port = 6543\n', 6543), ('', 5432)):
            with self.subTest(options=options):
                conf.write_text(f'[options]\n{options}')
                before = self.tree()
                result = self.setup_cmd()
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertIn(f'kept {conf}\nkept {compose}\nmismatch: {conf} connects to port {port} but {compose} '
                              'publishes 6001: make them the same\n', result.stdout)
                self.assertEqual(self.tree(), before)
        conf.write_text('[options]\ndb_port = 6001\n')
        self.assertNotIn('mismatch', self.setup_cmd().stdout)

    def test_source_flags_that_agree_with_the_machine_entry_are_accepted(self):
        self.write_machine(f"[series.\"19.0\"]\ncommunity = '{self.source}'\n")
        before = self.tree()
        for args in (('--no-enterprise',), ('--community', str(self.source)),
                     ('--community', str(self.source), '--no-enterprise')):
            with self.subTest(args=args):
                result = self.setup_cmd(*args)
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                self.assertIn('enterprise: none (from the machine file)\n', result.stdout)
                self.assertEqual(self.tree(), before)
        enterprise = self.scratch / 'sources' / 'enterprise'
        enterprise.mkdir()
        self.machine.write_text(f"[series.\"19.0\"]\ncommunity = '{self.source}'\nenterprise = '{enterprise}'\n")
        before = self.tree()
        self.assert_refused(self.setup_cmd('--no-enterprise'),
                            f'The machine file {self.machine} already sets enterprise for 19.0; setup never edits '
                            'an existing entry: drop --no-enterprise, or change the machine file yourself.', before)
        accepted = self.setup_cmd('--enterprise', str(enterprise))
        self.assertEqual((accepted.returncode, accepted.stderr), (0, ''))
        self.assertIn(f'enterprise: {enterprise} (from the machine file)\n', accepted.stdout)

    def test_a_failed_verification_undoes_every_change(self):
        self.write_machine('# my machine\n')
        exclude = self.checkout / '.git/info/exclude'
        exclude.write_text('# mine\n')
        # The plan of a new workspace does not read oasis-checkout.toml; the verification does.
        (self.checkout / 'oasis-checkout.toml').write_text('[tooling]\nunknown = 1\n')
        before = self.tree()
        result = self.setup_cmd('--apply', '--community', str(self.source), '--no-enterprise', *CREATE)
        self.assertEqual((result.returncode, result.stderr), (1, (
            'ERROR: Verification failed (oasis-checkout.toml may only set odoo_version, [tooling].checkout_slug and '
            '[tooling].environment: tooling.unknown); every change was undone.\n')))
        self.assertIn(f'add [series."19.0"] to {self.machine}:\n', result.stdout)
        self.assertIn(f'create {self.checkout / "oasis-workspace.toml"} (mode 0600):\n', result.stdout)
        self.assertNotIn('verified:', result.stdout)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.machine.read_text(), '# my machine\n')
        self.assertEqual(exclude.read_text(), '# mine\n')
        self.assertFalse((self.checkout / '.oasis').exists())
        self.assertFalse(self.log.exists())

    def test_a_failed_uv_venv_or_sync_keeps_the_written_files(self):
        environment = self.checkout / '.oasis/venv'
        requirements = self.checkout / '.oasis/config/requirements'
        self.env['FAKE_VENV_FAIL'] = '1'
        result = self.setup_cmd('--apply', '--community', str(self.source), '--no-enterprise', *CREATE)
        self.assertEqual((result.returncode, result.stderr), (2, (
            'error: no interpreter\nERROR: uv venv failed (exit 3); the files above are kept: fix it, then run '
            'oasis setup --apply again.\n')))
        self.assertIn(f'compiled {requirements}/runtime.txt, dev.txt and lock.sha256\n', result.stdout)
        self.assertNotIn('next steps', result.stdout)
        for path in ('oasis-workspace.toml', '.oasis/config/odoo.conf', '.oasis/config/.env',
                     '.oasis/config/compose.yml', '.oasis/config/requirements/lock.sha256'):
            self.assertTrue((self.checkout / path).is_file(), path)
        self.assertFalse(environment.exists())
        # Run again: everything written is kept and the environment is created.
        del self.env['FAKE_VENV_FAIL']
        self.log.unlink()
        again = self.setup_cmd('--apply')
        self.assertEqual((again.returncode, again.stderr), (0, ''))
        self.assertIn(f'kept the locks in {requirements}: current\n', again.stdout)
        self.assertIn(f'created the environment {environment}\n', again.stdout)
        self.assertEqual([line.split(' (in ')[0] for line in self.log.read_text().splitlines()], [
            f'uv venv --python 3.12 {environment}',
            f'uv pip sync --python {environment}/bin/python {requirements}/dev.txt'])
        # A failed sync stops after the environment was created: a second setup run would keep that
        # environment unsynced, so the error names bootstrap --apply, which syncs it.
        (self.checkout / 'oasis-workspace.toml').unlink()
        shutil.rmtree(self.checkout / '.oasis')
        self.env['FAKE_SYNC_FAIL'] = '1'
        failed = self.setup_cmd('--apply', '--community', str(self.source), '--no-enterprise', *CREATE)
        self.assertEqual((failed.returncode, failed.stderr), (2, (
            'error: no index\nERROR: uv pip sync failed (exit 4); the files above and the environment '
            f'{environment} are kept: fix it, then run oasis --project {self.checkout} bootstrap --apply to '
            'sync it.\n')))
        self.assertNotIn('setup --apply', failed.stderr)
        self.assertNotIn('next steps', failed.stdout)
        self.assertTrue((environment / 'pyvenv.cfg').is_file())
        self.assertTrue((self.checkout / 'oasis-workspace.toml').is_file())
        # Indeed a second setup run keeps the environment without syncing it.
        del self.env['FAKE_SYNC_FAIL']
        self.log.unlink()
        again = self.setup_cmd('--apply')
        self.assertEqual((again.returncode, again.stderr), (0, ''))
        self.assertIn(f'kept the environment {environment}\n', again.stdout)
        self.assertFalse(self.log.exists())

    def test_an_edited_lock_is_kept_and_leaves_the_environment_uncreated(self):
        project = self.existing_workspace()
        requirements = project / 'config/requirements'
        requirements.mkdir()
        for name in ('runtime.in', 'runtime.txt', 'dev.in', 'dev.txt'):
            (requirements / name).write_text(f'# {name}\n')
        (requirements / 'lock.sha256').write_text(''.join(
            f'{hashlib.sha256((requirements / name).read_bytes()).hexdigest()}  {name}\n'
            for name in ('runtime.in', 'runtime.txt', 'dev.in', 'dev.txt')))
        (requirements / 'dev.txt').write_text('pylint==3.0.0\n')
        for name, text in (('odoo.conf', '[options]\ndb_port = 6543\n'), ('.env', 'ODOO_DB_USER=mine\nODOO_DB_PASSWORD=mine\n'),
                           ('compose.yml', "name: mine\nservices:\n  db:\n    ports:\n      - '6543:5432'\n")):
            (project / 'config' / name).write_text(text)
        before = self.tree()
        result = self.setup_cmd('--apply')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout, '\n'.join([
            f'checkout: {self.checkout} (main)', f'workspace: {project / "oasis-workspace.toml"} (existing)',
            f'kept {project / "config/odoo.conf"}', f'kept {project / "config/compose.yml"}',
            f'kept {project / "config/.env"}', f'kept {requirements / "runtime.in"}', f'kept {requirements / "dev.in"}',
            f'kept the locks in {requirements}: a lock was changed by hand; move it away or fingerprint it again '
            '(see oasis bootstrap)',
            f'not created: the environment {project / "envs/shop"}, until the locks match lock.sha256',
            f'nothing to set up: run oasis --project {self.checkout} doctor']) + '\n')
        self.assertEqual(self.tree(), before)
        self.assertFalse(self.log.exists())

    def adopted_next_steps(self, project, add_development):
        """The next steps setup --apply prints for existing_workspace() with every other piece created."""
        config = project / 'config'
        workspace = project / 'oasis-workspace.toml'
        steps = [f'oasis --project {self.checkout} start-database', f'oasis --project {self.checkout} doctor']
        if add_development:
            steps.append(ADD_DEVELOPMENT.format(workspace=workspace))
        steps.append(f'oasis --project {self.checkout} init-dev-database --plan')
        return 'next steps:\n' + ''.join(f'  {number}. {step}\n' for number, step in enumerate(steps, 1))

    def test_a_workspace_with_a_development_table_gets_no_step_to_add_one(self):
        project = self.existing_workspace()
        workspace = project / 'oasis-workspace.toml'
        workspace.write_text(workspace.read_text() + "\n[development]\nadministrator_login = 'local_admin'\n")
        result = self.setup_cmd('--apply')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn(f'created the environment {project / "envs/shop"}\n', result.stdout)
        self.assertTrue(result.stdout.endswith(self.adopted_next_steps(project, add_development=False)), result.stdout)
        self.assertNotIn('add these lines', result.stdout)
        # Without the table the step is there and init-dev-database comes after it.
        shutil.rmtree(project / 'config')
        shutil.rmtree(project / 'envs')
        self.existing_workspace()
        result = self.setup_cmd('--apply')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.endswith(self.adopted_next_steps(project, add_development=True)), result.stdout)

    def test_a_workspace_file_unreadable_after_the_verification_gets_no_step_to_add_a_development_table(self):
        # The file is read again for the next steps: when that read fails, doctor reports it; setup
        # does not advise editing a file that may be broken.
        project = self.existing_workspace()
        workspace = project / 'oasis-workspace.toml'
        self.env['FAKE_SYNC_BREAK'] = str(workspace)
        result = self.setup_cmd('--apply')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(workspace.read_text(), 'broken = [\n')
        self.assertIn(f'verified: {self.checkout} loads its configuration from {workspace}\n', result.stdout)
        self.assertTrue(result.stdout.endswith(self.adopted_next_steps(project, add_development=False)), result.stdout)
        self.assertNotIn('add these lines', result.stdout)

    def test_a_new_workspace_gets_the_development_table_unless_the_answer_is_none(self):
        # v0.16.0 S6: init-dev-database needs [development]; setup asks the question development (recommended add,
        # applied without a terminal), so no manual edit of the workspace file comes before it.
        workspace = self.checkout / 'oasis-workspace.toml'
        flags = ('--community', str(self.source), '--no-enterprise')
        result = self.setup_cmd('--apply', *flags, *CREATE, '--answer', 'development=none')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertEqual(workspace.read_text(), WORKSPACE.format(base='.oasis/').replace(DEVELOPMENT, ''))
        self.assertTrue(result.stdout.endswith(
            'next steps:\n'
            f'  1. oasis --project {self.checkout} start-database\n'
            f'  2. oasis --project {self.checkout} doctor\n'
            f'  3. {ADD_DEVELOPMENT.format(workspace=workspace)}\n'
            f'  4. oasis --project {self.checkout} init-dev-database --plan\n'), result.stdout)
        # The lines the step names are the table setup writes.
        self.assertIn("\n[development]\nadministrator_login = 'admin'\n", DEVELOPMENT)
        # An answer setup does not take, and the question asked of an existing workspace, are refused.
        self.log.unlink()
        before = self.tree()
        self.assert_refused(self.setup_cmd('--answer', 'development=add'),
                            '--answer: setup does not ask development for this checkout; nothing changed: drop it.',
                            before)
        shutil.rmtree(self.checkout / '.oasis')
        workspace.unlink()
        before = self.tree()
        self.assert_refused(self.setup_cmd(*flags, '--answer', 'development=maybe'),
                            'Invalid answer maybe for development: answer add or none.', before)

    def test_modules_of_another_series_than_the_configured_one_get_the_series_exceptions_question(self):
        # S11, v0.16.0 S4: an existing configuration (the checkout's modules are 19.0, one is 15.0).
        project = self.existing_workspace()
        workspace = project / 'oasis-workspace.toml'
        original = workspace.read_text()
        self.module('old_sale', "{'name': 'Old', 'version': '15.0.1.0.0'}\n")
        before = self.tree()
        message = (f'The module old_sale declares Odoo 15.0 (version 15.0.1.0.0 in '
                   f'{self.checkout / "old_sale/__manifest__.py"}), but {self.checkout} is configured for Odoo 19.0 '
                   f'by {workspace}: run oasis in a checkout of an Odoo 19.0 branch, or set the '
                   'version of old_sale to 19.0.x.y.z if it is an Odoo 19.0 module; for Odoo 15.0 here, run oasis '
                   f'setup to add a [series."15.0"] section to {workspace}.')
        question = (f'The modules old_sale (Odoo 15.0) of {self.checkout} declare another Odoo series than 19.0: list '
                    f'them in series_exceptions under [series."19.0"] in {workspace}? Answer with --answer '
                    'series_exceptions=<add|no> (recommended: add).')
        result = self.setup_cmd()
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn(f'add [series."19.0"] to {workspace}:\n', result.stdout)
        self.assertTrue(result.stdout.endswith(f'open question series_exceptions: {question}\n{OPEN_PLAN}'),
                        result.stdout)
        self.assertEqual(self.tree(), before)
        result = self.setup_cmd('--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
            f'ERROR: open question series_exceptions: {question}\nERROR: nothing changed: answer the open '
            'questions, then run oasis setup --apply again.\n')))
        self.assert_refused(self.setup_cmd('--answer', 'series_exceptions=no'), message, before)
        result = self.setup_cmd('--apply', '--answer', 'series_exceptions=add')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertEqual(workspace.read_text(), original.replace('workspace_version = 1', 'workspace_version = 2')
                         + '\n' + SECTION.format(modules="'old_sale'"))
        self.assertIn(f'verified: {self.checkout} loads its configuration from {workspace}\n', result.stdout)
        # A new configuration whose --series disagrees with a module: the same question, before anything is written.
        workspace.unlink()
        self.log.unlink()
        new = self.checkout / 'oasis-workspace.toml'
        before = self.tree()
        flags = ('--series', '19.0', '--community', str(self.source), '--no-enterprise')
        self.assert_refused(self.setup_cmd(*flags, '--answer', 'series_exceptions=no'),
                            message.replace(str(workspace), str(new)), before)
        result = self.setup_cmd('--apply', *flags, *CREATE, '--answer', 'series_exceptions=add')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertEqual(new.read_text(), WORKSPACE.format(base='.oasis/').replace('workspace_version = 1',
                                                                                    'workspace_version = 2')
                         + '\n' + SECTION.format(modules="'old_sale'"))
        # Setup detects the series itself: a version that is not series-style does not count.
        new.unlink()
        (self.checkout / 'old_sale/__manifest__.py').write_text("{'name': 'Old', 'version': '1.2.3.4.5'}\n")
        result = self.setup_cmd('--community', str(self.source), '--no-enterprise')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn('series: 19.0 (from the module manifests)\n', result.stdout)
        self.assertNotIn('series_exceptions', result.stdout)

if __name__ == '__main__':
    unittest.main()
