"""Workspace file discovery: `oasis-workspace.toml` at the project root, checkouts at any depth.

Every project lives in a fresh system temp directory. git runs with explicit -c identity flags,
an empty global configuration and a ceiling at the scratch directory, so it never reads or
writes the user's configuration or a real project.
"""
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
LEGACY_PROFILE = (ROOT / 'tests' / 'fixture-profile.toml').read_text()
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
LEGACY_TAIL = ["WORKSPACE_ROOT=''", 'ODOO_VERSION=19.0', 'ODOO_SECOND_PORT_OPTION=--gevent-port',
               'ODOO_DEMO_OFF_ARGS=--without-demo', "ENVIRONMENT_NAME=''", 'PYTHON_VERSION=3.12', "DATA_DIR=''",
               'AGENT_DESTRUCTIVE=ask']
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
                         'GIT_CONFIG_NOSYSTEM': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
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

    def test_linked_worktree_needs_no_profile_copy(self):
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

    def test_legacy_profile_in_the_checkout_wins(self):
        main = self.layout()
        (main / '.odoo19-agent.toml').write_text(LEGACY_PROFILE)
        # A checkout file is not read in legacy mode.
        (main / 'oasis-checkout.toml').write_text("[odoo]\nversion = '18.0'\n")
        lines = self.assignments(main)
        self.assertEqual(lines[-8:], LEGACY_TAIL)
        self.assertIn('PROJECT_ENVIRONMENT=' + shlex.quote(str((main / '../../environments/example').resolve())),
                      lines)
        self.assertIn('ODOO_CONFIG=' + shlex.quote(str(main / 'dev/odoo.conf')), lines)
        self.assertIn("DEV_PREFIX=cc_dev_", lines)

    def test_legacy_profile_keeps_its_rules_in_a_writable_checkout(self):
        main = self.layout()
        (main / '.odoo19-agent.toml').write_text(LEGACY_PROFILE)
        expected = self.output(main)
        mode = stat.S_IMODE(main.stat().st_mode)
        main.chmod(mode | stat.S_IWGRP)
        try:
            self.assertEqual(self.output(main), expected)
        finally:
            main.chmod(mode)

    def test_a_profile_on_the_way_stops_discovery(self):
        main = self.layout()
        (self.project / 'codigo' / '.odoo19-agent.toml').write_text(LEGACY_PROFILE)
        self.assert_rejected(main, f'Missing tooling configuration: {main / ".odoo19-agent.toml"}')

    def test_without_any_file_the_missing_profile_error_stays(self):
        main = self.layout()
        self.workspace.unlink()
        self.assert_rejected(main, f'Missing tooling configuration: {main / ".odoo19-agent.toml"}')

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

    def test_workspace_tooling_keeps_the_profile_validation(self):
        main = self.layout()
        self.workspace.write_text(WORKSPACE.replace("test_prefix = 'acme_test_'", "test_prefix = 'other_test_'"))
        self.assert_rejected(main, 'Unsafe tooling database prefixes.')
        self.workspace.write_text(WORKSPACE + "[odoo]\nversion = '18.0'\n")
        self.assert_rejected(main, 'Conflicting advisory and tooling values: odoo.version.')
        self.workspace.write_text(WORKSPACE + "[odoo]\nversion = '19.0'\n")
        self.assertEqual(self.output(main), self.expected(main, 'main', ''))

    def test_shipped_example_is_accepted(self):
        example = ROOT / 'odoo19-environment/assets/oasis-workspace.example.toml'
        main = self.layout(example.read_text())
        lines = self.output(main).splitlines()
        self.assertEqual(lines[-8:], ['WORKSPACE_ROOT=' + shlex.quote(str(self.project)), 'ODOO_VERSION=19.0',
                                      'ODOO_SECOND_PORT_OPTION=--gevent-port', 'ODOO_DEMO_OFF_ARGS=--without-demo',
                                      "ENVIRONMENT_NAME=''", 'PYTHON_VERSION=3.12', "DATA_DIR=''",
                                      'AGENT_DESTRUCTIVE=ask'])
        self.assertIn('ODOO_CONFIG=' + shlex.quote(str(self.project / 'config/odoo.conf')), lines)
        self.assertIn('ADDON_ROOTS=' + shlex.quote(str(main)), lines)

    def test_shipped_example_documents_named_environments(self):
        # Uncommenting the documented [environments.default] block in place of
        # [tooling].environment gives a working workspace that selects it.
        raw = (ROOT / 'odoo19-environment/assets/oasis-workspace.example.toml').read_text()
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
        raw = (ROOT / 'odoo19-environment/assets/oasis-workspace.example.toml').read_text()
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

    # -- odoo19 entry point -----------------------------------------------------------------

    def invoke(self, project, *args):
        return subprocess.run([sys.executable, '-B', str(CLI), '--project', str(project), *args],
                              capture_output=True, text=True, env=self.env, cwd=self.scratch)

    def test_entry_point_runs_a_command_in_a_checkout_without_profile(self):
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

    def test_entry_point_keeps_the_error_without_profile_or_workspace(self):
        main = self.layout()
        self.workspace.unlink()
        result = self.invoke(main, 'model-info', 'coffee.order')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'ERROR: Missing tooling configuration: {main / ".odoo19-agent.toml"}\n'))

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
