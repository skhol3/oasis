"""The optional machine file `$XDG_CONFIG_HOME/oasis/config.toml` (else `~/.config/oasis/config.toml`):
per-series defaults for the Odoo source that a workspace or checkout value overrides (v0.14.0 S2,
S3, S10).

Every machine file, home and project lives in a fresh system temp directory: XDG_CONFIG_HOME and
HOME point there, so the real ~/.config is never read. git runs with an empty global configuration
and a ceiling at the scratch directory.
"""
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

# Machine and workspace files must not be group-writable (trust rule); keep results independent of the umask.
os.umask(0o022)

ROOT = Path(__file__).resolve().parents[1]
READER = ROOT / 'tools' / 'config.py'
GIT = ['git', '-c', 'user.name=oasis tests', '-c', 'user.email=tests@example.invalid',
       '-c', 'init.defaultBranch=main', '-c', 'commit.gpgsign=false']
# A workspace that does not repeat the source paths: the machine file gives them.
WORKSPACE = '''workspace_version = 1
odoo_version = '19.0'

[tooling]
environment = 'environments/acme'
config = 'config/odoo.conf'
env_file = 'config/.env'
compose = 'config/compose.yml'
requirements = 'config/requirements'
addons_paths = ['.']
db_service = 'db'
dev_prefix = 'acme_dev_'
test_prefix = 'acme_test_'
'''
NAMED = WORKSPACE.replace("environment = 'environments/acme'\n", '') + '''
[environments.default]
path = 'environments/acme'
python = '3.12'

[environments.next]
path = 'environments/acme-next'
python = '3.13'
'''
ORIGIN_KEYS = ['MACHINE_FILE', 'MACHINE_ENVIRONMENTS_DIR', 'ODOO_SOURCE_FROM', 'ENTERPRISE_SOURCE_FROM',
               'PROJECT_ENVIRONMENT_FROM', 'CHECKOUT_SLUG_FROM']


class MachineConfigTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix='oasis-machine-')).resolve()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.config_home = self.scratch / 'xdg'
        self.machine = self.config_home / 'oasis' / 'config.toml'
        self.home = self.scratch / 'home'
        self.home.mkdir()
        self.project = self.scratch / 'acme'
        self.project.mkdir()
        self.workspace = self.project / 'oasis-workspace.toml'
        self.series = self.scratch / 'odoo' / '19.0'
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        self.env.update({'GIT_CEILING_DIRECTORIES': str(self.scratch), 'GIT_CONFIG_GLOBAL': os.devnull,
                         'GIT_CONFIG_NOSYSTEM': '1', 'PYTHONDONTWRITEBYTECODE': '1',
                         'XDG_CONFIG_HOME': str(self.config_home), 'HOME': str(self.home)})

    # -- fixtures ---------------------------------------------------------------------------

    def write_machine(self, text, path=None):
        path = path or self.machine
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def run_reader(self, *args, env=None):
        return subprocess.run([sys.executable, '-B', str(READER), *args], capture_output=True, text=True,
                              env=env or self.env)

    def output(self, root=None, env=None):
        result = self.run_reader(str(root or self.project), env=env)
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        return result.stdout

    def origins(self, root=None):
        result = self.run_reader('--origins', str(root or self.project))
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        return result.stdout

    def assert_rejected(self, message, root=None, env=None):
        for args in ((str(root or self.project),), ('--origins', str(root or self.project))):
            with self.subTest(args=args[0]):
                result = self.run_reader(*args, env=env)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', f'ERROR: {message}\n'))

    def declared(self, community, enterprise=None):
        """The same workspace declaring the source paths itself, absolute, without a machine file."""
        text = WORKSPACE.replace('[tooling]\n', f"[tooling]\ncommunity = '{community}'\n")
        if enterprise is not None:
            text = text.replace('[tooling]\n', f"[tooling]\nenterprise = '{enterprise}'\n")
        return text

    def expected_origins(self, **values):
        defaults = {'MACHINE_FILE': '', 'MACHINE_ENVIRONMENTS_DIR': '', 'ODOO_SOURCE_FROM': 'workspace',
                    'ENTERPRISE_SOURCE_FROM': '', 'PROJECT_ENVIRONMENT_FROM': 'workspace', 'CHECKOUT_SLUG_FROM': ''}
        defaults.update(values)
        return ''.join(f'{key}={shlex.quote(str(defaults[key]))}\n' for key in ORIGIN_KEYS)

    def git(self, cwd, *args):
        subprocess.run([*GIT, '-C', str(cwd), *args], check=True, capture_output=True, text=True, env=self.env)

    # -- defaults and precedence ------------------------------------------------------------

    def test_machine_file_gives_the_series_source_relative_to_itself_or_absolute(self):
        community = self.series / 'source' / 'odoo'
        enterprise = self.scratch / 'shared' / 'enterprise'
        self.write_machine("[series.\"19.0\"]\ncommunity = '../../odoo/19.0/source/odoo'\n"
                           f"enterprise = '{enterprise}'\n")
        self.workspace.write_text(WORKSPACE)
        with_machine = self.output()
        # The same assignments as a workspace declaring both paths, without a machine file.
        self.machine.unlink()
        self.workspace.write_text(self.declared(community, enterprise))
        self.assertEqual(with_machine, self.output())
        self.assertIn(f"ODOO_SOURCE={shlex.quote(str(community))}\n", with_machine)
        self.assertIn(f"ENTERPRISE_SOURCE={shlex.quote(str(enterprise))}\n", with_machine)
        self.assertIn(f"ODOO_BIN={shlex.quote(str(community / 'odoo-bin'))}\n", with_machine)

    def test_a_workspace_value_wins_over_the_machine_default(self):
        self.write_machine("[series.\"19.0\"]\ncommunity = '/machine/odoo'\nenterprise = '/machine/enterprise'\n")
        mine = self.scratch / 'mine' / 'odoo'
        self.workspace.write_text(self.declared(mine))
        lines = self.output().splitlines()
        self.assertIn(f'ODOO_SOURCE={shlex.quote(str(mine))}', lines)
        # Enterprise still comes from the machine file: only the declared value is the project's.
        self.assertIn('ENTERPRISE_SOURCE=/machine/enterprise', lines)
        # enterprise = false: this project has no Enterprise, whatever the machine file says.
        self.workspace.write_text(self.declared(mine).replace('[tooling]\n', '[tooling]\nenterprise = false\n'))
        self.assertNotIn('ENTERPRISE_SOURCE=', self.output())
        self.assertEqual(self.origins(), self.expected_origins(MACHINE_FILE=self.machine))

    def test_without_any_source_the_error_names_the_machine_file_and_the_series_key(self):
        # S10: the machine file is the default place for the source; the refusal says where to put it.
        self.workspace.write_text(WORKSPACE)
        self.assert_rejected(f'No Odoo source for 19.0: create the machine file {self.machine} with community '
                             f'under [series."19.0"], or set [tooling].community in {self.workspace}.')
        # Without XDG_CONFIG_HOME the path named is the home one.
        env = {key: value for key, value in self.env.items() if key != 'XDG_CONFIG_HOME'}
        self.assert_rejected(f'No Odoo source for 19.0: create the machine file '
                             f'{self.home / ".config/oasis/config.toml"} with community under [series."19.0"], '
                             f'or set [tooling].community in {self.workspace}.', env=env)
        # A machine file for the series without community, or without the series: set it there.
        for text in ("[series.\"19.0\"]\nenterprise = '/machine/enterprise'\n", ''):
            with self.subTest(text=text):
                self.write_machine(text)
                self.assert_rejected(f'No Odoo source for 19.0: set community under [series."19.0"] in the machine '
                                     f'file {self.machine}, or [tooling].community in {self.workspace}.')
        # A declared but invalid community keeps its own error, with or without the machine file.
        self.workspace.write_text(WORKSPACE.replace('[tooling]\n', "[tooling]\ncommunity = ''\n"))
        self.assert_rejected('Invalid tooling path: community.')
        self.machine.unlink()
        self.assert_rejected('Invalid tooling path: community.')

    def test_without_a_machine_file_a_workspace_that_declares_the_source_works_as_today(self):
        self.workspace.write_text(self.declared('/x/odoo', '/x/enterprise'))
        lines = self.output().splitlines()
        self.assertIn('ODOO_SOURCE=/x/odoo', lines)
        self.assertIn('ENTERPRISE_SOURCE=/x/enterprise', lines)
        # enterprise = false without a machine file is the same as no enterprise; true is not a path.
        self.workspace.write_text(self.declared('/x/odoo').replace('[tooling]\n', '[tooling]\nenterprise = false\n'))
        self.assertNotIn('ENTERPRISE_SOURCE=', self.output())
        self.workspace.write_text(self.declared('/x/odoo').replace('[tooling]\n', '[tooling]\nenterprise = true\n'))
        self.assert_rejected('Invalid tooling path: enterprise.')

    def test_without_xdg_config_home_the_file_is_under_the_home_config(self):
        self.workspace.write_text(WORKSPACE)
        fallback = self.home / '.config' / 'oasis' / 'config.toml'
        self.write_machine("[series.\"19.0\"]\ncommunity = '/home-config/odoo'\n", fallback)
        for xdg in (None, '', 'relative/xdg'):
            with self.subTest(xdg=xdg):
                env = {key: value for key, value in self.env.items() if key != 'XDG_CONFIG_HOME'}
                if xdg is not None:
                    env['XDG_CONFIG_HOME'] = xdg
                self.assertIn('ODOO_SOURCE=/home-config/odoo\n', self.output(env=env))
        # An absolute XDG_CONFIG_HOME is used instead of the home one.
        self.write_machine("[series.\"19.0\"]\ncommunity = '/xdg-config/odoo'\n")
        self.assertIn('ODOO_SOURCE=/xdg-config/odoo\n', self.output())

    def test_the_environments_default_is_reported_and_does_not_choose_an_environment(self):
        self.write_machine("[series.\"19.0\"]\ncommunity = '/machine/odoo'\nenvironments = 'environments'\n")
        self.workspace.write_text(WORKSPACE)
        self.assertIn(f"PROJECT_ENVIRONMENT={shlex.quote(str(self.project / 'environments/acme'))}\n", self.output())
        self.assertEqual(self.origins(), self.expected_origins(
            MACHINE_FILE=self.machine, MACHINE_ENVIRONMENTS_DIR=self.config_home / 'oasis' / 'environments',
            ODOO_SOURCE_FROM='machine'))

    # -- origins ----------------------------------------------------------------------------

    def test_origins_name_where_each_layered_value_came_from(self):
        self.workspace.write_text(self.declared('/x/odoo', '/x/enterprise'))
        self.assertEqual(self.origins(), self.expected_origins(ENTERPRISE_SOURCE_FROM='workspace'))
        self.write_machine("[series.\"19.0\"]\ncommunity = '/machine/odoo'\nenterprise = '/machine/enterprise'\n")
        self.workspace.write_text(NAMED)
        self.assertEqual(self.origins(), self.expected_origins(
            MACHINE_FILE=self.machine, ODOO_SOURCE_FROM='machine', ENTERPRISE_SOURCE_FROM='machine'))
        (self.project / 'oasis-checkout.toml').write_text("[tooling]\ncheckout_slug = 'mrp_2'\nenvironment = 'next'\n")
        self.assertEqual(self.origins(), self.expected_origins(
            MACHINE_FILE=self.machine, ODOO_SOURCE_FROM='machine', ENTERPRISE_SOURCE_FROM='machine',
            PROJECT_ENVIRONMENT_FROM='checkout', CHECKOUT_SLUG_FROM='checkout'))
        # The assignments themselves are unchanged by --origins being available.
        self.assertIn(f"PROJECT_ENVIRONMENT={shlex.quote(str(self.project / 'environments/acme-next'))}\n",
                      self.output())

    @unittest.skipUnless(shutil.which('git'), 'git is required')
    def test_a_linked_worktree_slug_is_derived(self):
        main = self.project / 'codigo' / 'acme'
        main.mkdir(parents=True)
        self.workspace.write_text(self.declared('/x/odoo'))
        (main / 'README.md').write_text('fixture\n')
        self.git(main, 'init', '-q')
        self.git(main, 'add', 'README.md')
        self.git(main, 'commit', '-q', '-m', 'init')
        self.git(main, 'worktree', 'add', '-q', '-b', 'feat', '../acme-feat')
        self.assertEqual(self.origins(main), self.expected_origins())
        self.assertEqual(self.origins(main.parent / 'acme-feat'), self.expected_origins(CHECKOUT_SLUG_FROM='derived'))

    def test_origins_usage_needs_an_absolute_root(self):
        usage = ('ERROR: Usage: config.py <absolute-project-root>\n'
                 '       config.py --origins <absolute-project-root>\n'
                 '       config.py --release <release.py> <series>\n')
        for args in (('--origins',), ('--origins', 'relative'), ('--origins', str(self.project), 'extra')):
            with self.subTest(args=args):
                result = self.run_reader(*args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', usage))

    # -- validation and trust ---------------------------------------------------------------

    def test_invalid_toml_and_unknown_keys_are_refused_naming_the_file(self):
        self.workspace.write_text(self.declared('/x/odoo'))
        file = self.machine
        for text, message in (
                ('[series\n', f'Invalid TOML in {file}.'),
                ("community = '/x'\n", f'Unknown key community in {file}; the machine file holds only '
                                       '[series."<version>"] tables.'),
                ('series = 1\n', f'Invalid [series] in {file}.'),
                ("[series.\"18.0\"]\ncommunity = '/x'\n", f'Unknown series "18.0" in {file}; supported: 19.0.'),
                ("[series]\n\"19.0\" = '/x'\n", f'Invalid [series."19.0"] in {file}.'),
                ("[series.\"19.0\"]\npython = '3.12'\n",
                 f'Unknown key series."19.0".python in {file}; use community, enterprise or environments.'),
                ("[series.\"19.0\"]\ncommunity = ''\n", f'Invalid machine path series."19.0".community in {file}.'),
                ("[series.\"19.0\"]\nenterprise = 7\n", f'Invalid machine path series."19.0".enterprise in {file}.'),
                ("[series.\"19.0\"]\nenvironments = \"a\\nb\"\n",
                 f'Invalid machine path series."19.0".environments in {file}.')):
            with self.subTest(text=text):
                self.write_machine(text)
                self.assert_rejected(message)

    # Ownership by another user cannot be created without root, so only the mode bits are
    # exercised here; the owner rule shares the workspace file's check.
    def test_a_group_or_other_writable_machine_file_or_directory_is_refused(self):
        self.workspace.write_text(WORKSPACE)
        self.write_machine("[series.\"19.0\"]\ncommunity = '/machine/odoo'\n")
        for target in (self.machine, self.machine.parent):
            for bit, name in ((stat.S_IWGRP, 'g+w'), (stat.S_IWOTH, 'o+w')):
                with self.subTest(target=str(target), bit=name):
                    mode = stat.S_IMODE(target.stat().st_mode)
                    target.chmod(mode | bit)
                    try:
                        self.assert_rejected(f'Refusing untrusted machine file {self.machine}: '
                                             f'{target} is writable by group or others.')
                    finally:
                        target.chmod(mode)
        self.assertIn('ODOO_SOURCE=/machine/odoo\n', self.output())


if __name__ == '__main__':
    unittest.main()
