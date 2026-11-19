"""The Odoo capability table (tools/odoo_versions.py) and the version-neutral tool sources."""
from pathlib import Path
import importlib.util
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'tools'
SPEC = importlib.util.spec_from_file_location('odoo_versions', TOOLS / 'odoo_versions.py')
odoo_versions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(odoo_versions)


class CapabilityTableTests(unittest.TestCase):
    def test_only_odoo_19_is_supported_with_its_capabilities(self):
        self.assertEqual(odoo_versions.CAPABILITIES, {'19.0': {
            'python': ('3.10', '3.14'), 'postgres_min': 13, 'second_port_option': '--gevent-port',
            'demo_off_args': ['--without-demo'], 'test_tags_implies_stop': True}})
        self.assertEqual(odoo_versions.supported(), ['19.0'])

    def test_capability_reads_one_key(self):
        for key, value in (('python', ('3.10', '3.14')), ('postgres_min', 13),
                           ('second_port_option', '--gevent-port'), ('demo_off_args', ['--without-demo']),
                           ('test_tags_implies_stop', True)):
            with self.subTest(key=key):
                self.assertEqual(odoo_versions.capability('19.0', key), value)

    def test_capability_returns_a_copy_of_lists(self):
        odoo_versions.capability('19.0', 'demo_off_args').append('--with-demo')
        self.assertEqual(odoo_versions.capability('19.0', 'demo_off_args'), ['--without-demo'])

    def test_unknown_version_is_a_clear_error(self):
        for version, shown in (('12.0', '"12.0"'), ('15.0', '"15.0"'), ('19', '"19"'), (19.0, '19.0'),
                               (None, 'null')):
            with self.subTest(version=version):
                with self.assertRaises(odoo_versions.UnsupportedVersion) as caught:
                    odoo_versions.capability(version, 'python')
                self.assertEqual(str(caught.exception), f'Unsupported Odoo version {shown}; supported: 19.0.')
        self.assertTrue(issubclass(odoo_versions.UnsupportedVersion, ValueError))

    def test_unknown_key_is_a_programming_error(self):
        with self.assertRaises(KeyError):
            odoo_versions.capability('19.0', 'longpolling')

    def test_python_range_is_inclusive_and_numeric(self):
        for python, expected in (('3.10', True), ('3.12', True), ('3.14', True), ('3.9', False),
                                 ('3.15', False), ('2.7', False), ('4.0', False), ('3.100', False)):
            with self.subTest(python=python):
                self.assertIs(odoo_versions.python_supported('19.0', python), expected)
        for python in ('3', '3.12.1', '3.x', ' 3.12', '', 3.12, None, '03.12'):
            with self.subTest(python=python):
                self.assertIs(odoo_versions.python_supported('19.0', python), False)


class VersionNeutralToolsTests(unittest.TestCase):
    # Version-specific Odoo options are rendered from the table through config.py's
    # ODOO_SECOND_PORT_OPTION and ODOO_DEMO_OFF_ARGS, never written in a tool.
    FLAGS = re.compile(r'--(gevent-port|longpolling-port|without-demo)')

    def test_no_tool_writes_a_version_specific_odoo_option(self):
        found = []
        for path in sorted(TOOLS.rglob('*')):
            if not path.is_file() or path.name == 'odoo_versions.py' or '__pycache__' in path.parts:
                continue
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if self.FLAGS.search(line):
                    found.append(f'{path.relative_to(ROOT)}:{number}: {line.strip()}')
        self.assertEqual(found, [])


if __name__ == '__main__':
    unittest.main()
