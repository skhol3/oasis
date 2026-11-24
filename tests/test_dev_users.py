"""Fresh development initialization through the public CLI, isolated from Odoo/PG."""
import hashlib
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import sys
import unittest

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
        self.env.cr.data['users'][values['login']] = {
            'id': uid, 'password': digest(values['password']),
            'groups': values['group_ids'][0][2],
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
            'os.execv(sys.executable, [sys.executable, *sys.argv[1:]])\n')
        self.python.chmod(0o755)

    def command(self, *args):
        return [sys.executable, '-B', str(ROOT / 'odoo19'), '--project', str(self.root),
                'init-dev-database', *args]

    def invoke(self, *args):
        return subprocess.run(self.command(*args), input='', text=True,
                              capture_output=True, env=self.env, timeout=10)

    def terminal(self, *args):
        master, slave = pty.openpty()
        process = subprocess.Popen(self.command(*args), stdin=slave, stdout=slave,
                                   stderr=slave, env=self.env, start_new_session=True)
        os.close(slave)
        output = b''
        pending = b''
        prompts = [f'{kind} for {login}: '.encode()
                   for login in ('local_admin', 'planner', 'manager')
                   for kind in ('Password', 'Confirm password')]
        secrets = [hashlib.sha256(os.urandom(32)).hexdigest() for _ in range(3)]
        replies = [value for value in secrets for _ in range(2)]
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

    def test_requires_hidden_terminal_without_database_creation(self):
        result = self.invoke('coffee', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
            (2, '', 'ERROR: Password entry requires an interactive terminal.\n'))
        self.assertFalse(self.state.exists())
        self.assertFalse(self.commands.exists())

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

    def test_workspace_requires_hidden_terminal_without_database_creation(self):
        self.use_workspace()
        result = self.invoke('coffee', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
            (2, '', 'ERROR: Password entry requires an interactive terminal.\n'))
        self.assertFalse(self.state.exists())
        self.assertFalse(self.commands.exists())

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
