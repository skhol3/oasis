"""Workspace file discovery: `oasis-workspace.toml` at the project root, checkouts at any depth.

Every project lives in a fresh system temp directory. git runs with explicit -c identity flags,
an empty global configuration and a ceiling at the scratch directory, so it never reads or
writes the user's configuration or a real project.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import importlib.util
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

# Workspace files must not be group-writable (trust rule); keep test results independent of the caller's umask.
os.umask(0o022)

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'odoo19'
READER = ROOT / 'tools' / 'config.py'
# A legacy profile: no longer read, only refused (and converted by oasis migrate).
LEGACY_PROFILE = "[tooling]\nversion = '19.0'\npython_version = '3.12'\n"
MODEL_INFO = ROOT / 'tests' / 'fixtures' / 'model_info'
GIT = ['git', '-c', 'user.name=oasis tests', '-c', 'user.email=tests@example.invalid',
       '-c', 'init.defaultBranch=main', '-c', 'commit.gpgsign=false']
WORKSPACE = '''workspace_version = 1
odoo_version = '19.0'

[tooling]
community = 'source/odoo'
environment = 'environments/acme'
config = 'config/odoo.conf'
env_file = 'config/.env'
compose = 'config/compose.yml'
requirements = 'config/requirements'
addons_paths = ['.', 'addons']
db_service = 'db'
dev_prefix = 'acme_dev_'
test_prefix = 'acme_test_'
logs = 'logs'
'''
CHECKOUT_ONLY = 'oasis-checkout.toml may only set [tooling].checkout_slug and [tooling].environment: '
# The same workspace with named environments instead of [tooling].environment.
NAMED = WORKSPACE.replace("environment = 'environments/acme'\n", '') + '''
[environments.default]
path = 'environments/acme'
python = '3.12'

[environments.next]
path = 'environments/acme-next'
python = '3.13'
'''


@unittest.skipUnless(shutil.which('git'), 'git is required')
class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix='oasis-workspace-')).resolve()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        self.env.update({'GIT_CEILING_DIRECTORIES': str(self.scratch), 'GIT_CONFIG_GLOBAL': os.devnull,
                         'GIT_CONFIG_NOSYSTEM': '1', 'PYTHONDONTWRITEBYTECODE': '1',
                         # No machine file (never the real ~/.config): these checks prove the
                         # behaviour without one.
                         'XDG_CONFIG_HOME': str(self.scratch / 'xdg')})
        self.project = self.scratch / 'acme'
        self.workspace = self.project / 'oasis-workspace.toml'
        self.main = self.project / 'codigo' / 'acme'

    # -- fixtures ---------------------------------------------------------------------------

    def git(self, cwd, *args):
        result = subprocess.run([*GIT, '-C', str(cwd), *args], check=True, capture_output=True,
                                text=True, env=self.env)
        return result.stdout.strip()

    def layout(self, workspace=WORKSPACE):
        """<project>/oasis-workspace.toml and the main checkout <project>/codigo/acme (git)."""
        self.main.mkdir(parents=True)
        self.workspace.write_text(workspace)
        (self.main / 'README.md').write_text('fixture\n')
        self.git(self.main, 'init', '-q')
        self.git(self.main, 'add', 'README.md')
        self.git(self.main, 'commit', '-q', '-m', 'init')
        return self.main

    def linked(self, name='acme-feat', branch='feat'):
        self.git(self.main, 'worktree', 'add', '-q', '-b', branch, '../' + name)
        return self.main.parent / name

    def run_reader(self, root):
        return subprocess.run([sys.executable, '-B', str(READER), str(root)],
                              capture_output=True, text=True, env=self.env)

    def assignments(self, root):
        result = self.run_reader(root)
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        return result.stdout.splitlines()

    def output(self, root):
        result = self.run_reader(root)
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        return result.stdout

    def assert_rejected(self, root, message):
        result = self.run_reader(root)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', f'ERROR: {message}\n'))

    def expected(self, checkout, kind, slug, environment='', python='3.12', path='environments/acme',
                 data_dir='', agent_destructive='ask'):
        project = self.project
        values = {
            'PROJECT_ROOT': str(checkout), 'PROJECT_NAME': checkout.name,
            'DEV_PREFIX': 'acme_dev_', 'TEST_PREFIX': 'acme_test_', 'TEST_DATABASE': '',
            'ODOO_SOURCE': str(project / 'source/odoo'),
            'PROJECT_ENVIRONMENT': str(project / path),
            'ODOO_CONFIG': str(project / 'config/odoo.conf'), 'ENV_FILE': str(project / 'config/.env'),
            'COMPOSE_FILE': str(project / 'config/compose.yml'),
            'REQUIREMENTS_DIR': str(project / 'config/requirements'),
            'ADDON_ROOTS': f'{checkout}\n{checkout / "addons"}',
            'DB_SERVICE': 'db',
            'PYTHON': str(project / path / 'bin/python'),
            'ODOO_BIN': str(project / 'source/odoo/odoo-bin'),
            'ENVIRONMENTS_DIR': str(project / 'environments'),
            'CHECKOUT_KIND': kind, 'CHECKOUT_SLUG': slug, 'CHECKOUT_MAIN_ROOT': str(self.main),
            'LOGS_DIR': str(project / 'logs'), 'WORKSPACE_ROOT': str(project),
            # Appended after WORKSPACE_ROOT: the series' Odoo options and the environment.
            'ODOO_VERSION': '19.0', 'ODOO_SECOND_PORT_OPTION': '--gevent-port', 'ODOO_DEMO_OFF_ARGS': '--without-demo',
            'ENVIRONMENT_NAME': environment, 'PYTHON_VERSION': python,
            # Appended after them: [tooling].data_dir, empty when absent.
            'DATA_DIR': data_dir,
            # Appended last: [tooling].agent_destructive, ask when absent.
            'AGENT_DESTRUCTIVE': agent_destructive,
        }
        # ADDON_ROOTS spans two lines (a newline-separated list inside one quoted value).
        return ''.join(f'{name}={shlex.quote(value)}\n' for name, value in values.items())

    # -- config.py --------------------------------------------------------------------------

    def test_main_checkout_reads_the_workspace_at_the_project_root(self):
        main = self.layout()
        self.assertEqual(self.output(main), self.expected(main, 'main', ''))

    def test_data_dir_resolves_from_the_workspace_for_every_checkout(self):
        main = self.layout(WORKSPACE + "data_dir = 'data'\n")
        linked = self.linked()
        data = str(self.project / 'data')
        self.assertEqual(self.output(main), self.expected(main, 'main', '', data_dir=data))
        self.assertEqual(self.output(linked), self.expected(linked, 'linked', 'feat', data_dir=data))
        self.workspace.write_text(WORKSPACE + 'data_dir = ""\n')
        self.assert_rejected(main, 'Invalid tooling path: data_dir.')

    def test_agent_destructive_applies_to_every_checkout_and_only_the_workspace_sets_it(self):
        main = self.layout(WORKSPACE + "agent_destructive = 'deny'\n")
        linked = self.linked()
        self.assertEqual(self.output(main), self.expected(main, 'main', '', agent_destructive='deny'))
        self.assertEqual(self.output(linked), self.expected(linked, 'linked', 'feat', agent_destructive='deny'))
        self.workspace.write_text(WORKSPACE + "agent_destructive = 'sometimes'\n")
        self.assert_rejected(main, 'Invalid tooling agent_destructive: use ask, deny or allow.')
        # A checkout cannot loosen it: oasis-checkout.toml refuses the key.
        self.workspace.write_text(WORKSPACE)
        (linked / 'oasis-checkout.toml').write_text("[tooling]\nagent_destructive = 'allow'\n")
        self.assert_rejected(linked, CHECKOUT_ONLY + 'tooling.agent_destructive')

    def test_linked_worktree_needs_no_copy_of_the_workspace_file(self):
        self.layout()
        linked = self.linked()
        self.assertFalse((linked / '.odoo19-agent.toml').exists())
        self.assertEqual(self.output(linked), self.expected(linked, 'linked', 'feat'))

    def test_checkout_file_sets_only_the_slug(self):
        main = self.layout()
        (main / 'oasis-checkout.toml').write_text("[tooling]\ncheckout_slug = 'mrp_2'\n")
        self.assertEqual(self.output(main), self.expected(main, 'main', 'mrp_2'))
        for text in ('', '[tooling]\n'):
            with self.subTest(text=text):
                (main / 'oasis-checkout.toml').write_text(text)
                self.assertEqual(self.output(main), self.expected(main, 'main', ''))
        for value in ("''", "'Upper'", '7'):
            with self.subTest(value=value):
                (main / 'oasis-checkout.toml').write_text(f'[tooling]\ncheckout_slug = {value}\n')
                self.assert_rejected(main, 'Invalid tooling checkout slug.')

    def test_checkout_file_refuses_every_other_key(self):
        main = self.layout()
        for text, key in (("[tooling]\nlogs = 'mine'\n", 'tooling.logs'),
                          ("[tooling]\ncheckout_slug = 'a'\ndev_prefix = 'x_dev_'\n", 'tooling.dev_prefix'),
                          ('workspace_version = 1\n', 'workspace_version'),
                          ("[odoo]\nversion = '19.0'\n", 'odoo'),
                          ('tooling = 1\n', 'tooling')):
            with self.subTest(key=key):
                (main / 'oasis-checkout.toml').write_text(text)
                self.assert_rejected(main, CHECKOUT_ONLY + key)

    def test_invalid_files_are_named(self):
        main = self.layout()
        (main / 'oasis-checkout.toml').write_text('[tooling\n')
        self.assert_rejected(main, f'Invalid TOML in {main / "oasis-checkout.toml"}.')
        (main / 'oasis-checkout.toml').unlink()
        self.workspace.write_text('workspace_version = \n')
        self.assert_rejected(main, f'Invalid TOML in {self.workspace}.')

    # Ownership by another user cannot be created without root, so only the mode bits are
    # exercised here; the owner rule shares the same check and message shape.
    def assert_writable_refused(self, main, file, targets):
        for target in targets:
            for bit, name in ((stat.S_IWGRP, 'g+w'), (stat.S_IWOTH, 'o+w')):
                with self.subTest(target=str(target), bit=name):
                    mode = stat.S_IMODE(target.stat().st_mode)
                    target.chmod(mode | bit)
                    try:
                        self.assert_rejected(main, f'Refusing untrusted workspace file {file}: '
                                                   f'{target} is writable by group or others.')
                    finally:
                        target.chmod(mode)

    def test_group_or_other_writable_workspace_file_is_refused(self):
        main = self.layout()
        before = self.workspace.read_bytes()
        self.assert_writable_refused(main, self.workspace, (self.workspace, self.project))
        self.assertEqual(self.workspace.read_bytes(), before)
        # Back to the owner's own modes, the same workspace is accepted again.
        self.assertEqual(self.output(main), self.expected(main, 'main', ''))

    def test_group_or_other_writable_checkout_file_is_refused(self):
        main = self.layout()
        checkout = main / 'oasis-checkout.toml'
        checkout.write_text("[tooling]\ncheckout_slug = 'mrp_2'\n")
        self.assert_writable_refused(main, checkout, (checkout, main))
        self.assertEqual(self.output(main), self.expected(main, 'main', 'mrp_2'))
        # Without a checkout file, the checkout directory's mode is not a workspace file's.
        checkout.unlink()
        mode = stat.S_IMODE(main.stat().st_mode)
        main.chmod(mode | stat.S_IWGRP)
        try:
            self.assertEqual(self.output(main), self.expected(main, 'main', ''))
        finally:
            main.chmod(mode)

    def test_writable_directories_above_the_workspace_are_not_checked(self):
        # Only the file and its own directory: the scratch parent (like /tmp) may be shared.
        main = self.layout()
        mode = stat.S_IMODE(self.scratch.stat().st_mode)
        self.scratch.chmod(mode | stat.S_IWOTH)
        try:
            self.assertEqual(self.output(main), self.expected(main, 'main', ''))
        finally:
            self.scratch.chmod(mode)

    def refusal(self, profile):
        return (f'{profile} is the old profile format, no longer read: run oasis migrate --plan to see its '
                'conversion to oasis-workspace.toml, then oasis migrate --apply.')

    def test_a_legacy_profile_in_the_checkout_is_refused_next_to_the_workspace(self):
        main = self.layout()
        profile = main / '.odoo19-agent.toml'
        profile.write_text(LEGACY_PROFILE)
        self.assert_rejected(main, self.refusal(profile))
        # The checkout file does not change that.
        (main / 'oasis-checkout.toml').write_text("[tooling]\ncheckout_slug = 'mrp_2'\n")
        self.assert_rejected(main, self.refusal(profile))

    def test_a_profile_on_the_way_no_longer_stops_discovery(self):
        main = self.layout()
        (self.project / 'codigo' / '.odoo19-agent.toml').write_text(LEGACY_PROFILE)
        self.assertEqual(self.output(main), self.expected(main, 'main', ''))

    def test_without_a_workspace_file_the_missing_configuration_error_names_the_checkout(self):
        main = self.layout()
        self.workspace.unlink()
        self.assert_rejected(main, f'Missing tooling configuration: no oasis-workspace.toml at or above {main}.')

    def test_unsupported_workspace_version_is_refused(self):
        main = self.layout()
        for line, shown in (('workspace_version = 2\n', '2'), ('workspace_version = "1"\n', '"1"'),
                            ('workspace_version = true\n', 'true'), ('', '(missing)')):
            with self.subTest(shown=shown):
                self.workspace.write_text(WORKSPACE.replace('workspace_version = 1\n', line))
                self.assert_rejected(main, f'Unsupported workspace_version {shown} in {self.workspace}.')

    def test_unsupported_odoo_version_is_refused(self):
        main = self.layout()
        for line, shown in (("odoo_version = '18.0'\n", '"18.0"'), ("odoo_version = '12.0'\n", '"12.0"'),
                            ('odoo_version = 19\n', '19'), ('', '(missing)')):
            with self.subTest(shown=shown):
                self.workspace.write_text(WORKSPACE.replace("odoo_version = '19.0'\n", line))
                self.assert_rejected(main, f'Unsupported odoo_version {shown} in {self.workspace}; '
                                           'supported: 19.0.')

    def test_derived_and_checkout_keys_are_refused_in_the_workspace(self):
        main = self.layout()
        for key, value in (('version', "'19.0'"), ('python_version', "'3.12'")):
            with self.subTest(key=key):
                self.workspace.write_text(WORKSPACE + f'{key} = {value}\n')
                self.assert_rejected(main, f'[tooling].{key} is derived in a workspace; '
                                           f'remove it from {self.workspace}.')
        self.workspace.write_text(WORKSPACE + "checkout_slug = 'all'\n")
        self.assert_rejected(main, f'[tooling].checkout_slug belongs in a checkout\'s oasis-checkout.toml, '
                                   f'not in {self.workspace}.')

    def test_workspace_tooling_keeps_its_validation(self):
        main = self.layout()
        self.workspace.write_text(WORKSPACE.replace("test_prefix = 'acme_test_'", "test_prefix = 'other_test_'"))
        self.assert_rejected(main, 'Unsafe tooling database prefixes.')
        self.workspace.write_text(WORKSPACE + "[odoo]\nversion = '18.0'\n")
        self.assert_rejected(main, 'Conflicting advisory and tooling values: odoo.version.')
        self.workspace.write_text(WORKSPACE + "[odoo]\nversion = '19.0'\n")
        self.assertEqual(self.output(main), self.expected(main, 'main', ''))

    def test_single_environment_python_comes_from_the_series_table(self):
        # [tooling].environment declares no Python: config.py takes the series' python_default
        # from tools/odoo_versions.py, not a value of its own.
        main = self.layout()
        spec = importlib.util.spec_from_file_location('oasis_config_under_test', READER)
        config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config)
        table = config.versions().CAPABILITIES['19.0']
        self.assertEqual(config.load(main)['PYTHON_VERSION'], '3.12')
        table['python_default'] = '3.13'
        try:
            self.assertEqual(config.load(main)['PYTHON_VERSION'], '3.13')
        finally:
            table['python_default'] = '3.12'

    def shipped_example(self):
        """The shipped example and, in this test's scratch XDG_CONFIG_HOME, the machine file it
        documents (its commented [series."19.0"] block), which gives the source (v0.14.0 S10)."""
        raw = (ROOT / 'odoo19-environment/assets/oasis-workspace.example.toml').read_text()
        block = re.search(r'^#   \[series\."19\.0"\]\n(?:#   [a-z]+ = .*\n)+', raw, re.MULTILINE)
        self.assertIsNotNone(block, raw)
        machine = self.scratch / 'xdg' / 'oasis' / 'config.toml'
        machine.parent.mkdir(mode=0o700, parents=True)
        machine.write_text(re.sub(r'^#   ', '', block.group(0), flags=re.MULTILINE))
        machine.chmod(0o600)
        return raw

    def test_shipped_example_is_accepted(self):
        raw = self.shipped_example()
        main = self.layout(raw)
        lines = self.output(main).splitlines()
        # The source comes from the machine file the example documents.
        self.assertIn('ODOO_SOURCE=/srv/odoo/19.0/source/odoo', lines)
        self.assertIn('ENTERPRISE_SOURCE=/srv/odoo/19.0/source/enterprise', lines)
        self.assertEqual(lines[-8:], ['WORKSPACE_ROOT=' + shlex.quote(str(self.project)), 'ODOO_VERSION=19.0',
                                      'ODOO_SECOND_PORT_OPTION=--gevent-port', 'ODOO_DEMO_OFF_ARGS=--without-demo',
                                      "ENVIRONMENT_NAME=''", 'PYTHON_VERSION=3.12', "DATA_DIR=''",
                                      'AGENT_DESTRUCTIVE=ask'])
        self.assertIn('ODOO_CONFIG=' + shlex.quote(str(self.project / 'config/odoo.conf')), lines)
        self.assertIn('ADDON_ROOTS=' + shlex.quote(str(main)), lines)
        # Uncommenting the documented overrides makes the project's source win over the machine's.
        self.assertIn("# community = 'source/odoo'\n", raw)
        self.assertIn("# enterprise = 'source/enterprise'\n", raw)
        self.workspace.write_text(raw.replace("# community = 'source/odoo'\n", "community = 'source/odoo'\n")
                                  .replace("# enterprise = 'source/enterprise'\n", 'enterprise = false\n'))
        lines = self.output(main).splitlines()
        self.assertIn('ODOO_SOURCE=' + shlex.quote(str(self.project / 'source/odoo')), lines)
        self.assertFalse(any(line.startswith('ENTERPRISE_SOURCE=') for line in lines), lines)

    def test_shipped_example_documents_named_environments(self):
        # Uncommenting the documented [environments.default] block in place of
        # [tooling].environment gives a working workspace that selects it.
        raw = self.shipped_example()
        block = re.search(r'^# \[environments\.default\]\n(?:# [a-z]+ = .*\n)+', raw, re.MULTILINE)
        self.assertIsNotNone(block, raw)
        self.assertIn("environment = 'environments/acme'\n", raw)
        named = (raw.replace("environment = 'environments/acme'\n", '')
                 + re.sub(r'^# ', '', block.group(0), flags=re.MULTILINE))
        main = self.layout(named)
        lines = self.output(main).splitlines()
        self.assertEqual(lines[-4:], ['ENVIRONMENT_NAME=default', 'PYTHON_VERSION=3.12', "DATA_DIR=''",
                                      'AGENT_DESTRUCTIVE=ask'])
        self.assertIn('PROJECT_ENVIRONMENT=' + shlex.quote(str(self.project / 'environments/acme')), lines)
        self.assertRegex(raw, r"(?m)^#\s+environment = '[a-z_]+'$")

    def test_shipped_example_documents_agent_destructive(self):
        # Uncommenting the documented agent_destructive line with each value is accepted.
        raw = self.shipped_example()
        self.assertIn("# agent_destructive = 'ask'\n", raw)
        main = self.layout(raw)
        for value in ('ask', 'deny', 'allow'):
            with self.subTest(value=value):
                self.workspace.write_text(raw.replace("# agent_destructive = 'ask'\n", f"agent_destructive = '{value}'\n"))
                self.assertEqual(self.output(main).splitlines()[-1], f'AGENT_DESTRUCTIVE={value}')

    # -- named environments -----------------------------------------------------------------

    def test_named_environments_use_default_without_a_selection(self):
        main = self.layout(NAMED)
        self.assertEqual(self.output(main), self.expected(main, 'main', '', 'default'))
        linked = self.linked()
        self.assertEqual(self.output(linked), self.expected(linked, 'linked', 'feat', 'default'))

    def test_checkout_file_selects_a_named_environment(self):
        main = self.layout(NAMED)
        checkout = main / 'oasis-checkout.toml'
        checkout.write_text("[tooling]\nenvironment = 'next'\n")
        self.assertEqual(self.output(main), self.expected(main, 'main', '', 'next', '3.13', 'environments/acme-next'))
        checkout.write_text("[tooling]\ncheckout_slug = 'mrp_2'\nenvironment = 'next'\n")
        self.assertEqual(self.output(main), self.expected(main, 'main', 'mrp_2', 'next', '3.13',
                                                          'environments/acme-next'))
        # Only this checkout: a worktree without its own selection keeps the default.
        linked = self.linked()
        self.assertEqual(self.output(linked), self.expected(linked, 'linked', 'feat', 'default'))

    def test_unknown_environment_lists_the_declared_names(self):
        main = self.layout(NAMED)
        checkout = main / 'oasis-checkout.toml'
        for value, shown in (("'nope'", '"nope"'), ("'Default'", '"Default"'), ('7', '7')):
            with self.subTest(value=value):
                checkout.write_text(f'[tooling]\nenvironment = {value}\n')
                self.assert_rejected(main, f'Unknown environment {shown}; {self.workspace} declares: default, next.')
        checkout.unlink()
        # Without a selection the default must exist.
        self.workspace.write_text(NAMED.replace('[environments.default]', '[environments.old]'))
        self.assert_rejected(main, f'Unknown environment "default"; {self.workspace} declares: old, next.')
        # A selection needs [environments]; [tooling].environment has no name.
        self.workspace.write_text(WORKSPACE)
        checkout.write_text("[tooling]\nenvironment = 'default'\n")
        self.assert_rejected(main, f'Unknown environment "default"; {self.workspace} declares: (none).')

    def test_environment_python_must_be_in_the_odoo_range(self):
        main = self.layout(NAMED)
        for value, shown in (("'3.9'", '"3.9"'), ("'3.15'", '"3.15"'), ("'3.12.1'", '"3.12.1"'),
                             ('3.12', '3.12'), (None, '(missing)')):
            with self.subTest(value=value):
                line = f'python = {value}\n' if value is not None else ''
                self.workspace.write_text(NAMED.replace("python = '3.12'\n", line))
                self.assert_rejected(main, f'Unsupported python {shown} for environment "default" in '
                                           f'{self.workspace}; Odoo 19.0 supports 3.10 to 3.14.')
        for python in ('3.10', '3.14'):
            with self.subTest(python=python):
                self.workspace.write_text(NAMED.replace("python = '3.12'", f"python = '{python}'"))
                self.assertEqual(self.output(main), self.expected(main, 'main', '', 'default', python))

    def test_environment_path_keeps_the_environment_rules(self):
        main = self.layout(NAMED)
        for path in ('.', 'codigo', 'codigo/acme', '/', 'source/odoo', 'source', 'other/acme'):
            with self.subTest(path=path):
                self.workspace.write_text(NAMED.replace("path = 'environments/acme'\n", f"path = '{path}'\n"))
                self.assert_rejected(main, 'Unsafe tooling environment target.')
        for line in ("path = ''\n", 'path = 7\n', 'path = "a\\u0000b"\n', ''):
            with self.subTest(line=line):
                self.workspace.write_text(NAMED.replace("path = 'environments/acme'\n", line))
                self.assert_rejected(main, 'Invalid tooling path: environment.')
        # The advisory [environment].python still has to agree with the selected path.
        self.workspace.write_text(NAMED + "[environment]\npython = 'environments/other/bin/python'\n")
        self.assert_rejected(main, 'Conflicting advisory and tooling values: environment.python.')

    def test_environments_table_shape_is_checked(self):
        main = self.layout(NAMED)
        self.workspace.write_text('environments = 1\n' + WORKSPACE.replace("environment = 'environments/acme'\n", ''))
        self.assert_rejected(main, f'Invalid [environments] in {self.workspace}.')
        self.workspace.write_text(WORKSPACE.replace("environment = 'environments/acme'\n", '')
                                  + "[environments]\ndefault = 'environments/acme'\n")
        self.assert_rejected(main, f'Invalid environment "default" in {self.workspace}.')
        self.workspace.write_text(NAMED.replace("[tooling]\n", "[tooling]\nenvironment = 'environments/acme'\n"))
        self.assert_rejected(main, f'Set either [tooling].environment or [environments] in {self.workspace}, '
                                   'not both.')

    # -- paths and the environment rule (docs/new-workspace.md) -----------------------------

    def line(self, name, value):
        return f'{name}={shlex.quote(str(value))}'

    def test_absolute_paths_are_accepted(self):
        main = self.layout()
        shared = self.scratch / 'odoo' / '19.0'
        logs = self.scratch / 'logs' / 'acme'
        self.workspace.write_text(WORKSPACE.replace("community = 'source/odoo'", f"community = '{shared}/source/odoo'")
                                  .replace("environment = 'environments/acme'",
                                           f"environment = '{shared}/environments/acme'")
                                  .replace("logs = 'logs'", f"logs = '{logs}'")
                                  .replace("addons_paths = ['.', 'addons']", f"addons_paths = ['.', '{shared}/oca']"))
        # Whole lines of the output: ADDON_ROOTS spans two lines inside one quoted value.
        text = '\n' + self.output(main)
        for name, value in (('ODOO_SOURCE', shared / 'source/odoo'),
                            ('PROJECT_ENVIRONMENT', shared / 'environments/acme'),
                            ('PYTHON', shared / 'environments/acme/bin/python'),
                            ('ODOO_BIN', shared / 'source/odoo/odoo-bin'),
                            ('ENVIRONMENTS_DIR', shared / 'environments'),
                            ('LOGS_DIR', logs),
                            # An absolute addon root is the same folder for every checkout.
                            ('ADDON_ROOTS', f'{main}\n{shared}/oca'),
                            # Relative values keep resolving from the workspace file's directory.
                            ('ODOO_CONFIG', self.project / 'config/odoo.conf')):
            with self.subTest(name=name):
                self.assertIn('\n' + self.line(name, value) + '\n', text)
        # A named environment's path may be absolute as well.
        self.workspace.write_text(NAMED.replace("path = 'environments/acme'",
                                                f"path = '{shared}/environments/acme'"))
        lines = self.assignments(main)
        self.assertIn(self.line('PROJECT_ENVIRONMENT', shared / 'environments/acme'), lines)
        self.assertIn('ENVIRONMENT_NAME=default', lines)

    def test_environment_rule_accepts_an_environments_parent_and_refuses_the_rest(self):
        main = self.layout()
        accepted = (f'{self.scratch}/x/environments/acme', f'{self.scratch}/x/odoo-environments/acme',
                    '../environments/acme')
        for path in accepted:
            with self.subTest(accepted=path):
                self.workspace.write_text(WORKSPACE.replace("environment = 'environments/acme'",
                                                            f"environment = '{path}'"))
                self.assertIn(self.line('PROJECT_ENVIRONMENT', (self.project / path).resolve()),
                              self.assignments(main))
        refused = ('/opt/venvs/acme',                           # parent venvs does not end in environments
                   'environments/acme/venv',                    # parent acme: only the direct parent counts
                   f'{self.project}/source/odoo',               # is the Odoo source
                   f'{self.project}/source',                    # contains the Odoo source
                   '.')                                         # contains the checkout
        for path in refused:
            with self.subTest(refused=path):
                self.workspace.write_text(WORKSPACE.replace("environment = 'environments/acme'",
                                                            f"environment = '{path}'"))
                self.assert_rejected(main, 'Unsafe tooling environment target.')

    def test_environment_inside_a_checkout_serves_only_that_checkout(self):
        main = self.layout(WORKSPACE.replace("environment = 'environments/acme'",
                                             "environment = 'codigo/acme/.venv'"))
        self.assertIn(self.line('PROJECT_ENVIRONMENT', main / '.venv'), self.assignments(main))
        linked = self.linked()
        self.assert_rejected(linked, 'Unsafe tooling environment target.')

    def test_home_shorthand_is_not_expanded(self):
        # TOML values are taken literally: ~ is a folder below the workspace directory.
        main = self.layout(WORKSPACE.replace("environment = 'environments/acme'",
                                             "environment = '~/environments/acme'"))
        self.assertIn(self.line('PROJECT_ENVIRONMENT', self.project / '~/environments/acme'),
                      self.assignments(main))

    # -- the guide's own examples -----------------------------------------------------------

    def guide_block(self, first_line):
        """The fenced toml block of docs/new-workspace.md that starts with first_line."""
        guide = (ROOT / 'docs' / 'new-workspace.md').read_text(encoding='utf-8')
        match = re.search(r'^```toml\n(' + re.escape(first_line) + r'\n.*?)^```$', guide, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(match, first_line)
        return match.group(1)

    def test_guide_follows_the_declared_python_and_checks_the_locks_with_full(self):
        guide = (ROOT / 'docs' / 'new-workspace.md').read_text(encoding='utf-8')
        # The commands take the environment's declared Python, never a fixed one.
        self.assertEqual(re.findall(r'--python(?:-version)? 3\.\d+', guide), [])
        self.assertIn('--python "$python"', guide)
        self.assertIn('--python-version "$python"', guide)
        # Checking the installed packages against the locks is --full; --quick skips it.
        self.assertIn('check-environment --full', guide)
        # Each block that uses "$python" sets it first: a block pasted in a new shell works alone.
        blocks = re.findall(r'^ *```bash\n(.*?)^ *```$', guide, re.MULTILINE | re.DOTALL)
        using = [block for block in blocks if '"$python"' in block]
        self.assertGreaterEqual(len(using), 2)
        for block in using:
            with self.subTest(block=block.splitlines()[0].strip()):
                lines = [line.strip() for line in block.splitlines()]
                first_use = next(index for index, line in enumerate(lines) if '"$python"' in line)
                self.assertTrue(any(re.fullmatch(r'python=3\.\d+', line) for line in lines[:first_use]), block)

    def test_guide_workspace_resolves_to_its_example_tree(self):
        series = self.scratch / 'odoo' / '19.0'
        self.project = series / 'projects' / 'acme'
        self.workspace = self.project / 'oasis-workspace.toml'
        self.main = self.project / 'codigo' / 'acme'
        workspace = self.guide_block('# projects/acme/oasis-workspace.toml')
        main = self.layout(workspace)
        linked = self.linked('acme-shop-feature', 'shop-feature')
        for checkout, slug in ((main, ''), (linked, 'shop_feature')):
            with self.subTest(checkout=checkout.name):
                lines = self.assignments(checkout)
                for name, value in (('ODOO_SOURCE', series / 'source/odoo'),
                                    ('PROJECT_ENVIRONMENT', series / 'environments/acme'),
                                    ('ODOO_CONFIG', self.project / 'config/odoo.conf'),
                                    ('COMPOSE_FILE', self.project / 'config/compose.yml'),
                                    ('REQUIREMENTS_DIR', self.project / 'config/requirements'),
                                    ('ADDON_ROOTS', checkout), ('CHECKOUT_SLUG', slug),
                                    ('LOGS_DIR', self.project / 'logs'), ('DATA_DIR', self.project / 'data'),
                                    ('WORKSPACE_ROOT', self.project)):
                    self.assertIn(self.line(name, value), lines)
        # The named form: the guide's [environments] block in place of [tooling].environment,
        # and the guide's oasis-checkout.toml selecting the second one in the worktree.
        environment = re.search(r"^environment = '[^']*'\n", workspace, re.MULTILINE)
        self.assertIsNotNone(environment, workspace)
        named = self.guide_block('# In oasis-workspace.toml, in place of [tooling].environment:')
        self.workspace.write_text(workspace.replace(environment.group(0), '') + '\n' + named)
        lines = self.assignments(main)
        self.assertIn(self.line('PROJECT_ENVIRONMENT', series / 'environments/acme'), lines)
        self.assertIn('ENVIRONMENT_NAME=default', lines)
        (linked / 'oasis-checkout.toml').write_text(self.guide_block('# codigo/acme-shop-feature/oasis-checkout.toml'))
        lines = self.assignments(linked)
        self.assertIn(self.line('PROJECT_ENVIRONMENT', series / 'environments/acme-next'), lines)
        self.assertEqual(lines[-4:-2], ['ENVIRONMENT_NAME=next', 'PYTHON_VERSION=3.13'])

    # -- odoo19 entry point -----------------------------------------------------------------

    def invoke(self, project, *args):
        return subprocess.run([sys.executable, '-B', str(CLI), '--project', str(project), *args],
                              capture_output=True, text=True, env=self.env, cwd=self.scratch)

    def invoke_in(self, cwd, *args, program='odoo19'):
        """The entry point without --project, run from cwd (v0.14.0 S8)."""
        return subprocess.run([sys.executable, '-B', str(ROOT / program), *args],
                              capture_output=True, text=True, env=self.env, cwd=cwd)

    def test_entry_point_without_project_uses_the_git_top_level_of_the_current_directory(self):
        main = self.layout()
        shutil.copytree(MODEL_INFO / 'source', self.project / 'source')
        linked = self.linked()
        for checkout in (main, linked):
            shutil.copytree(MODEL_INFO / 'project' / 'addons', checkout / 'addons')
        for checkout in (main, linked):
            explicit = self.invoke(checkout, 'model-info', 'coffee.order')
            self.assertEqual((explicit.returncode, explicit.stderr), (0, ''))
            for cwd in (checkout, checkout / 'addons' / 'coffee_shop'):
                for program in ('oasis', 'odoo19'):
                    with self.subTest(cwd=str(cwd), program=program):
                        result = self.invoke_in(cwd, 'model-info', 'coffee.order', program=program)
                        self.assertEqual((result.returncode, result.stdout, result.stderr),
                                         (explicit.returncode, explicit.stdout, explicit.stderr))

    def test_entry_point_without_project_refuses_an_unconfigured_checkout_like_an_explicit_one(self):
        main = self.layout()
        self.workspace.unlink()
        (main / 'sub').mkdir()
        explicit = self.invoke(main, 'model-info', 'coffee.order')
        result = self.invoke_in(main / 'sub', 'model-info', 'coffee.order')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            2, '', f'ERROR: Missing tooling configuration: no oasis-workspace.toml at or above {main}.\n'))
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (explicit.returncode, explicit.stdout, explicit.stderr))

    def test_entry_point_without_project_stops_when_git_fails_in_a_repository(self):
        # A checkout whose git cannot answer is not taken for a project outside git.
        broken = self.scratch / 'broken'
        (broken / 'sub').mkdir(parents=True)
        (broken / '.git').write_text(f'gitdir: {self.scratch / "missing"}\n')
        (broken / 'oasis-workspace.toml').write_text(WORKSPACE)
        result = self.invoke_in(broken / 'sub', 'model-info', 'coffee.order')
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.assertRegex(result.stderr, r'\AERROR: Cannot determine the project root of '
                         + re.escape(str(broken / 'sub')) + r': git failed \(.+\); pass --project\.\n\Z')

    def test_entry_point_runs_a_command_in_a_linked_worktree(self):
        self.layout()
        shutil.copytree(MODEL_INFO / 'source', self.project / 'source')
        linked = self.linked()
        shutil.copytree(MODEL_INFO / 'project' / 'addons', linked / 'addons')
        result = self.invoke(linked, 'model-info', 'coffee.order')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(
            "model: coffee.order — Coffee Order (table coffee_order, order 'date desc, id')\n"
            'defined: coffee coffee/models/coffee_order.py:4 inherits mail.thread\n'), result.stdout)
        # coffee_shop comes from the checkout's addons, resolved from the checkout root.
        self.assertIn('extended by (2): coffee_loyalty, coffee_shop(+mail.activity.mixin)\n', result.stdout)

    def test_entry_point_reports_a_missing_workspace_file(self):
        main = self.layout()
        self.workspace.unlink()
        result = self.invoke(main, 'model-info', 'coffee.order')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            2, '', f'ERROR: Missing tooling configuration: no oasis-workspace.toml at or above {main}.\n'))

    # -- worktree-init ----------------------------------------------------------------------

    def snapshot(self):
        return sorted(str(path.relative_to(self.scratch)) for path in self.scratch.rglob('*')
                      if '.git' not in path.relative_to(self.scratch).parts)

    def test_worktree_init_only_adds_the_worktree(self):
        main = self.layout()
        head = self.git(main, 'rev-parse', 'HEAD')
        new = self.project / 'codigo' / 'acme-shop'
        expected = (f'worktree: {new}\n'
                    f'branch: feature/shop (created from HEAD {head[:12]})\n'
                    'slug: shop\n'
                    f'workspace: {self.project}\n')
        before = self.snapshot()
        result = self.invoke(main, 'worktree-init', 'shop', 'feature/shop', '--dry-run')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, expected + 'dry run: nothing changed\n', ''))
        self.assertEqual(self.snapshot(), before)
        result = self.invoke(main, 'worktree-init', 'shop', 'feature/shop')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, ''))
        self.assertEqual(sorted(path.name for path in new.iterdir()), ['.git', 'README.md'])
        self.assertEqual(self.output(new), self.expected(new, 'linked', 'shop'))

    def test_worktree_init_refuses_a_workspace_inside_the_main_checkout(self):
        main = self.layout()
        self.workspace.unlink()
        (main / 'oasis-workspace.toml').write_text(WORKSPACE)
        before = self.snapshot()
        result = self.invoke(main, 'worktree-init', 'shop', 'feature/shop')
        new = self.project / 'codigo' / 'acme-shop'
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'ERROR: The new worktree {new} would not be under the workspace {main}; '
                                 'prepare the worktree by hand.\n'))
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
