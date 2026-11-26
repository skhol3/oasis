"""Fresh development initialization through the public CLI, isolated from Odoo/PG."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import time
import unittest
from unittest import mock

import test_lifecycle

ROOT = Path(__file__).resolve().parents[1]
PROFILE = '''
[development]
administrator_login = 'local_admin'
[[development.users]]
login = 'planner'
name = 'Local Planner'
groups = ['example.group_planner']
[[development.users]]
login = 'manager'
name = 'Local Manager'
groups = ['example.group_manager']
'''

# These doubles implement only the Odoo public operations used by the new command.
FAKE_ODOO = '''
import copy, hashlib, json, os
from pathlib import Path
from types import SimpleNamespace

# Workspace files must not be group-writable (trust rule); keep test results independent of the caller's umask.
os.umask(0o022)
path = Path(os.environ['FAKE_STATE'])
def read():
    return json.loads(path.read_text()) if path.exists() else {}
def save(value):
    path.write_text(json.dumps(value))
def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()
class Config:
    def parse_config(self, args):
        Path(os.environ['FAKE_STATE'] + '.config').write_text(json.dumps(args))
tools = SimpleNamespace(config=Config())
class Database:
    def exp_create_database(self, database, demo, lang, user_password, login):
        if read():
            raise RuntimeError('existing database')
        save({'demo': demo, 'users': {login: {'id': 2, 'password': digest(user_password),
              'groups': [1, 2]}}, 'commits': 0})
class Common:
    def exp_authenticate(self, database, login, password, agent):
        user = read().get('users', {}).get(login, {})
        return user.get('id') if user.get('password') == digest(password) else False
service = SimpleNamespace(db=Database(), common=Common())
class Cursor:
    def __init__(self):
        self.data = copy.deepcopy(read())
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def commit(self):
        self.data['commits'] += 1
        save(self.data)
class Registry:
    @classmethod
    def new(cls, database):
        return cls()
    def cursor(self):
        return Cursor()
modules = SimpleNamespace(registry=SimpleNamespace(Registry=Registry))
class Users:
    def __init__(self, env):
        self.env = env
    def with_context(self, **kwargs):
        return self
    def search(self, domain, **kwargs):
        return domain[0][2] in self.env.cr.data['users']
    def create(self, values):
        uid = len(self.env.cr.data['users']) + 2
        # The groups field of res.users is the series' (group_ids in 19.0, groups_id in 15.0).
        [field] = [key for key in ('group_ids', 'groups_id') if key in values]
        self.env.cr.data['users'][values['login']] = {
            'id': uid, 'password': digest(values['password']),
            'groups': values[field][0][2], 'groups_field': field,
            'company': values['company_id'], 'companies': values['company_ids'][0][2]}
        return SimpleNamespace(id=uid)
class Environment:
    def __init__(self, cr, uid, context):
        self.cr = cr
        self.company = SimpleNamespace(id=1)
    def __getitem__(self, key):
        assert key == 'res.users'
        return Users(self)
    def ref(self, xmlid):
        refs = {'base.group_user': 1, 'base.group_system': 2,
                'example.group_planner': 3, 'example.group_manager': 4}
        return SimpleNamespace(_name='res.groups', id=refs[xmlid])
api = SimpleNamespace(Environment=Environment, SUPERUSER_ID=1)
'''


class FailingWrite:
    """os.fdopen's stream whose write fails (a full disk)."""

    def __init__(self, descriptor, *args, **kwargs):
        self.stream = open(descriptor, *args, **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stream.close()

    def fileno(self):
        return self.stream.fileno()

    def write(self, text):
        raise OSError('no space left on device')


class DevelopmentUsersTests(unittest.TestCase):
    def setUp(self):
        test_lifecycle.LifecycleTests.setUp(self)
        self.profile = self.root / 'oasis-workspace.toml'
        self.profile.write_text(self.profile.read_text() + PROFILE)
        self.state = self.root / 'state.json'
        self.env['FAKE_STATE'] = str(self.state)
        (self.source / 'odoo/__init__.py').write_text(FAKE_ODOO)
        for package in ('service', 'modules'):
            directory = self.source / 'odoo' / package
            directory.mkdir()
            (directory / '__init__.py').write_text('')
        (self.source / 'odoo/service/db.py').write_text(
            'from .. import Database\nexp_create_database = Database().exp_create_database\n')
        (self.source / 'odoo/service/common.py').write_text(
            'from .. import Common\nexp_authenticate = Common().exp_authenticate\n')
        (self.source / 'odoo/modules/registry.py').write_text('from .. import Registry\n')
        (self.source / 'odoo-bin').write_text('')
        self.python.write_text('#!' + sys.executable + '\n'
            'import json, os, sys\n'
            'from pathlib import Path\n'
            'if sys.argv[1] == "-c": print("3.12"); sys.exit(0)\n'
            'if "--version" in sys.argv: print("Odoo Server 19.0"); sys.exit(0)\n'
            'if sys.argv[1].endswith("odoo-bin"):\n'
            ' p=Path(os.environ["FAKE_STATE"]); d=json.loads(p.read_text()); '
            'd["installed"]=True; d.setdefault("installs", []).append(sys.argv[1:]); '
            'p.write_text(json.dumps(d)); sys.exit(0)\n'
            # The runner: FAKE_RUNNER_EXIT ends it with that status, FAKE_RUNNER_RAISE with a traceback (exit 1),
            # FAKE_RUNNER_SLEEP records the pid of its parent in that file and waits; nothing is created.
            'if os.environ.get("FAKE_RUNNER_EXIT"): sys.exit(int(os.environ["FAKE_RUNNER_EXIT"]))\n'
            'if os.environ.get("FAKE_RUNNER_RAISE"): raise RuntimeError("runner crashed")\n'
            'if os.environ.get("FAKE_RUNNER_SLEEP"):\n'
            ' import time; Path(os.environ["FAKE_RUNNER_SLEEP"]).write_text(str(os.getppid())); time.sleep(30)\n'
            'os.execv(sys.executable, [sys.executable, *sys.argv[1:]])\n')
        self.python.chmod(0o755)

    def command(self, *args):
        return [sys.executable, '-B', str(ROOT / 'odoo19'), '--project', str(self.root),
                'init-dev-database', *args]

    def invoke(self, *args):
        return subprocess.run(self.command(*args), input='', text=True,
                              capture_output=True, env=self.env, timeout=10)

    def terminal(self, *args, generated=()):
        """Run on a terminal, typing a password (twice) for each login but those in generated, which
        get Enter at their first prompt."""
        master, slave = pty.openpty()
        process = subprocess.Popen(self.command(*args), stdin=slave, stdout=slave,
                                   stderr=slave, env=self.env, start_new_session=True)
        os.close(slave)
        output = b''
        pending = b''
        logins = ('local_admin', 'planner', 'manager')
        secrets = [hashlib.sha256(os.urandom(32)).hexdigest() for _ in range(3)]
        prompts, replies = [], []
        for login, secret in zip(logins, secrets):
            kinds = ('Password',) if login in generated else ('Password', 'Confirm password')
            prompts += [f'{kind} for {login}: '.encode() for kind in kinds]
            replies += ['' if login in generated else secret] * len(kinds)
        try:
            while True:
                if not select.select([master], [], [], 15)[0]:
                    self.fail('Terminal command did not finish or prompt within 15 seconds.')
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output += chunk
                pending += chunk
                if prompts and prompts[0] in pending:
                    pending = pending.split(prompts.pop(0), 1)[1]
                    os.write(master, replies.pop(0).encode() + b'\n')
            code = process.wait(timeout=5)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)
        self.assertTrue(all(secret.encode() not in output for secret in secrets),
                        'A password was exposed in terminal output.')
        return code, output.decode().replace('\r\n', '\n')

    def test_rejects_test_unmanaged_empty_and_unsafe_names_without_effects(self):
        for database in ('cc_test_coffee', 'other_db', 'cc_dev_', "cc_dev_bad'"):
            result = self.invoke('coffee', database)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                (2, '', 'ERROR: Initialization requires a named development database.\n'))
            self.assertFalse(self.state.exists())
            self.assertFalse(self.commands.exists())

    def test_slugged_checkout_rejects_main_checkout_name_without_effects(self):
        (self.root / 'oasis-checkout.toml').write_text("[tooling]\ncheckout_slug = 'wt_1'\n")
        for database in ('cc_dev_coffee', 'cc_dev_wt_1_'):
            result = self.invoke('coffee', database)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                (2, '', 'Databases of checkout wt_1 must use cc_dev_wt_1_<name> or '
                        f'cc_test_wt_1_<name>: {database}\n'))
            self.assertFalse(self.state.exists())
            self.assertFalse(self.commands.exists())

    def test_requires_explicit_module_and_database(self):
        result = self.invoke('coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Usage: init-dev-database [--with-demo] <module> <database>\n'))
        self.assertFalse(self.state.exists())
        self.assertFalse(self.commands.exists())

    def test_rejects_invalid_or_secret_profile_before_runtime(self):
        for profile in (PROFILE + "password = 'not-a-real-secret'\n",
                        PROFILE.replace("['example.group_manager']", '[]'),
                        PROFILE.replace('example.group_manager', 'not-an-xml-id')):
            self.profile.write_text(test_lifecycle.WORKSPACE + profile)
            result = self.invoke('coffee', 'cc_dev_coffee')
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, '')
            self.assertEqual(result.stderr, 'ERROR: Invalid development user configuration.\n')
            self.assertFalse(self.state.exists())
            self.assertFalse(self.commands.exists())

    def logins_file(self, database='cc_dev_coffee'):
        """Where the generated passwords of database go: next to the env file (v0.16.0 S2)."""
        return self.root / 'dev' / f'{database}.logins'

    def assert_generated(self, result, logins, database='cc_dev_coffee'):
        """The passwords of logins were generated into the logins file (0600), never printed, and are the
        ones the database accepts."""
        path = self.logins_file(database)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        lines = path.read_text().splitlines()
        self.assertEqual(lines[:2], [
            f'# Written by oasis init-dev-database: the generated passwords of {database} (docs/dev-database.md).',
            '# One "<login> <password>" per line. Never commit this file.'])
        found = dict(line.split(' ') for line in lines[2:])
        self.assertEqual(list(found), list(logins))
        state = json.loads(self.state.read_text())
        for login, password in found.items():
            self.assertRegex(password, r'\A[A-Za-z0-9_-]{32}\Z')
            self.assertEqual(state['users'][login]['password'], hashlib.sha256(password.encode()).hexdigest())
            self.assertNotIn(password, result)
            if self.commands.exists():
                self.assertNotIn(password, self.commands.read_text())

    def test_without_a_terminal_every_password_is_generated_into_a_0600_file(self):
        result = self.invoke('coffee', 'cc_dev_coffee')
        path = self.logins_file()
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertEqual(result.stdout, 'Development database initialized: cc_dev_coffee\nAccounts ready: 3\n'
                                        f'Generated passwords: {path} (mode 0600): local_admin, planner, manager\n')
        self.assert_generated(result.stdout, ('local_admin', 'planner', 'manager'))
        self.assertEqual(set(json.loads(self.state.read_text())['users']), {'local_admin', 'planner', 'manager'})
        # An existing database is refused, and its logins file stays as it was.
        before = path.read_bytes()
        result = self.invoke('coffee', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', (
            'ERROR: Could not create a fresh development database; existing data was not modified.\n')))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(sorted(item.name for item in path.parent.iterdir() if 'logins' in item.name),
                         ['cc_dev_coffee.logins'])

    def test_on_a_terminal_enter_generates_that_password_and_typed_ones_are_not_stored(self):
        code, output = self.terminal('coffee', 'cc_dev_coffee', generated=('planner',))
        self.assertEqual(code, 0, output)
        path = self.logins_file()
        self.assertIn(f'Enter at a password prompt generates one into {path} (mode 0600).\n', output)
        self.assertTrue(output.endswith('Development database initialized: cc_dev_coffee\nAccounts ready: 3\n'
                                        f'Generated passwords: {path} (mode 0600): planner\n'), output)
        self.assert_generated(output, ('planner',))
        # Every password typed: no file.
        self.state.unlink()
        code, output = self.terminal('coffee', 'cc_dev_other')
        self.assertEqual(code, 0, output)
        self.assertTrue(output.endswith('Accounts ready: 3\n'), output)
        self.assertFalse(self.logins_file('cc_dev_other').exists())

    def test_initializes_explicit_admin_and_project_roles_without_demo(self):
        code, output = self.terminal('coffee', 'cc_dev_coffee')
        self.assertEqual(code, 0, output)
        self.assertTrue(output.endswith('Development database initialized: cc_dev_coffee\nAccounts ready: 3\n'))
        state = json.loads(self.state.read_text())
        self.assertFalse(state['demo'])
        self.assertTrue(state['installed'])
        self.assertEqual(state['commits'], 1)
        self.assertEqual(set(state['users']), {'local_admin', 'planner', 'manager'})
        self.assertEqual(state['users']['planner']['groups'], [1, 3])
        self.assertEqual(state['users']['manager']['groups'], [1, 4])
        self.assertEqual(state['users']['planner']['company'], 1)
        self.assertEqual(state['users']['planner']['companies'], [1])
        self.assertEqual({user.get('groups_field') for user in state['users'].values()}, {None, 'group_ids'})
        before = self.state.read_bytes()
        code, output = self.terminal('coffee', 'cc_dev_coffee')
        self.assertEqual(code, 1)
        self.assertTrue(output.endswith('ERROR: Could not create a fresh development database; existing data was not modified.\n'))
        self.assertEqual(self.state.read_bytes(), before)

    def test_demo_help_is_explicit_and_has_no_side_effects(self):
        result = self.invoke('--help')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, '')
        self.assertIn('Usage: init-dev-database [--with-demo] <module> <database>', result.stdout)
        self.assertIn('native Odoo demo loader', result.stdout)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.commands.exists())

    def test_opt_in_demo_without_optional_modules(self):
        code, output = self.terminal('--with-demo', 'coffee', 'cc_dev_coffee')
        self.assertEqual(code, 0, output)
        state = json.loads(self.state.read_text())
        self.assertTrue(state['demo'])
        self.assertEqual(len(state['installs']), 1)
        self.assertIn('--with-demo', state['installs'][0])
        self.assertEqual(set(state['users']), {'local_admin', 'planner', 'manager'})

    def test_opt_in_native_demo_preinstalls_declared_modules(self):
        self.profile.write_text(self.profile.read_text().replace(
            "administrator_login = 'local_admin'", "administrator_login = 'local_admin'\ndemo_modules = ['purchase_stock']"))
        code, output = self.terminal('--with-demo', 'coffee', 'cc_dev_coffee')
        self.assertEqual(code, 0, output)
        state = json.loads(self.state.read_text())
        self.assertTrue(state['demo'])
        self.assertEqual(len(state['installs']), 2)
        for call, module in zip(state['installs'], ('purchase_stock', 'coffee')):
            self.assertEqual(call[call.index('-i') + 1], module)
            self.assertIn('--with-demo', call)
            self.assertNotIn('--without-demo', call)
        self.assertEqual(set(state['users']), {'local_admin', 'planner', 'manager'})

    def test_demo_module_configuration_does_not_change_default_install(self):
        self.profile.write_text(self.profile.read_text().replace(
            "administrator_login = 'local_admin'", "administrator_login = 'local_admin'\ndemo_modules = ['purchase_stock']"))
        code, output = self.terminal('coffee', 'cc_dev_coffee')
        self.assertEqual(code, 0, output)
        state = json.loads(self.state.read_text())
        self.assertFalse(state['demo'])
        self.assertEqual(len(state['installs']), 1)
        self.assertIn('--without-demo', state['installs'][0])
        self.assertEqual(state['installs'][0][state['installs'][0].index('-i') + 1], 'coffee')

    def test_demo_option_preserves_dev_only_guard(self):
        for name in ('cc_test_coffee', 'other_db', 'cc_dev_'):
            result = self.invoke('--with-demo', 'coffee', name)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                (2, '', 'ERROR: Initialization requires a named development database.\n'))
            self.assertFalse(self.state.exists())
            self.assertFalse(self.commands.exists())

    def test_invalid_demo_modules_rejected_before_side_effects(self):
        for modules in ("'purchase_stock'", "['../unsafe']", "['purchase_stock', 'purchase_stock']"):
            self.profile.write_text(test_lifecycle.WORKSPACE + PROFILE.replace(
                "administrator_login = 'local_admin'", "administrator_login = 'local_admin'\ndemo_modules = " + modules))
            result = self.invoke('--with-demo', 'coffee', 'cc_dev_coffee')
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                (2, '', 'ERROR: Invalid development user configuration.\n'))
            self.assertFalse(self.state.exists())
            self.assertFalse(self.commands.exists())

    def use_odoo_15(self):
        """An Odoo 15.0 checkout (v0.15.0 S2): workspace series, source release, Python 3.9."""
        self.profile.write_text(self.profile.read_text().replace("odoo_version = '19.0'", "odoo_version = '15.0'", 1))
        (self.source / 'odoo/release.py').write_text('version_info = (15, 0, 0, "final", 0)\n')
        self.python.write_text(self.python.read_text().replace('print("3.12")', 'print("3.9")', 1)
                               .replace('Odoo Server 19.0', 'Odoo Server 15.0', 1))

    def test_odoo_15_uses_its_demo_options_and_groups_field(self):
        # 15.0 loads demo data unless --without-demo=all is given and has no --with-demo option;
        # its res.users groups field is groups_id.
        self.use_odoo_15()
        self.profile.write_text(self.profile.read_text().replace(
            "administrator_login = 'local_admin'", "administrator_login = 'local_admin'\ndemo_modules = ['purchase_stock']"))
        conf = str(self.root / 'dev/odoo.conf')
        for demo, flags in ((False, ['--without-demo=all']), (True, [])):
            with self.subTest(demo=demo):
                self.state.unlink(missing_ok=True)
                code, output = self.terminal(*(['--with-demo'] if demo else []), 'coffee', 'cc_dev_coffee')
                self.assertEqual(code, 0, output)
                self.assertTrue(output.endswith('Development database initialized: cc_dev_coffee\nAccounts ready: 3\n'))
                state = json.loads(self.state.read_text())
                self.assertIs(state['demo'], demo)
                self.assertEqual(json.loads(Path(str(self.state) + '.config').read_text()),
                                 ['-c', conf, '--no-http', *flags, '--log-level=critical'])
                self.assertEqual(state['installs'], [
                    [str(self.source / 'odoo-bin'), '-c', conf, '-d', 'cc_dev_coffee', '-i', module, *flags,
                     '--stop-after-init', '--no-http', '--log-level=critical']
                    for module in (['purchase_stock', 'coffee'] if demo else ['coffee'])])
                self.assertEqual(state['users']['planner']['groups'], [1, 3])
                self.assertEqual({user.get('groups_field') for user in state['users'].values()}, {None, 'groups_id'})

    # Workspace mode: the checkout has no profile; [development] lives in the workspace file.
    WORKSPACE = '''workspace_version = 1
odoo_version = '19.0'

[tooling]
community = 'source/odoo'
environment = 'environments/example'
config = 'projects/a project/dev/odoo.conf'
env_file = 'projects/a project/dev/.env'
compose = 'projects/a project/dev/compose.yml'
requirements = 'projects/a project/dev/requirements'
addons_paths = ['.']
db_service = 'db'
dev_prefix = 'cc_dev_'
test_prefix = 'cc_test_'
'''

    def use_workspace(self, development=PROFILE):
        self.profile.unlink()
        workspace = self.root.parent.parent / 'oasis-workspace.toml'
        workspace.write_text(self.WORKSPACE + development)
        return workspace

    def test_workspace_without_a_terminal_generates_the_passwords_next_to_its_env_file(self):
        self.use_workspace()
        result = self.invoke('coffee', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertTrue(result.stdout.endswith(
            f'Generated passwords: {self.logins_file()} (mode 0600): local_admin, planner, manager\n'))
        self.assert_generated(result.stdout, ('local_admin', 'planner', 'manager'))

    def test_workspace_rejects_invalid_or_secret_declaration_before_runtime(self):
        for development in ('', PROFILE + "password = 'not-a-real-secret'\n",
                            PROFILE.replace('example.group_manager', 'not-an-xml-id')):
            with self.subTest(development=development):
                if not self.profile.exists():
                    self.profile.write_text('')
                self.use_workspace(development)
                result = self.invoke('coffee', 'cc_dev_coffee')
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, '', 'ERROR: Invalid development user configuration.\n'))
                self.assertFalse(self.state.exists())
                self.assertFalse(self.commands.exists())

    def test_workspace_initializes_declared_accounts(self):
        self.use_workspace()
        code, output = self.terminal('coffee', 'cc_dev_coffee')
        self.assertEqual(code, 0, output)
        self.assertTrue(output.endswith('Development database initialized: cc_dev_coffee\nAccounts ready: 3\n'))
        state = json.loads(self.state.read_text())
        self.assertFalse(state['demo'])
        self.assertEqual(set(state['users']), {'local_admin', 'planner', 'manager'})
        self.assertEqual(state['users']['manager']['groups'], [1, 4])

    def staged_files(self, database='cc_dev_coffee'):
        """The temporary logins files left next to the env file."""
        return sorted(self.logins_file(database).parent.glob(f'.{database}.logins.*'))

    def assert_kept(self, path, logins=('local_admin', 'planner', 'manager'), database='cc_dev_coffee'):
        """A staged logins file that holds the generated passwords of logins (0600)."""
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        lines = path.read_text().splitlines()
        self.assertEqual(lines[0], f'# Written by oasis init-dev-database: the generated passwords of {database} '
                                   '(docs/dev-database.md).')
        self.assertEqual([line.split(' ')[0] for line in lines[2:]], list(logins))

    def test_a_missing_logins_directory_stops_before_any_service_or_prompt(self):
        self.profile.write_text(self.profile.read_text().replace("env_file = 'dev/.env'", "env_file = 'gone/.env'"))
        result = self.invoke('coffee', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
            f'ERROR: {self.root / "gone"} does not exist: run odoo19 setup --apply; no database was created.\n')))
        self.assertFalse(self.state.exists())
        self.assertFalse(self.commands.exists())

    @unittest.skipIf(os.geteuid() == 0, 'root writes into a read-only directory')
    def test_generated_passwords_that_cannot_be_staged_create_no_database(self):
        directory = self.logins_file().parent
        directory.chmod(0o555)
        self.addCleanup(directory.chmod, 0o755)
        result = self.invoke('coffee', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
            f'ERROR: Cannot write the generated passwords next to {self.logins_file()}; no database was created.\n')))
        self.assertFalse(self.state.exists())
        self.assertEqual(self.staged_files(), [])

    def test_a_staged_file_that_cannot_be_written_is_removed(self):
        spec = importlib.util.spec_from_file_location('oasis_test_dev_users', ROOT / 'tools/dev_users.py')
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(ROOT / 'tools'))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(ROOT / 'tools'))
        target = self.logins_file()
        for name in ('fchmod', 'write'):
            with self.subTest(failing=name):
                if name == 'fchmod':
                    patch = mock.patch.object(module.os, 'fchmod', side_effect=OSError('no'))
                else:
                    patch = mock.patch.object(module.os, 'fdopen', FailingWrite)
                with patch, self.assertRaises(OSError):
                    module.staged(target, 'cc_dev_coffee', [('local_admin', 'x')])
                self.assertEqual(self.staged_files(), [])
                self.assertFalse(target.exists())

    def test_a_runner_failure_it_does_not_report_keeps_the_staged_passwords(self):
        for variable, value, code in (('FAKE_RUNNER_EXIT', '9', 9), ('FAKE_RUNNER_EXIT', '2', 2),
                                      ('FAKE_RUNNER_RAISE', '1', 1)):
            with self.subTest(variable=variable, value=value):
                for path in self.staged_files():
                    path.unlink()
                result = subprocess.run(self.command('coffee', 'cc_dev_coffee'), input='', text=True,
                                        capture_output=True, env={**self.env, variable: value}, timeout=10)
                [pending] = self.staged_files()
                self.assertEqual((result.returncode, result.stderr), (1, (
                    f'ERROR: Development setup stopped unexpectedly (exit {code}); cc_dev_coffee may exist: '
                    'odoo19 list-databases shows it.\n')))
                self.assertEqual(result.stdout, (
                    f'Generated passwords: {pending} (mode 0600; rename it to {self.logins_file()} if cc_dev_coffee '
                    'exists): local_admin, planner, manager\n'))
                self.assert_kept(pending)
                self.assertFalse(self.logins_file().exists())
                self.assertFalse(self.state.exists())

    def test_an_interrupt_after_the_runner_started_keeps_the_staged_passwords(self):
        marker = self.root / 'runner.pid'
        process = subprocess.Popen(self.command('coffee', 'cc_dev_coffee'), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   env={**self.env, 'FAKE_RUNNER_SLEEP': str(marker)},
                                   preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
        try:
            deadline = time.monotonic() + 15
            while not (marker.exists() and marker.read_text()):
                self.assertLess(time.monotonic(), deadline, 'the runner did not start')
                time.sleep(0.05)
            # The runner's parent is init-dev-database's Python (the entry point and bash exec into it).
            self.assertEqual(int(marker.read_text()), process.pid)
            os.kill(process.pid, signal.SIGINT)
            stdout, stderr = process.communicate(timeout=15)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        [pending] = self.staged_files()
        self.assertEqual((process.returncode, stderr), (130, (
            'ERROR: Interrupted while creating cc_dev_coffee; it may exist: odoo19 list-databases shows it.\n')))
        self.assertEqual(stdout, (
            f'Generated passwords: {pending} (mode 0600; rename it to {self.logins_file()} if cc_dev_coffee exists): '
            'local_admin, planner, manager\n'))
        self.assert_kept(pending)
        self.assertFalse(self.logins_file().exists())

    def test_a_logins_file_that_cannot_be_renamed_into_place_is_kept_and_named(self):
        self.logins_file().mkdir()
        result = self.invoke('coffee', 'cc_dev_coffee')
        [pending] = self.staged_files()
        self.assertEqual((result.returncode, result.stderr), (1, (
            f'ERROR: Cannot rename {pending} to {self.logins_file()}; the generated passwords stay in {pending}.\n')))
        self.assertEqual(result.stdout, (
            'Development database initialized: cc_dev_coffee\nAccounts ready: 3\n'
            f'Generated passwords: {pending} (mode 0600; it could not be renamed to {self.logins_file()}): '
            'local_admin, planner, manager\n'))
        self.assertNotIn('Traceback', result.stderr)
        self.assert_kept(pending)
        self.assertEqual(set(json.loads(self.state.read_text())['users']), {'local_admin', 'planner', 'manager'})

    def test_a_typed_password_that_does_not_match_its_confirmation_creates_nothing(self):
        master, slave = pty.openpty()
        process = subprocess.Popen(self.command('coffee', 'cc_dev_coffee'), stdin=slave, stdout=slave,
                                   stderr=slave, env=self.env, start_new_session=True)
        os.close(slave)
        output, replies = b'', [(b'Password for local_admin: ', b'first-typed\n'),
                                (b'Confirm password for local_admin: ', b'second-typed\n')]
        try:
            while True:
                if not select.select([master], [], [], 15)[0]:
                    self.fail('Terminal command did not finish or prompt within 15 seconds.')
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output += chunk
                if replies and replies[0][0] in output:
                    output = output.replace(replies[0][0], b'<' + replies[0][0].strip() + b'>', 1)
                    os.write(master, replies.pop(0)[1])
            code = process.wait(timeout=5)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)
        text = output.decode().replace('\r\n', '\n')
        self.assertEqual(code, 2, text)
        self.assertTrue(text.endswith('ERROR: Passwords must match; no database was created.\n'), text)
        self.assertNotIn('typed', text)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.commands.exists())
        self.assertFalse(self.logins_file().exists())
        self.assertEqual(self.staged_files(), [])

    def test_missing_group_retains_new_database_without_partial_role_accounts(self):
        self.profile.write_text(self.profile.read_text().replace('example.group_manager', 'example.missing'))
        code, output = self.terminal('coffee', 'cc_dev_coffee')
        self.assertEqual(code, 1)
        self.assertTrue(output.endswith('ERROR: Development setup failed; the new database was retained.\n'))
        state = json.loads(self.state.read_text())
        self.assertEqual(set(state['users']), {'local_admin'})
        self.assertEqual(state['commits'], 0)


if __name__ == '__main__':
    unittest.main()
