"""The Odoo capability table (tools/odoo_versions.py) and the version-neutral tool sources."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
from pathlib import Path
import importlib.util
import re
import sys
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'tools'
SPEC = importlib.util.spec_from_file_location('odoo_versions', TOOLS / 'odoo_versions.py')
odoo_versions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(odoo_versions)


class CapabilityTableTests(unittest.TestCase):
    ODOO_19 = {
        'python': ('3.10', '3.14'), 'python_default': '3.12', 'postgres_min': 13,
        'postgres_default': 17, 'second_port_option': '--gevent-port',
        'demo_off_args': ['--without-demo'], 'demo_on_args': ['--with-demo'],
        'second_port_conf_option': 'gevent_port',
        'test_tags_implies_stop': True, 'test_class_filter': True,
        'dev_option': '--dev', 'dev_features': ['access', 'qweb', 'reload', 'replica', 'xml'],
        'dev_all': ['access', 'qweb', 'reload', 'xml'], 'dev_reload_packages': ['inotify', 'watchdog'],
        'user_groups_field': 'group_ids'}
    # v0.15.0 S2, read from the local 15.0 source (tools/odoo_versions.py cites the lines).
    ODOO_15 = {
        'python': ('3.7', '3.12'), 'python_default': '3.10', 'postgres_min': 12,
        'postgres_default': 14, 'second_port_option': '--longpolling-port', 'second_port_conf_option': 'longpolling_port',
        'demo_off_args': ['--without-demo=all'], 'demo_on_args': [],
        'test_tags_implies_stop': False, 'test_class_filter': True,
        'dev_option': '--dev',
        'dev_features': ['ipdb', 'pdb', 'pudb', 'wdb', 'qweb', 'reload', 'werkzeug', 'xml'],
        'dev_all': ['pdb', 'reload', 'qweb', 'werkzeug', 'xml'], 'dev_reload_packages': ['inotify', 'watchdog'],
        'user_groups_field': 'groups_id'}

    def test_odoo_19_and_15_are_supported_with_their_capabilities(self):
        self.assertEqual(odoo_versions.CAPABILITIES, {'19.0': self.ODOO_19, '15.0': self.ODOO_15})
        # 19.0 stays first: the series a tool takes when it has to pick one (setup's machine file check).
        self.assertEqual(odoo_versions.supported(), ['19.0', '15.0'])

    def test_capability_reads_one_key(self):
        for version, table in (('19.0', self.ODOO_19), ('15.0', self.ODOO_15)):
            for key, value in table.items():
                with self.subTest(version=version, key=key):
                    self.assertEqual(odoo_versions.capability(version, key), value)

    def test_capability_returns_a_copy_of_lists(self):
        odoo_versions.capability('19.0', 'demo_off_args').append('--with-demo')
        self.assertEqual(odoo_versions.capability('19.0', 'demo_off_args'), ['--without-demo'])

    def test_dev_features_form_a_closed_set_in_every_series(self):
        # The dev mode selector is built from this table (v0.12.0 S4): every series declares its
        # option, its features (closed set of plain words), what `all` turns on and the packages
        # of which one makes `reload` work.
        for version in odoo_versions.supported():
            with self.subTest(version=version):
                features = odoo_versions.capability(version, 'dev_features')
                self.assertRegex(odoo_versions.capability(version, 'dev_option'), r'^--[a-z][a-z-]*$')
                self.assertTrue(features)
                self.assertEqual(len(set(features)), len(features))
                for feature in features:
                    self.assertRegex(feature, r'^[a-z]+$')
                self.assertLessEqual(set(odoo_versions.capability(version, 'dev_all')), set(features))
                packages = odoo_versions.capability(version, 'dev_reload_packages')
                self.assertEqual(bool(packages), 'reload' in features)
        odoo_versions.capability('19.0', 'dev_features').append('pdb')
        self.assertNotIn('pdb', odoo_versions.capability('19.0', 'dev_features'))

    def test_default_python_lies_in_the_series_range(self):
        # The Python of a workspace that sets [tooling].environment instead of named environments.
        for version in odoo_versions.supported():
            with self.subTest(version=version):
                self.assertTrue(odoo_versions.python_supported(
                    version, odoo_versions.capability(version, 'python_default')))

    def test_default_postgres_is_supported_by_its_series(self):
        # The PostgreSQL of the compose file oasis setup writes (v0.14.0 L13): never below the minimum.
        for version in odoo_versions.supported():
            with self.subTest(version=version):
                default = odoo_versions.capability(version, 'postgres_default')
                self.assertIs(type(default), int)
                self.assertGreaterEqual(default, odoo_versions.capability(version, 'postgres_min'))

    def test_unknown_version_is_a_clear_error(self):
        for version, shown in (('12.0', '"12.0"'), ('16.0', '"16.0"'), ('15', '"15"'), ('19', '"19"'),
                               (19.0, '19.0'), (15.0, '15.0'), (None, 'null')):
            with self.subTest(version=version):
                with self.assertRaises(odoo_versions.UnsupportedVersion) as caught:
                    odoo_versions.capability(version, 'python')
                self.assertEqual(str(caught.exception), f'Unsupported Odoo version {shown}; supported: 19.0, 15.0.')
        self.assertTrue(issubclass(odoo_versions.UnsupportedVersion, ValueError))

    def test_unknown_key_is_a_programming_error(self):
        with self.assertRaises(KeyError):
            odoo_versions.capability('19.0', 'longpolling')

    def test_python_range_is_inclusive_and_numeric(self):
        for python, expected in (('3.10', True), ('3.12', True), ('3.14', True), ('3.9', False),
                                 ('3.15', False), ('2.7', False), ('4.0', False), ('3.100', False)):
            with self.subTest(python=python):
                self.assertIs(odoo_versions.python_supported('19.0', python), expected)
        for python, expected in (('3.7', True), ('3.10', True), ('3.12', True), ('3.6', False), ('3.13', False)):
            with self.subTest(series='15.0', python=python):
                self.assertIs(odoo_versions.python_supported('15.0', python), expected)
        for python in ('3', '3.12.1', '3.x', ' 3.12', '', 3.12, None, '03.12'):
            with self.subTest(python=python):
                self.assertIs(odoo_versions.python_supported('19.0', python), False)


class VersionNeutralToolsTests(unittest.TestCase):
    # Version-specific Odoo options are rendered from the table through config.py's
    # ODOO_SECOND_PORT_OPTION and ODOO_DEMO_OFF_ARGS (and odoo_versions.py demo_on_args), never
    # written in a tool. --with-demo is also the oasis option of install-module and
    # init-dev-database (and the menu's flag for them): only those lines may name it.
    FLAGS = re.compile(r'--(gevent-port|longpolling-port|without-demo|with-demo)(?![\w-])')
    OASIS_OPTIONS = {
        ('tools/actions.py', "[flag('demo', '--with-demo'), value('module'), value('database')],"),
        ('tools/init-dev-database', "printf '%s\\n' 'Usage: init-dev-database [--with-demo] <module> <database>' \\"),
        ('tools/init-dev-database', "'--with-demo opts in to the native Odoo demo loader and project development.demo_modules.'"),
        ('tools/init-dev-database', 'if [[ ${1:-} == --with-demo ]]; then'),
        ('tools/init-dev-database', "printf 'Usage: init-dev-database [--with-demo] <module> <database>\\n' >&2"),
        ('tools/install-module', "usage='Usage: install-module [--with-demo] <module> [database]'"),
        ('tools/install-module', 'if [[ ${1:-} == --with-demo ]]; then'),
    }

    def test_no_tool_writes_a_version_specific_odoo_option(self):
        found = []
        for path in sorted(TOOLS.rglob('*')):
            if not path.is_file() or path.name == 'odoo_versions.py' or '__pycache__' in path.parts:
                continue
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if self.FLAGS.search(line) and (str(path.relative_to(ROOT)), line.strip()) not in self.OASIS_OPTIONS:
                    found.append(f'{path.relative_to(ROOT)}:{number}: {line.strip()}')
        self.assertEqual(found, [])

    def test_the_guard_sees_every_series_option(self):
        for line in ('run_odoo -i x --with-demo --stop-after-init', "'--longpolling-port=8073'",
                     '--gevent-port 1', 'args=(--without-demo=all)'):
            with self.subTest(line=line):
                self.assertRegex(line, self.FLAGS)
        self.assertNotRegex('--with-demos --without-demo-data', self.FLAGS)

    # The series itself is read from the configuration (ODOO_VERSION) or the table: besides
    # odoo_versions.py, only the legacy profile contract that migrate converts may name it.
    SERIES = re.compile(r"(?<![\w.])19\.0(?!\d)|\(19, 0\)|release_is_19")
    ALLOWED = {('tools/migrate.py', "LEGACY_VERSION = '19.0'")}

    def test_no_tool_names_the_odoo_series(self):
        found = []
        for path in sorted(TOOLS.rglob('*')):
            if not path.is_file() or path.name == 'odoo_versions.py' or '__pycache__' in path.parts:
                continue
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if self.SERIES.search(line) and (str(path.relative_to(ROOT)), line.strip()) not in self.ALLOWED:
                    found.append(f'{path.relative_to(ROOT)}:{number}: {line.strip()}')
        self.assertEqual(found, [])

    def test_capabilities_can_be_read_from_the_shell(self):
        def read(*args):
            return subprocess.run([sys.executable, '-I', '-B', str(TOOLS / 'odoo_versions.py'), *args],
                                  text=True, capture_output=True)
        for key, expected in (('test_class_filter', 'true\n'), ('second_port_option', '--gevent-port\n'),
                              ('demo_off_args', '--without-demo\n'), ('postgres_min', '13\n'), ('postgres_default', '17\n'),
                              ('dev_option', '--dev\n'), ('dev_features', 'access qweb reload replica xml\n'),
                              ('dev_all', 'access qweb reload xml\n'), ('dev_reload_packages', 'inotify watchdog\n')):
            with self.subTest(key=key):
                result = read('19.0', key)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, ''))
        for version, key, expected in (('19.0', 'demo_on_args', '--with-demo\n'), ('15.0', 'demo_on_args', '\n'),
                                       ('15.0', 'demo_off_args', '--without-demo=all\n'),
                                       ('15.0', 'second_port_option', '--longpolling-port\n'),
                                       ('19.0', 'second_port_conf_option', 'gevent_port\n'),
                                       ('15.0', 'second_port_conf_option', 'longpolling_port\n'),
                                       ('15.0', 'test_tags_implies_stop', 'false\n'), ('15.0', 'test_class_filter', 'true\n'),
                                       ('15.0', 'python', '3.7 3.12\n'), ('15.0', 'postgres_default', '14\n'),
                                       ('15.0', 'dev_all', 'pdb reload qweb werkzeug xml\n')):
            with self.subTest(version=version, key=key):
                result = read(version, key)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, expected, ''))
        for args in (('12.0', 'test_class_filter'), ('19.0', 'no_such_key'), ('19.0',), ()):
            with self.subTest(args=args):
                result = read(*args)
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertTrue(result.stderr.strip())


if __name__ == '__main__':
    unittest.main()
