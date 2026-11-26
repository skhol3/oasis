"""tools/known_problems.py: the requirement, marker and version readers, the OpenLDAP check and the module
requirements setup asks about (v0.16.0 S3).

Unit tests of the module loaded from its file: system_ldap gets fake programs through patched shutil.which and
subprocess.run, so nothing reads this machine's libraries; requirement files live in a fresh temp directory.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import ast
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / 'tools'


def load():
    spec = importlib.util.spec_from_file_location('oasis_test_known_problems', TOOLS / 'known_problems.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


known = load()


class ParserTests(unittest.TestCase):
    def test_version_reads_numbers_and_dots_only(self):
        for text, expected in (('1.2.3', (1, 2, 3)), ('2', (2,)), ('010.0', (10, 0)), ('1.2a', None), ('', None),
                               ('1..2', None), ('1.2.', None), ('v1', None)):
            with self.subTest(text=text):
                self.assertEqual(known.version(text), expected)

    def test_requirement_reads_the_name_the_clauses_and_the_marker(self):
        for line, expected in (
                ("python-ldap==3.4.0 ; sys_platform != 'win32'",
                 ('python-ldap', [('==', '3.4.0')], "sys_platform != 'win32'")),
                ('Babel[extra] >=2.6, <3', ('Babel', [('>=', '2.6'), ('<', '3')], '')),
                ('zope.interface~=5.4', ('zope.interface', [('~=', '5.4')], '')),
                ('gevent===21.8.0', ('gevent', [('===', '21.8.0')], '')),
                ('reportlab!=3.6.*', ('reportlab', [('!=', '3.6.*')], '')),
                ('phonenumbers', ('phonenumbers', [], '')),
                ('  requests  ', ('requests', [], '')),
                ('pkg @ https://example.invalid/pkg-1.0.tar.gz', None),
                ('==1.0', None), ('', None), ('pkg ==', None)):
            with self.subTest(line=line):
                self.assertEqual(known.requirement(line), expected)

    def test_a_marker_holds_unless_a_known_atom_of_an_and_fails(self):
        for marker, python, expected in (
                ('', '3.9', True),
                ("python_version < '3.10'", '3.9', True),
                ("python_version < '3.10'", '3.10', False),
                ('python_version >= "3.8"', '3.7', False),
                ("python_full_version == '3.9.*'", '3.9', True),
                ("python_version >= '3.8' and sys_platform == 'win32'", '3.9', False),
                ("sys_platform != 'win32'", '3.9', True),
                ("sys_platform == 'darwin'", '3.9', False),
                ("platform_system == 'Linux'", '3.9', True),
                ("platform_system != 'Linux'", '3.9', False),
                ("(python_version > '3.7')", '3.9', True),
                ("python_version < '3.8' or sys_platform == 'win32'", '3.9', True),
                ("implementation_name == 'pypy'", '3.9', True),
                ("sys_platform > 'linux'", '3.9', True),
                ("python_version < 'x'", '3.9', True)):
            with self.subTest(marker=marker, python=python):
                self.assertEqual(known.applies(marker, python), expected)

    def test_compare_pads_versions_and_reads_wildcards_and_compatible_releases(self):
        for found, operator, wanted, expected in (
                ((2, 6, 1), '>=', '3.3.1', False), ((3, 4), '==', '3.4.0', True), ((3, 4, 0), '===', '3.4', True),
                ((3, 4, 4), '~=', '3.4', True), ((3, 5, 0), '~=', '3.4.0', False), ((3, 4, 9), '~=', '3.4.0', True),
                ((2, 9), '==', '2.*', True), ((3, 0), '==', '2.*', False), ((3, 0), '!=', '2.*', True),
                ((2, 0), '>=', '2.*', None), ((1, 0), '<', '1.0.1', True), ((1, 0), '>', '0.9', True),
                ((1, 0), '<=', '1', True), ((1, 0), '!=', '1.0', False), (None, '==', '1.0', None),
                ((1, 0), '==', 'x', None)):
            with self.subTest(found=found, operator=operator, wanted=wanted):
                self.assertEqual(known.compare(found, operator, wanted), expected)

    def test_lines_leave_out_comments_options_urls_and_an_unreadable_file(self):
        directory = Path(tempfile.mkdtemp(prefix='oasis-known-problems-'))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = directory / 'requirements.txt'
        path.write_text('# a comment\n-r other.txt\n--index-url https://example.invalid\n\n'
                        'psycopg2==2.8.6  # pinned\nhttps://example.invalid/pkg.tar.gz\n  lxml\n')
        self.assertEqual(known.lines(path), ['psycopg2==2.8.6', 'lxml'])
        self.assertEqual(known.lines(directory / 'missing.txt'), [])
        (directory / 'binary.txt').write_bytes(b'\xff\xfe')
        self.assertEqual(known.lines(directory / 'binary.txt'), [])

    def test_pins_keep_the_applying_lines_and_an_override_replaces_its_name(self):
        lines = ["cryptography==2.6.1", "python-ldap==3.4.0 ; sys_platform != 'win32'",
                 "greenlet==0.4.15 ; python_version < '3.9'", "greenlet==1.1.0 ; python_version >= '3.9'",
                 'Python_Dateutil==2.7.3']
        found = known.pins(lines, '3.9', ['cryptography==3.3.1', 'cryptography<4'])
        self.assertEqual(found, {
            'cryptography': [('cryptography==3.3.1', [('==', '3.3.1')]), ('cryptography<4', [('<', '4')])],
            'python-ldap': [('python-ldap==3.4.0', [('==', '3.4.0')])],
            'greenlet': [('greenlet==1.1.0', [('==', '1.1.0')])],
            'python-dateutil': [('Python_Dateutil==2.7.3', [('==', '2.7.3')])]})
        self.assertTrue(known.pinned(found, 'python-ldap==3.4.0'))
        self.assertFalse(known.pinned(found, 'python-ldap==3.4.4'))
        self.assertFalse(known.pinned(found, 'pyyaml==5.4'))
        self.assertFalse(known.pinned(found, '==1'))


class RequirementProblemTests(unittest.TestCase):
    PINS = {'cryptography': [('cryptography==2.6.1', [('==', '2.6.1')])],
            'python-ldap': [('python-ldap==3.4.0', [('==', '3.4.0')])]}

    def problems(self, *entries):
        return known.requirement_problems([('shop_sale', entry) for entry in entries], self.PINS)

    def test_a_translated_or_known_name_is_a_distribution_and_an_unknown_import_name_is_not(self):
        self.assertEqual(self.problems('yaml', 'phonenumbers', 'python-jose', 'cv2', 'attr', 'ldap', 'json',
                                       'xml.etree', 'Crypto>=3.9'), [
            {'id': 'requirement:pyyaml', 'module': 'shop_sale', 'name': 'pyyaml', 'entry': 'pyyaml', 'kind': 'missing',
             'known': True, 'pin': None, 'proposal': None},
            {'id': 'requirement:phonenumbers', 'module': 'shop_sale', 'name': 'phonenumbers', 'entry': 'phonenumbers',
             'kind': 'missing', 'known': True, 'pin': None, 'proposal': None},
            {'id': 'requirement:python-jose', 'module': 'shop_sale', 'name': 'python-jose', 'entry': 'python-jose',
             'kind': 'missing', 'known': True, 'pin': None, 'proposal': None},
            {'id': 'requirement:cv2', 'module': 'shop_sale', 'name': 'cv2', 'entry': 'cv2', 'kind': 'missing',
             'known': False, 'pin': None, 'proposal': None},
            {'id': 'requirement:attr', 'module': 'shop_sale', 'name': 'attr', 'entry': 'attr', 'kind': 'missing',
             'known': False, 'pin': None, 'proposal': None},
            {'id': 'requirement:pycryptodome', 'module': 'shop_sale', 'name': 'pycryptodome',
             'entry': 'pycryptodome>=3.9', 'kind': 'missing', 'known': True, 'pin': None, 'proposal': None}])

    def test_a_conflict_names_the_pin_and_the_lowest_version_it_accepts(self):
        self.assertEqual(self.problems('cryptography>=3.3.1', 'cryptography>=1.0', 'python-ldap'), [
            {'id': 'requirement:cryptography', 'module': 'shop_sale', 'name': 'cryptography',
             'entry': 'cryptography>=3.3.1', 'kind': 'conflict', 'known': True, 'pin': 'cryptography==2.6.1',
             'proposal': 'cryptography==3.3.1'}])


class SystemLdapTests(unittest.TestCase):
    """system_ldap: OpenLDAP 2.6 or later without libldap_r, from pkg-config, else ldconfig -p."""

    def check(self, ldconfig='', pkg_config=None, which=True, failing=()):
        calls = []

        def run(command, **_kwargs):
            calls.append(command)
            name = Path(command[0]).name
            if name in failing:
                raise OSError('cannot run')
            if name == 'ldconfig':
                return subprocess.CompletedProcess(command, 0, ldconfig, '')
            if pkg_config is None:
                return subprocess.CompletedProcess(command, 1, '', 'Package ldap was not found')
            return subprocess.CompletedProcess(command, 0, pkg_config, '')
        with mock.patch.object(known.shutil, 'which', lambda name: f'/fake/bin/{name}' if which else None), \
                mock.patch.object(known.subprocess, 'run', run):
            return known.system_ldap(), calls

    def test_the_version_comes_from_pkg_config_else_from_the_libldap_names(self):
        for ldconfig, pkg_config, expected in (
                ('\tlibldap.so.2 => /usr/lib/libldap.so.2\n', '2.6.8\n', '2.6.8'),
                ('', '2.6.8\n', '2.6.8'),
                ('', '2.4.59\n', None),
                ('\tlibldap-2.6.so.0 => /usr/lib/libldap-2.6.so.0\n', None, '2.6'),
                ('\tlibldap-2.5.so.0 => /x\n\tlibldap-2.6.so.0 => /y\n', None, '2.6'),
                ('\tlibldap-2.5.so.0 => /usr/lib/libldap-2.5.so.0\n', None, None),
                ('\tlibldap.so.2 => /usr/lib/libldap.so.2\n', None, '2.6'),
                ('\tlibldap.so.2 => /usr/lib/libldap.so.2\n', 'unknown\n', '2.6'),
                ('\tlibc.so.6 => /usr/lib/libc.so.6\n', None, None),
                ('', None, None)):
            with self.subTest(ldconfig=ldconfig, pkg_config=pkg_config):
                self.assertEqual(self.check(ldconfig, pkg_config)[0], expected)

    def test_libldap_r_means_no_problem_whatever_pkg_config_says(self):
        found, calls = self.check('\tlibldap_r-2.4.so.2 => /usr/lib/libldap_r-2.4.so.2\n', '2.6.8\n')
        self.assertIsNone(found)
        self.assertEqual(calls[0][:2], ['/fake/bin/ldconfig', '-p'])
        self.assertEqual(len(calls), 1)

    def test_a_program_that_cannot_run_or_is_missing_says_nothing(self):
        self.assertEqual(self.check('\tlibldap.so.2 => /x\n', '2.6.8\n', failing=('ldconfig', 'pkg-config'))[0],
                         None)
        self.assertEqual(self.check('\tlibldap.so.2 => /x\n', None, failing=('pkg-config',))[0], '2.6')
        with mock.patch.object(known.Path, 'is_file', lambda _path: False):
            found, calls = self.check('\tlibldap.so.2 => /x\n', '2.6.8\n', which=False)
        self.assertEqual((found, calls), (None, []))

    def test_without_ldconfig_on_path_the_sbin_one_is_used(self):
        with mock.patch.object(known.Path, 'is_file', lambda path: str(path) == '/usr/sbin/ldconfig'):
            found, calls = self.check('\tlibldap.so.2 => /x\n', '2.6.8\n', which=False)
        self.assertEqual(found, '2.6')
        self.assertEqual([call[0] for call in calls], ['/usr/sbin/ldconfig'])


class OldPythonTests(unittest.TestCase):
    """Modules the environment's Python may run (3.7 and later) or that are named for it postpone their
    annotations, so `X | None` and `list[str]` are never evaluated at definition time."""

    def test_they_import_annotations_from_the_future(self):
        for name in ('known_problems', 'db_account', 'audit_dependencies', 'status_json'):
            with self.subTest(module=name):
                tree = ast.parse((TOOLS / f'{name}.py').read_text(encoding='utf-8'))
                self.assertTrue(any(isinstance(node, ast.ImportFrom) and node.module == '__future__'
                                    and [alias.name for alias in node.names] == ['annotations']
                                    for node in tree.body), name)


if __name__ == '__main__':
    unittest.main()
