"""workspace_version 2: one workspace file for several Odoo series (v0.15.0 S1, S3, S4).

[tooling] holds the common keys (paths may use `{series}`), `[series."x.y"]` what differs; a checkout
works with its oasis-checkout.toml odoo_version, else the series of its module manifests (series
exceptions left out), else the workspace default. Doctor shows the series and fails series that
share a database port, prefixes, compose project or env file.

Every project lives in a fresh system temp directory, git is kept out with a ceiling, and no real
project, ~/.config or install target is read. The second series is the real 15.0 row of
tools/odoo_versions.py; expected Odoo options and Python are read back from that table.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import importlib.util
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

# Workspace files must not be group-writable (trust rule); keep results independent of the umask.
os.umask(0o022)

ROOT = Path(__file__).resolve().parents[1]
READER = ROOT / 'tools' / 'config.py'
CLI = ROOT / 'oasis'
WORKSPACE = '''workspace_version = 2
odoo_version = '19.0'

[tooling]
community = 'source/{series}/odoo'
environment = 'environments/acme-{series}'
config = 'config/{series}/odoo.conf'
env_file = 'config/{series}/.env'
compose = 'config/{series}/compose.yml'
requirements = 'config/{series}/requirements'
addons_paths = ['.']
db_service = 'db'
dev_prefix = 'acme_dev_'
test_prefix = 'acme_test_'
logs = 'logs/{series}'
data_dir = 'data/{series}'

[series."15.0"]
config = 'config/odoo-15/odoo.conf'
env_file = 'config/odoo-15/.env'
compose = 'config/odoo-15/compose.yml'
dev_prefix = 'acme15_dev_'
test_prefix = 'acme15_test_'
series_exceptions = ['report_xlsx']
'''
SECTION_15 = WORKSPACE[WORKSPACE.index('[series."15.0"]'):]
WITHOUT_15 = WORKSPACE.replace(SECTION_15, '')
SECTION_KEYS = ('community, enterprise, environment, config, env_file, compose, requirements, db_service, '
                'dev_prefix, test_prefix, test_database, logs, data_dir, series_exceptions')


def manifest(version):
    return f"{{'name': 'A module', 'version': {version!r}, 'depends': ['base']}}\n"


def fresh_config(name):
    """A config.py module of its own (in-process readers)."""
    spec = importlib.util.spec_from_file_location(name, READER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def supported():
    return ', '.join(fresh_config('oasis_v2_table').versions().supported())


class WorkspaceVersion2Tests(unittest.TestCase):
    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix='oasis-v2-')).resolve()
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)
        self.project = self.scratch / 'acme'
        self.project.mkdir()
        self.workspace = self.project / 'oasis-workspace.toml'
        self.workspace.write_text(WORKSPACE)
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(('GIT_', 'OASIS_', 'ODOO19_'))}
        self.env.update({'GIT_CEILING_DIRECTORIES': str(self.scratch), 'PYTHONDONTWRITEBYTECODE': '1',
                         'XDG_CONFIG_HOME': str(self.scratch / 'xdg'), 'XDG_RUNTIME_DIR': str(self.scratch)})
        # The in-process readers see the same environment as the subprocesses.
        patcher = unittest.mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config = fresh_config('oasis_v2_config')

    # -- fixtures ---------------------------------------------------------------------------

    def checkout(self, name, *modules, checkout_file=None):
        """<project>/codigo/<name> (outside git) with the given (module, version) manifests."""
        root = self.project / 'codigo' / name
        root.mkdir(parents=True)
        for module, version in modules:
            (root / module).mkdir()
            (root / module / '__manifest__.py').write_text(manifest(version))
        if checkout_file is not None:
            (root / 'oasis-checkout.toml').write_text(checkout_file)
        return root

    def reader(self, *args):
        return subprocess.run([sys.executable, '-B', str(READER), *args], capture_output=True, text=True,
                              env=self.env)

    def output(self, root):
        result = self.reader(str(root))
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        return result.stdout

    def assert_rejected(self, root, message):
        for args in ((str(root),), ('--origins', str(root))):
            with self.subTest(args=args[0]):
                result = self.reader(*args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', f'ERROR: {message}\n'))

    def refused(self, root):
        """The in-process refusal of root (the series table includes 15.0 here)."""
        with self.assertRaises(self.config.InvalidConfig) as refused:
            self.config.load(root)
        return str(refused.exception)

    def expected(self, checkout, series, **changed):
        """Every assignment of a version 2 checkout of series, from [tooling] with {series} replaced."""
        project, capability = self.project, self.config.versions().capability
        values = {
            'PROJECT_ROOT': str(checkout), 'PROJECT_NAME': checkout.name,
            'DEV_PREFIX': 'acme_dev_', 'TEST_PREFIX': 'acme_test_', 'TEST_DATABASE': '',
            'ODOO_SOURCE': str(project / f'source/{series}/odoo'),
            'PROJECT_ENVIRONMENT': str(project / f'environments/acme-{series}'),
            'ODOO_CONFIG': str(project / f'config/{series}/odoo.conf'),
            'ENV_FILE': str(project / f'config/{series}/.env'),
            'COMPOSE_FILE': str(project / f'config/{series}/compose.yml'),
            'REQUIREMENTS_DIR': str(project / f'config/{series}/requirements'),
            'ADDON_ROOTS': str(checkout), 'DB_SERVICE': 'db',
            'PYTHON': str(project / f'environments/acme-{series}/bin/python'),
            'ODOO_BIN': str(project / f'source/{series}/odoo/odoo-bin'),
            'ENVIRONMENTS_DIR': str(project / 'environments'),
            'CHECKOUT_KIND': 'none', 'CHECKOUT_SLUG': '', 'CHECKOUT_MAIN_ROOT': '',
            'LOGS_DIR': str(project / f'logs/{series}'), 'WORKSPACE_ROOT': str(project),
            'ODOO_VERSION': series, 'ODOO_SECOND_PORT_OPTION': capability(series, 'second_port_option'),
            'ODOO_DEMO_OFF_ARGS': shlex.join(capability(series, 'demo_off_args')),
            'ENVIRONMENT_NAME': '', 'PYTHON_VERSION': capability(series, 'python_default'),
            'DATA_DIR': str(project / f'data/{series}'), 'AGENT_DESTRUCTIVE': 'ask',
            # Appended last, only for workspace_version 2.
            'WORKSPACE_VERSION': '2', 'SERIES_EXCEPTIONS': '',
        }
        for key, value in changed.items():
            self.assertIn(key, values)
            values[key] = value
        return values

    def shell(self, values):
        return ''.join(f'{name}={shlex.quote(value)}\n' for name, value in values.items())

    def section_15(self, series='15.0'):
        """The 15.0 section's own values, for expected()."""
        project = self.project
        return {'DEV_PREFIX': 'acme15_dev_', 'TEST_PREFIX': 'acme15_test_',
                'ODOO_CONFIG': str(project / 'config/odoo-15/odoo.conf'),
                'ENV_FILE': str(project / 'config/odoo-15/.env'),
                'COMPOSE_FILE': str(project / 'config/odoo-15/compose.yml')}

    # -- the default series (real table) ------------------------------------------------------

    def test_a_checkout_of_the_default_series_reads_tooling_with_its_series_in_the_paths(self):
        shop = self.checkout('shop', ('shop_sale', '19.0.1.0.0'), ('plain', '1.0'))
        self.assertEqual(self.output(shop), self.shell(self.expected(shop, '19.0')))
        origins = ("MACHINE_FILE=''\nMACHINE_ENVIRONMENTS_DIR=''\nODOO_SOURCE_FROM=workspace\n"
                   "ENTERPRISE_SOURCE_FROM=''\nPROJECT_ENVIRONMENT_FROM=workspace\nCHECKOUT_SLUG_FROM=''\n")
        result = self.reader('--origins', str(shop))
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, origins + 'ODOO_VERSION_FROM=manifests\n', ''))
        # Without a series-style manifest the checkout has the workspace default.
        empty = self.checkout('empty', ('plain', '1.0'))
        self.assertEqual(self.output(empty), self.shell(self.expected(empty, '19.0')))
        result = self.reader('--origins', str(empty))
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, origins + 'ODOO_VERSION_FROM=workspace\n', ''))

    def test_a_section_of_the_default_series_overrides_only_what_it_sets(self):
        self.workspace.write_text(WITHOUT_15 + "[series.\"19.0\"]\nconfig = 'config/main.conf'\n"
                                  "dev_prefix = 'shop_dev_'\ntest_prefix = 'shop_test_'\n"
                                  "series_exceptions = ['report_xlsx', 'web_tree']\n")
        shop = self.checkout('shop', ('shop_sale', '19.0.1.0.0'), ('report_xlsx', '16.0.2.0.2'),
                             ('web_tree', '15.0.1.0.0'))
        self.assertEqual(self.output(shop), self.shell(self.expected(
            shop, '19.0', DEV_PREFIX='shop_dev_', TEST_PREFIX='shop_test_',
            ODOO_CONFIG=str(self.project / 'config/main.conf'), SERIES_EXCEPTIONS='report_xlsx\nweb_tree')))
        # S4: without the exception the guard refuses the module, naming the series_exceptions fix.
        self.workspace.write_text(self.workspace.read_text().replace("['report_xlsx', 'web_tree']", "['web_tree']"))
        result = self.reader(str(shop))
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.assertEqual(result.stderr, 'ERROR: ' + (
            f'The module report_xlsx declares Odoo 16.0 (version 16.0.2.0.2 in {shop / "report_xlsx/__manifest__.py"}), '
            f'but {shop} is configured for Odoo 19.0 by {self.workspace}: run oasis in a checkout of an Odoo 19.0 '
            'branch, or set the version of report_xlsx to 19.0.x.y.z if it is an Odoo 19.0 module, or list '
            f'report_xlsx in series_exceptions under [series."19.0"] in {self.workspace}; oasis does not support '
            f'Odoo 16.0 (supported: {supported()})'
            '.\n'))

    def test_invalid_series_sections_are_refused_with_one_message(self):
        shop = self.checkout('shop', ('shop_sale', '19.0.1.0.0'))
        file = self.workspace
        for text, message in (
                (WITHOUT_15.replace('[tooling]\n', 'series = 1\n\n[tooling]\n'), f'Invalid [series] in {file}.'),
                ("[series.\"18.0\"]\nconfig = 'x'\n", f'Unknown series "18.0" in {file}; supported: {supported()}.'),
                ("[series]\n\"19.0\" = 'x'\n", f'Invalid [series."19.0"] in {file}.'),
                ("[series.\"19.0\"]\naddons_paths = ['x']\n",
                 f'Unknown key series."19.0".addons_paths in {file}; a series section may set: {SECTION_KEYS}.'),
                ("[series.\"19.0\"]\nversion = '19.0'\n",
                 f'Unknown key series."19.0".version in {file}; a series section may set: {SECTION_KEYS}.'),
                ("[series.\"19.0\"]\ncheckout_slug = 'all'\n",
                 f'Unknown key series."19.0".checkout_slug in {file}; a series section may set: {SECTION_KEYS}.'),
                ("[series.\"19.0\"]\nseries_exceptions = 'report_xlsx'\n",
                 f'Invalid series."19.0".series_exceptions in {file}: use a list of module names.'),
                ("[series.\"19.0\"]\nseries_exceptions = ['report xlsx']\n",
                 f'Invalid series."19.0".series_exceptions in {file}: use a list of module names.')):
            with self.subTest(text=text):
                file.write_text(text if text.startswith('workspace_version') else WITHOUT_15 + text)
                self.assert_rejected(shop, message)
        # The exceptions belong to a series section, not to the common keys.
        file.write_text(WITHOUT_15.replace('[tooling]\n', "[tooling]\nseries_exceptions = ['report_xlsx']\n"))
        self.assert_rejected(shop, f'[tooling].series_exceptions belongs in a [series."<version>"] section of {file}.')
        # A section's values keep the [tooling] rules.
        file.write_text(WITHOUT_15 + "[series.\"19.0\"]\ndev_prefix = 'other_dev_'\n")
        self.assert_rejected(shop, 'Unsafe tooling database prefixes.')
        file.write_text(WITHOUT_15 + "[series.\"19.0\"]\nconfig = ''\n")
        self.assert_rejected(shop, 'Invalid tooling path: config.')

    def test_unsupported_versions_are_refused(self):
        shop = self.checkout('shop', checkout_file="odoo_version = '18.0'\n")
        self.assert_rejected(shop, f'Unsupported odoo_version "18.0" in {shop / "oasis-checkout.toml"}; '
                                   f'supported: {supported()}.')
        (shop / 'oasis-checkout.toml').write_text('odoo_version = 19\n')
        self.assert_rejected(shop, f'Unsupported odoo_version 19 in {shop / "oasis-checkout.toml"}; '
                                   f'supported: {supported()}.')
        (shop / 'oasis-checkout.toml').unlink()
        for line, shown in (('workspace_version = 3\n', '3'), ('workspace_version = 0\n', '0')):
            with self.subTest(shown=shown):
                self.workspace.write_text(WORKSPACE.replace('workspace_version = 2\n', line))
                self.assert_rejected(shop, f'Unsupported workspace_version {shown} in {self.workspace}.')

    # -- workspace_version 1 is unchanged -----------------------------------------------------

    def test_workspace_version_1_ignores_sections_and_placeholders_and_appends_nothing(self):
        v1 = WITHOUT_15.replace('workspace_version = 2', 'workspace_version = 1')
        self.workspace.write_text(v1 + "[series.\"19.0\"]\ndev_prefix = 'other_dev_'\nunknown = 1\n")
        shop = self.checkout('shop', ('shop_sale', '19.0.1.0.0'))
        # Every path keeps {series} as written; no section is read and nothing is appended.
        literal = {key: value.replace('19.0', '{series}') if value.startswith('/') else value
                   for key, value in self.expected(shop, '19.0').items()}
        del literal['WORKSPACE_VERSION'], literal['SERIES_EXCEPTIONS']
        self.assertEqual(self.output(shop), self.shell(literal))
        result = self.reader('--origins', str(shop))
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertNotIn('ODOO_VERSION_FROM', result.stdout)
        # A module of another series is refused with the version 1 refusal, as before (--origins has no guard).
        (shop / 'old').mkdir()
        (shop / 'old/__manifest__.py').write_text(manifest('15.0.1.0.0'))
        result = self.reader(str(shop))
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.assertEqual(result.stderr, 'ERROR: ' + (
            f'The module old declares Odoo 15.0 (version 15.0.1.0.0 in {shop / "old/__manifest__.py"}), but {shop} '
            f'is configured for Odoo 19.0 by {self.workspace}: run oasis in a checkout of an Odoo 19.0 branch, or '
            'set the version of old to 19.0.x.y.z if it is an Odoo 19.0 module; for Odoo 15.0 here, run oasis setup '
            f'to add a [series."15.0"] section to {self.workspace}.\n'))

    # -- another series -----------------------------------------------------------------------

    def test_a_checkout_of_another_series_reads_its_section(self):
        shop = self.checkout('shop15', ('cafe_sale', '15.0.1.0.0'), ('report_xlsx', '16.0.2.0.2'))
        self.assertEqual(self.config.load(shop), self.expected(shop, '15.0', SERIES_EXCEPTIONS='report_xlsx',
                                                                **self.section_15()))
        self.assertEqual(self.config.origins(shop)['ODOO_VERSION_FROM'], 'manifests')

    def test_the_checkout_file_wins_over_the_manifests_and_the_default(self):
        shop = self.checkout('shop', ('plain', '1.0'), checkout_file="odoo_version = '15.0'\n")
        self.assertEqual(self.config.load(shop), self.expected(shop, '15.0', SERIES_EXCEPTIONS='report_xlsx',
                                                                **self.section_15()))
        self.assertEqual(self.config.origins(shop)['ODOO_VERSION_FROM'], 'checkout')
        # With its slug and environment keys next to it.
        (shop / 'oasis-checkout.toml').write_text("odoo_version = '15.0'\n[tooling]\ncheckout_slug = 'feat'\n")
        self.assertEqual(self.config.load(shop)['CHECKOUT_SLUG'], 'feat')
        # The checkout's series is checked against its manifests like any other.
        (shop / 'oasis-checkout.toml').write_text("odoo_version = '19.0'\n")
        (shop / 'cafe_sale').mkdir()
        (shop / 'cafe_sale/__manifest__.py').write_text(manifest('15.0.1.0.0'))
        self.assertEqual(self.refused(shop), (
            f'The module cafe_sale declares Odoo 15.0 (version 15.0.1.0.0 in {shop / "cafe_sale/__manifest__.py"}), '
            f'but {shop} is configured for Odoo 19.0 by {self.workspace}: run oasis in a checkout of an Odoo 19.0 '
            'branch, or set the version of cafe_sale to 19.0.x.y.z if it is an Odoo 19.0 module, or list cafe_sale '
            f'in series_exceptions under [series."19.0"] in {self.workspace}; for Odoo 15.0 here, set '
            f"odoo_version = '15.0' in {shop / 'oasis-checkout.toml'}."))
        # Without a 15.0 section the fix names oasis setup instead.
        self.workspace.write_text(WITHOUT_15)
        self.assertEqual(self.refused(shop), (
            f'The module cafe_sale declares Odoo 15.0 (version 15.0.1.0.0 in {shop / "cafe_sale/__manifest__.py"}), '
            f'but {shop} is configured for Odoo 19.0 by {self.workspace}: run oasis in a checkout of an Odoo 19.0 '
            'branch, or set the version of cafe_sale to 19.0.x.y.z if it is an Odoo 19.0 module, or list cafe_sale '
            f'in series_exceptions under [series."19.0"] in {self.workspace}; for Odoo 15.0 here, run oasis setup to '
            f'add a [series."15.0"] section to {self.workspace}.'))

    def test_a_series_without_a_section_is_refused_naming_setup(self):
        self.workspace.write_text(WITHOUT_15)
        shop = self.checkout('shop15', ('cafe_sale', '15.0.1.0.0'))
        message = (f'{shop} is an Odoo 15.0 checkout (the series of its module manifests), but {self.workspace} '
                   'has no [series."15.0"] section: run oasis setup to add it.')
        self.assertEqual(self.refused(shop), message)
        with self.assertRaises(self.config.MissingSeries):
            self.config.origins(shop)
        pinned = self.checkout('pinned', checkout_file="odoo_version = '15.0'\n")
        self.assertEqual(self.refused(pinned), (
            f"{pinned} is an Odoo 15.0 checkout (odoo_version in {pinned / 'oasis-checkout.toml'}), but "
            f'{self.workspace} has no [series."15.0"] section: run oasis setup to add it.'))
        # A version 1 workspace has one series: another one in the checkout file is refused the same way.
        self.workspace.write_text(WITHOUT_15.replace('workspace_version = 2', 'workspace_version = 1'))
        self.assertEqual(self.refused(pinned), (
            f"{pinned} is an Odoo 15.0 checkout (odoo_version in {pinned / 'oasis-checkout.toml'}), but "
            f'{self.workspace} has no [series."15.0"] section: run oasis setup to add it.'))
        (pinned / 'oasis-checkout.toml').write_text("odoo_version = '19.0'\n")
        self.assertEqual(self.config.load(pinned)['ODOO_VERSION'], '19.0')

    def test_modules_of_several_series_are_refused_naming_them(self):
        shop = self.checkout('mixed', ('b_sale', '15.0.1.0.0'), ('a_sale', '15.0.1.0.1'), ('c_web', '19.0.1.0.0'),
                             ('other', '16.0.1.0.0'))
        self.assertEqual(self.refused(shop), (
            f'The modules of {shop} declare several Odoo series: 15.0 (a_sale), 19.0 (c_web); set odoo_version in '
            f'{shop / "oasis-checkout.toml"} to the series of this checkout, or list the modules of the other series '
            f'in series_exceptions under its [series."<version>"] in {self.workspace}.'))
        # An exception of any section is left out of the detection, then only its own series ignores it.
        (shop / 'c_web').rename(shop / 'report_xlsx')
        (shop / 'other/__manifest__.py').unlink()
        values = self.config.load(shop)
        self.assertEqual((values['ODOO_VERSION'], values['SERIES_EXCEPTIONS']), ('15.0', 'report_xlsx'))

    def test_series_exceptions_are_ignored_only_for_their_series(self):
        shop = self.checkout('shop15', ('cafe_sale', '15.0.1.0.0'), ('report_xlsx', '16.0.2.0.2'))
        self.assertEqual(self.config.load(shop)['ODOO_VERSION'], '15.0')
        self.workspace.write_text(WORKSPACE.replace("series_exceptions = ['report_xlsx']\n", ''))
        self.assertEqual(self.refused(shop), (
            f'The module report_xlsx declares Odoo 16.0 (version 16.0.2.0.2 in {shop / "report_xlsx/__manifest__.py"}), '
            f'but {shop} is configured for Odoo 15.0 by {self.workspace}: run oasis in a checkout of an Odoo 15.0 '
            'branch, or set the version of report_xlsx to 15.0.x.y.z if it is an Odoo 15.0 module, or list '
            f'report_xlsx in series_exceptions under [series."15.0"] in {self.workspace}; oasis does not support '
            f'Odoo 16.0 (supported: {", ".join(self.config.versions().supported())}).'))
        # The guard of doctor and setup reads the same exceptions from the assignments.
        values = self.config.load(shop, series_guard=False)
        self.assertEqual(self.config.series_mismatch(values)['module'], 'report_xlsx')
        values['SERIES_EXCEPTIONS'] = 'report_xlsx'
        self.assertIsNone(self.config.series_mismatch(values))

    def test_each_layer_wins_over_the_next(self):
        """checkout > workspace [series] > [tooling] > machine [series] > table defaults."""
        machine = self.scratch / 'xdg/oasis/config.toml'
        machine.parent.mkdir(parents=True, mode=0o700)
        machine.write_text("[series.\"15.0\"]\ncommunity = '/machine/15.0/odoo'\n"
                           "[series.\"19.0\"]\ncommunity = '/machine/19.0/odoo'\n")
        machine.chmod(0o600)
        text = WORKSPACE.replace("community = 'source/{series}/odoo'\n", '')
        self.workspace.write_text(text)
        shop = self.checkout('shop15', ('cafe_sale', '15.0.1.0.0'))
        values = self.config.load(shop)
        # Machine [series] over nothing; the table's Python without a declared one.
        self.assertEqual((values['ODOO_SOURCE'], values['PYTHON_VERSION']),
                         ('/machine/15.0/odoo', self.config.versions().capability('15.0', 'python_default')))
        self.assertEqual(self.config.origins(shop)['ODOO_SOURCE_FROM'], 'machine')
        # [tooling] over the machine file.
        self.workspace.write_text(WORKSPACE)
        self.assertEqual(self.config.load(shop)['ODOO_SOURCE'], str(self.project / 'source/15.0/odoo'))
        # The series section over [tooling].
        self.workspace.write_text(WORKSPACE + "community = '/section/odoo'\nenvironment = 'environments/cafe15'\n")
        values = self.config.load(shop)
        self.assertEqual((values['ODOO_SOURCE'], values['PROJECT_ENVIRONMENT']),
                         ('/section/odoo', str(self.project / 'environments/cafe15')))
        # The checkout's named environment over the section's path; named environments may use {series}.
        named = (WORKSPACE.replace("environment = 'environments/acme-{series}'\n", '')
                 + "environment = 'environments/cafe15'\n"
                 "[environments.default]\npath = 'environments/acme-{series}'\npython = '3.12'\n"
                 "[environments.old]\npath = 'environments/old-{series}'\npython = '3.10'\n")
        self.workspace.write_text(named)
        self.assertEqual(self.config.load(shop)['PROJECT_ENVIRONMENT'], str(self.project / 'environments/cafe15'))
        (shop / 'oasis-checkout.toml').write_text("[tooling]\nenvironment = 'old'\n")
        values = self.config.load(shop)
        self.assertEqual((values['PROJECT_ENVIRONMENT'], values['ENVIRONMENT_NAME'], values['PYTHON_VERSION']),
                         (str(self.project / 'environments/old-15.0'), 'old', '3.10'))
        # The named environment's Python is checked against the checkout's series.
        self.workspace.write_text(named.replace("python = '3.10'", "python = '3.13'"))
        self.assertEqual(self.refused(shop), (
            f'Unsupported python "3.13" for environment "old" in {self.workspace}; Odoo 15.0 supports '
            f'{" to ".join(self.config.versions().capability("15.0", "python"))}.'))

    def test_configuration_readers_see_the_series_values(self):
        """Tools that read their own keys (lint_rcfile) get the checkout's series too (S3 item 4)."""
        self.workspace.write_text(WORKSPACE.replace('[tooling]\n', "[tooling]\nlint_rcfile = 'config/{series}/.pylintrc'\n"))
        shop = self.checkout('shop15', ('cafe_sale', '15.0.1.0.0'))
        document, base, workspace = self.config.configuration(shop)
        self.assertEqual((document['tooling']['version'], document['tooling']['lint_rcfile'],
                          document['tooling']['dev_prefix'], base, workspace),
                         ('15.0', 'config/15.0/.pylintrc', 'acme15_dev_', self.project, self.workspace))

    def test_the_documented_example_configures_both_series(self):
        docs = (ROOT / 'docs/workspace-file.md').read_text()
        start = docs.index('# Example only: corpus-cafe/oasis-workspace.toml\n')
        self.workspace.write_text(docs[start:docs.index('```', start)])
        machine = self.scratch / 'xdg/oasis/config.toml'
        machine.parent.mkdir(parents=True, mode=0o700)
        machine.write_text("[series.\"15.0\"]\ncommunity = '/odoo/15.0'\n[series.\"19.0\"]\ncommunity = '/odoo/19.0'\n")
        machine.chmod(0o600)
        old = self.checkout('facturacion', ('cafe_sale', '15.0.1.0.0'), ('report_xlsx', '16.0.2.0.2'))
        new = self.checkout('corpus-cafe', ('cafe_sale', '19.0.1.0.0'))
        keys = ('ODOO_VERSION', 'ODOO_SOURCE', 'ODOO_CONFIG', 'COMPOSE_FILE', 'DEV_PREFIX', 'LOGS_DIR',
                'PROJECT_ENVIRONMENT', 'SERIES_EXCEPTIONS')
        project = self.project
        self.assertEqual([self.config.load(old)[key] for key in keys], [
            '15.0', '/odoo/15.0', str(project / 'config/odoo-15/odoo.conf'), str(project / 'config/odoo-15/compose.yml'),
            'cc15_dev_', str(project / 'logs/15.0'), str(project / 'environments/corpus-cafe-15.0'), 'report_xlsx'])
        self.assertEqual([self.config.load(new)[key] for key in keys], [
            '19.0', '/odoo/19.0', str(project / 'config/odoo.conf'), str(project / 'config/compose.yml'),
            'cc_dev_', str(project / 'logs/19.0'), str(project / 'environments/corpus-cafe-19.0'), ''])

    def test_every_reader_follows_the_checkout_series(self):
        shop = self.checkout('shop15', ('cafe_sale', '15.0.1.0.0'))
        self.assertEqual(self.output(shop), self.shell(self.expected(shop, '15.0', SERIES_EXCEPTIONS='report_xlsx',
                                                                     **self.section_15())))


class DoctorVersion2Tests(unittest.TestCase):
    """doctor through the entry point, with fake git, docker and flock first on PATH."""

    setUp_fixture = WorkspaceVersion2Tests.setUp
    checkout = WorkspaceVersion2Tests.checkout

    def setUp(self):
        self.setUp_fixture()
        bindir = self.scratch / 'bin'
        bindir.mkdir()
        for name, text in (('git', 'echo "git version 2.47.1"'), ('docker', 'echo "Docker Compose version v2.29.1"'),
                           ('flock', 'exit 0')):
            (bindir / name).write_text(f'#!/bin/sh\n{text}\n')
            (bindir / name).chmod(0o755)
        os.environ['PATH'] = f'{bindir}:/usr/bin:/bin'
        for series, directory, port, name in (('19.0', 'config/19.0', 5419, 'acme19'),
                                              ('15.0', 'config/odoo-15', 5415, 'acme15')):
            self.series_files(directory, port, name)

    def series_files(self, directory, port, name):
        directory = self.project / directory
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'compose.yml').write_text(f"name: {name}\nservices:\n  db:\n    ports:\n      - '127.0.0.1:{port}:5432'\n")
        (directory / 'odoo.conf').write_text(f'[options]\ndb_port = {port}\n')
        (directory / '.env').write_text('ODOO_DB_USER=me\n')

    def doctor(self, root):
        result = subprocess.run([sys.executable, '-B', str(CLI), '--project', str(root), 'doctor'], text=True,
                                capture_output=True, env=dict(os.environ), stdin=subprocess.DEVNULL)
        self.assertEqual(result.stderr, '')
        return result.returncode, result.stdout

    def test_doctor_shows_the_series_its_origin_its_exceptions_and_their_isolation(self):
        shop = self.checkout('shop15', ('cafe_sale', '15.0.1.0.0'))
        code, report = self.doctor(shop)
        self.assertIn('PASS configuration=workspace\nPASS odoo_version=15.0\nPASS series=15.0 from=manifests\n'
                      'PASS series_exceptions=report_xlsx\nPASS series_isolation=19.0,15.0\n'
                      'PASS agent_destructive=ask\n', report)
        self.assertEqual(code, 1)  # the environment and source of this fixture do not exist
        self.assertNotIn('ODOO_DB_USER', report)
        shop19 = self.checkout('shop', checkout_file="odoo_version = '19.0'\n")
        code, report = self.doctor(shop19)
        self.assertIn('PASS odoo_version=19.0\nPASS series=19.0 from=checkout\nPASS series_isolation=19.0,15.0\n'
                      'PASS agent_destructive=ask\n', report)

    def test_doctor_fails_series_that_share_a_port_prefixes_a_compose_project_or_an_env_file(self):
        self.workspace.write_text(WORKSPACE.replace("dev_prefix = 'acme15_dev_'\ntest_prefix = 'acme15_test_'\n", '')
                                  .replace("env_file = 'config/odoo-15/.env'\n", "env_file = 'config/19.0/.env'\n"))
        self.series_files('config/odoo-15', 5419, 'acme19')
        shop = self.checkout('shop15', ('cafe_sale', '15.0.1.0.0'))
        code, report = self.doctor(shop)
        compose = self.project / 'config/odoo-15/compose.yml'
        expected = (
            'FAIL series_isolation=db_port series=19.0,15.0\n'
            f'  fix: publish another port to 5432 in {compose} and set db_port in '
            f'{self.project / "config/odoo-15/odoo.conf"} to it\n'
            'FAIL series_isolation=compose_project series=19.0,15.0\n'
            f'  fix: set another top-level name: in {compose}\n'
            'FAIL series_isolation=prefixes series=19.0,15.0\n'
            f'  fix: set dev_prefix and test_prefix under [series."15.0"] in {self.workspace} to a pair of its own\n'
            'FAIL series_isolation=env_file series=19.0,15.0\n'
            f'  fix: set env_file under [series."15.0"] in {self.workspace} to a file of its own\n')
        self.assertIn('PASS series_exceptions=report_xlsx\n' + expected + 'PASS agent_destructive=ask\n', report)
        self.assertEqual(code, 1)
        # One compose file for both: the fix is a compose file of its own.
        self.workspace.write_text(WORKSPACE.replace("compose = 'config/odoo-15/compose.yml'\n",
                                                    "compose = 'config/19.0/compose.yml'\n"))
        code, report = self.doctor(shop)
        own = f'  fix: set compose under [series."15.0"] in {self.workspace} to a compose file of its own\n'
        self.assertIn('PASS series_exceptions=report_xlsx\n'
                      f'FAIL series_isolation=db_port series=19.0,15.0\n{own}'
                      f'FAIL series_isolation=compose_project series=19.0,15.0\n{own}'
                      'PASS agent_destructive=ask\n', report)

    def test_doctor_names_setup_for_a_series_without_a_section(self):
        self.workspace.write_text(WITHOUT_15)
        shop = self.checkout('shop15', ('cafe_sale', '15.0.1.0.0'))
        code, report = self.doctor(shop)
        self.assertEqual(code, 1)
        self.assertTrue(report.startswith(
            f'FAIL configuration={shop} is an Odoo 15.0 checkout (the series of its module manifests), but '
            f'{self.workspace} has no [series."15.0"] section: run oasis setup to add it.\n'
            '  fix: oasis setup --apply\nPASS git=2.47.1\n'), report)


if __name__ == '__main__':
    unittest.main()
