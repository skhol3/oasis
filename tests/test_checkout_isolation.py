"""Per-checkout database names and guards, through the public project wrappers.

Every project is a synthetic fixture with the fake docker/python harness of test_lifecycle;
a `[tooling].checkout_slug` stands in for a linked worktree's derived slug.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import re
import shlex
import subprocess
import unittest
import test_lifecycle as lifecycle

SLUG = 'wt_1'
NAMESPACE = (f'Databases of checkout {SLUG} must use cc_dev_{SLUG}_<name> or '
             f'cc_test_{SLUG}_<name>: ')
TOO_LONG = 'Database names must be at most 63 bytes: {}\n'
NO_SIBLING_ROOM = 'Test databases with an _update sibling must be at most 56 bytes: {}\n'


def utf8_letters_pass_charset(locale):
    """True when bash in this locale lets a non-ASCII letter through the name charset."""
    probe = subprocess.run(['bash', '-c', '[[ é =~ ^[A-Za-z0-9_]+$ ]]'],
                           env={'LC_ALL': locale, 'PATH': '/usr/bin:/bin'}, capture_output=True)
    return probe.returncode == 0 and not probe.stderr


class IsolationBase(unittest.TestCase):
    setUp_fixture = lifecycle.LifecycleTests.setUp
    invoke = lifecycle.LifecycleTests.invoke
    unchanged = lifecycle.LifecycleTests.unchanged

    profile_extra = ''

    def missing(self, database):
        """The refusal of a missing database: create-database is the one command that creates one, through its plan
        (v0.20.0 S12)."""
        plan = shlex.join(['oasis', '--project', str(self.root), 'create-database', '--plan'])
        return f'Database {database} does not exist; create it with: {plan}\n'

    def setUp(self):
        self.setUp_fixture()
        self.write_profile()

    def write_profile(self, extra=''):
        lifecycle.write_config(self.root, lifecycle.WORKSPACE + self.profile_extra + extra)

    def odoo_lines(self):
        return [lifecycle.any_run_database(lifecycle.any_test_port(line))
                for line in self.commands.read_text().splitlines() if line.startswith('odoo ')]

    def odoo_call(self, *args):
        return ' '.join(['odoo', str(self.source / 'odoo-bin'), '-c', str(self.root / 'dev/odoo.conf'),
                         *args])

    def assert_rejected(self, result, stderr):
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', stderr))
        self.unchanged()

    def add_module(self, name):
        (self.root / name).mkdir()
        (self.root / name / '__manifest__.py').touch()


class SluggedCheckoutTests(IsolationBase):
    profile_extra = f"checkout_slug = '{SLUG}'\n"

    def test_test_module_default_gets_the_slug(self):
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertRegex(self.commands.read_text(), r'sh cc_test_wt_1_coffee_r[0-9a-f]{6}\n')
        self.assertEqual(self.odoo_lines(), [self.odoo_call(
            '--http-port=<free>', '--gevent-port=<free>', '-d', 'cc_test_wt_1_coffee_r<run>', '-i', 'coffee', '--without-demo', '--test-tags',
            '/coffee', '--stop-after-init')])

    def test_reuse_default_and_configured_names_get_the_slug(self):
        ports = ('--http-port=<free>', '--gevent-port=<free>')
        tail = ('--test-tags', '/coffee', '--stop-after-init')
        for database in ('cc_test_wt_1_coffee', 'cc_test_wt_1_shared'):
            with self.subTest(database=database):
                # The first run installs in the working database, the next one updates it.
                for module_arguments in (('-i', 'coffee', '--without-demo'), ('-u', 'coffee')):
                    result = self.invoke('test-module', '--reuse', 'coffee')
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
                    self.assertEqual(self.odoo_lines()[-1],
                                     self.odoo_call(*ports, '-d', database, *module_arguments, *tail))
            self.write_profile("test_database = 'cc_test_shared'\n")
        self.assertNotIn(' cc_test_shared', self.commands.read_text())

    def test_configured_test_database_gets_the_slug_after_the_prefix(self):
        self.write_profile("test_database = 'cc_test_shared'\n")
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(self.odoo_lines(), [self.odoo_call(
            '--http-port=<free>', '--gevent-port=<free>', '-d', 'cc_test_wt_1_shared', '-i', 'coffee', '--without-demo', '--test-tags', '/coffee',
            '--stop-after-init')])
        self.assertNotIn(' cc_test_shared', self.commands.read_text())

    def test_verify_module_defaults_get_the_slug(self):
        for extra, test, update in (
                ('', 'cc_test_wt_1_coffee_r<run>', 'cc_test_wt_1_coffee_r<run>_update'),
                ("test_database = 'cc_test_shared'\n", 'cc_test_wt_1_shared', 'cc_test_wt_1_shared_update')):
            with self.subTest(test=test):
                self.write_profile(extra)
                self.commands.unlink(missing_ok=True)
                result = self.invoke('verify-module', 'coffee')
                self.assertEqual((result.returncode, result.stderr), (0, ''))
                pattern = re.escape(f'tests_database={test}\nupdate_database={update}\n').replace(
                    re.escape('<run>'), '[0-9a-f]{6}')
                self.assertRegex(result.stdout, pattern)
                self.assertEqual(self.odoo_lines(), [
                    self.odoo_call('--http-port=<free>', '--gevent-port=<free>', '-d', test, '-i', 'coffee', '--without-demo', '--test-tags', '/coffee',
                                   '--stop-after-init'),
                    self.odoo_call('-d', update, '-i', 'coffee', '--without-demo', '--stop-after-init'),
                    self.odoo_call('-d', update, '-u', 'coffee', '--stop-after-init')])

    def test_install_module_default_gets_the_slug(self):
        # The database exists: install-module installs into an existing database only (v0.20.0 S12).
        self.env['FAKE_EXISTS'] = '1'
        result = self.invoke('install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(self.odoo_lines(), [self.odoo_call(
            '-d', 'cc_dev_wt_1_coffee', '-i', 'coffee', '--without-demo', '--stop-after-init')])
        result = self.invoke('install-module', '--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('defaults to cc_dev_wt_1_<module>.', result.stdout)

    def test_main_checkout_names_are_rejected_before_any_command(self):
        cases = [
            ('test-module', ('coffee', 'cc_test_coffee'), 'cc_test_coffee'),
            ('verify-module', ('coffee', 'cc_test_coffee'), 'cc_test_coffee'),
            ('verify-module', ('coffee', 'cc_test_wt_1_coffee', 'cc_test_coffee_update'), 'cc_test_coffee_update'),
            ('install-module', ('coffee', 'cc_dev_coffee'), 'cc_dev_coffee'),
            ('install-module', ('--with-demo', 'coffee', 'cc_test_coffee'), 'cc_test_coffee'),
            ('update-module', ('coffee', 'cc_dev_coffee'), 'cc_dev_coffee'),
            ('odoo-shell', ('cc_dev_coffee',), 'cc_dev_coffee'),
            ('start', ('-d', 'cc_dev_coffee'), 'cc_dev_coffee'),
            ('drop-database', ('cc_test_coffee',), 'cc_test_coffee'),
            ('module-status', ('coffee', 'cc_dev_coffee'), 'cc_dev_coffee'),
            # Another checkout's namespace and the bare namespace are refused as well.
            ('update-module', ('coffee', 'cc_dev_wt_2_coffee'), 'cc_dev_wt_2_coffee'),
            ('odoo-shell', ('cc_dev_wt_1_',), 'cc_dev_wt_1_'),
        ]
        self.env['FAKE_EXISTS'] = '1'
        for command, args, name in cases:
            with self.subTest(command=command, args=args):
                self.assert_rejected(self.invoke(command, *args), NAMESPACE + name + '\n')

    def test_slugged_names_are_accepted(self):
        self.env['FAKE_EXISTS'] = '1'
        result = self.invoke('update-module', 'coffee', 'cc_dev_wt_1_coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        result = self.invoke('odoo-shell', 'cc_test_wt_1_coffee', input='print(42)\n')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, 'print(42)\n', ''))
        result = self.invoke('install-module', '--with-demo', 'coffee', 'cc_test_wt_1_demo')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        result = self.invoke('test-module', 'coffee', 'cc_test_wt_1_other')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(self.odoo_lines(), [
            self.odoo_call('-d', 'cc_dev_wt_1_coffee', '-u', 'coffee', '--stop-after-init'),
            ' '.join(['odoo', str(self.source / 'odoo-bin'), 'shell', '-c',
                      str(self.root / 'dev/odoo.conf'), '-d', 'cc_test_wt_1_coffee']),
            self.odoo_call('-d', 'cc_test_wt_1_demo', '-i', 'coffee', '--with-demo', '--stop-after-init'),
            self.odoo_call('--http-port=<free>', '--gevent-port=<free>', '-d', 'cc_test_wt_1_other', '-i', 'coffee', '--without-demo', '--test-tags',
                           '/coffee', '--stop-after-init')])

    def test_install_update_and_shell_refuse_a_missing_database(self):
        # v0.20.0 S12: install-module too (before, it created the missing database).
        for command, args in (('install-module', ('coffee',)), ('update-module', ('coffee', 'cc_dev_wt_1_coffee')),
                              ('odoo-shell', ('cc_dev_wt_1_coffee',))):
            with self.subTest(command=command):
                self.commands.unlink(missing_ok=True)
                result = self.invoke(command, *args, input='print(42)\n')
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, '', self.missing('cc_dev_wt_1_coffee')))
                log = self.commands.read_text()
                self.assertIn("datname = 'cc_dev_wt_1_coffee'", log)
                self.assertNotIn('createdb', log)
                self.assertEqual(self.odoo_lines(), [])

    def test_start_guards_every_database_option_form(self):
        self.env['FAKE_EXISTS'] = '1'
        port = lifecycle.free_port()
        (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text(f'http_port = {port}\n'))
        forms = (lambda name: ('-d', name), lambda name: ('-d' + name,),
                 lambda name: ('--database', name), lambda name: ('--database=' + name,),
                 lambda name: ('--datab', name), lambda name: ('--databas=' + name,))
        for form in forms:
            args = (*form('cc_dev_wt_1_coffee'), '--workers=0')
            with self.subTest(accepted=args):
                self.commands.unlink(missing_ok=True)
                result = self.invoke('start', *args)
                self.assertEqual((result.returncode, result.stdout), (0, ''))
                self.assertRegex(result.stderr, rf'^oasis start: http://localhost:{port} \(pid \d+\)\n$')
                self.assertEqual(self.odoo_lines(), [self.odoo_call(f'--http-port={port}', *args)])
            args = ('--workers=0', *form('cc_dev_coffee'))
            with self.subTest(rejected=args):
                self.commands.unlink(missing_ok=True)
                self.assert_rejected(self.invoke('start', *args), NAMESPACE + 'cc_dev_coffee\n')
        self.commands.unlink(missing_ok=True)
        self.assert_rejected(self.invoke('start', '-d'),
                             'Database name must use only letters, numbers, and underscores.\n')

    def test_63_byte_boundary_for_managed_names(self):
        fits = 'cc_dev_wt_1_' + 'a' * 51
        too_long = fits + 'a'
        self.assertEqual((len(fits.encode()), len(too_long.encode())), (63, 64))
        # The database exists: install-module installs into an existing database only (v0.20.0 S12).
        self.env['FAKE_EXISTS'] = '1'
        result = self.invoke('install-module', 'coffee', fits)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(self.odoo_lines(), [self.odoo_call(
            '-d', fits, '-i', 'coffee', '--without-demo', '--stop-after-init')])
        self.commands.unlink()
        for command, args in (('install-module', ('coffee', too_long)),
                              ('update-module', ('coffee', too_long)),
                              ('odoo-shell', (too_long,)),
                              ('start', ('-d', too_long)),
                              ('test-module', ('coffee', 'cc_test_wt_1_' + 'a' * 51))):
            with self.subTest(command=command):
                self.assert_rejected(self.invoke(command, *args), TOO_LONG.format(args[-1]))

    def test_63_byte_limit_counts_utf8_bytes(self):
        locale = next((name for name in ('en_US.UTF-8', 'C.UTF-8') if utf8_letters_pass_charset(name)), None)
        if locale is None:
            self.skipTest('no locale lets a non-ASCII letter through the bash name charset')
        self.env['LC_ALL'] = locale
        name = 'cc_dev_wt_1_é' + 'a' * 50
        self.assertEqual((len(name), len(name.encode())), (63, 64))
        self.assert_rejected(self.invoke('install-module', 'coffee', name), TOO_LONG.format(name))

    def test_56_byte_boundary_for_test_databases_with_update_sibling(self):
        fits_module, long_module = 'm' * 43, 'm' * 44
        self.add_module(fits_module)
        self.add_module(long_module)
        # Disposable defaults are shortened to fit (test_disposable_tests checks the format).
        result = self.invoke('verify-module', long_module)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        tests = re.search(r'^tests_database=(\S+)$', result.stdout, re.M).group(1)
        self.assertEqual(len(tests.encode()), 56)
        self.assertIn(f'update_database={tests}_update\n', result.stdout)
        self.commands.unlink()
        test = 'cc_test_wt_1_' + long_module
        self.assertEqual(len(test.encode()), 57)
        for args in ((long_module, test), (long_module, test, test + '_update')):
            with self.subTest(args=args):
                self.assert_rejected(self.invoke('verify-module', *args), NO_SIBLING_ROOM.format(test))
        # Without an _update sibling the test database may use the whole 63 bytes.
        result = self.invoke('verify-module', 'coffee', 'cc_test_wt_1_' + 'a' * 50)
        self.assertEqual((result.returncode, result.stderr), (0, ''))

    def test_configured_test_database_length_counts_the_slug(self):
        fits = 'cc_test_' + 'a' * 43
        self.write_profile(f"test_database = '{fits}'\n")
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertIn(' -d cc_test_wt_1_' + 'a' * 43 + ' -i coffee', self.commands.read_text())
        self.commands.unlink()
        self.write_profile(f"test_database = '{fits}a'\n")
        self.assert_rejected(self.invoke('test-module', 'coffee'),
                             'ERROR: Tooling test database exceeds 56 bytes with checkout slug wt_1.\n')


class MainCheckoutTests(IsolationBase):
    """Without a slug the previous names hold; the new guards apply to every checkout."""

    def test_defaults_keep_previous_names(self):
        for command, expected in (
                ('test-module', '-d cc_test_coffee_r<run> -i coffee --without-demo --test-tags /coffee'),
                ('install-module', '-d cc_dev_coffee -i coffee --without-demo --stop-after-init')):
            with self.subTest(command=command):
                # install-module's default database exists (v0.20.0 S12: it never creates one); test-module's is new.
                self.env['FAKE_EXISTS'] = '1' if command == 'install-module' else '0'
                result = self.invoke(command, 'coffee')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
                self.assertIn(expected, '\n'.join(self.odoo_lines()))
        self.env['FAKE_EXISTS'] = '0'
        result = self.invoke('verify-module', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertRegex(result.stdout, r'tests_database=(cc_test_coffee_r[0-9a-f]{6})\nupdate_database=\1_update\n')
        self.write_profile("test_database = 'cc_test_a'\n")
        result = self.invoke('verify-module', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn('tests_database=cc_test_a\nupdate_database=cc_test_a_update\n', result.stdout)

    def test_previous_test_prefix_message_is_unchanged(self):
        for name in ('other_db', 'cc_dev_coffee'):
            with self.subTest(name=name):
                self.assert_rejected(self.invoke('test-module', 'coffee', name),
                                     'Test databases must use the cc_test_ prefix.\n')

    def test_update_shell_install_and_start_require_managed_names(self):
        message = 'Managed databases must use cc_dev_<name> or cc_test_<name>: other_db\n'
        self.env['FAKE_EXISTS'] = '1'
        for command, args in (('update-module', ('coffee', 'other_db')), ('odoo-shell', ('other_db',)),
                              ('install-module', ('coffee', 'other_db')), ('start', ('--database=other_db',))):
            with self.subTest(command=command):
                self.assert_rejected(self.invoke(command, *args), message)

    def test_main_names_are_accepted_and_start_without_database_is_unchanged(self):
        self.env['FAKE_EXISTS'] = '1'
        port = lifecycle.free_port()
        (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text(f'http_port = {port}\n'))
        for command, args, expected in (
                ('update-module', ('coffee', 'cc_test_coffee'), self.odoo_call(
                    '-d', 'cc_test_coffee', '-u', 'coffee', '--stop-after-init')),
                ('start', ('-d', 'cc_dev_coffee'), self.odoo_call(f'--http-port={port}', '-d', 'cc_dev_coffee')),
                ('start', ('--workers=0',), self.odoo_call(f'--http-port={port}', '--workers=0'))):
            with self.subTest(command=command, args=args):
                self.commands.unlink(missing_ok=True)
                result = self.invoke(command, *args)
                self.assertEqual((result.returncode, result.stdout), (0, ''))
                started = rf'^oasis start: http://localhost:{port} \(pid \d+\)\n$'
                self.assertRegex(result.stderr, started if command == 'start' else '^$')
                self.assertEqual(self.odoo_lines(), [expected])

    def test_update_refuses_a_missing_main_database(self):
        result = self.invoke('update-module', 'coffee', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', self.missing('cc_dev_coffee')))
        self.assertNotIn('createdb', self.commands.read_text())
        self.assertEqual(self.odoo_lines(), [])

    def test_63_byte_limit_applies_without_slug(self):
        fits = 'cc_dev_' + 'a' * 56
        # The database exists: install-module installs into an existing database only (v0.20.0 S12).
        self.env['FAKE_EXISTS'] = '1'
        result = self.invoke('install-module', 'coffee', fits)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.commands.unlink()
        self.assert_rejected(self.invoke('install-module', 'coffee', fits + 'a'), TOO_LONG.format(fits + 'a'))


if __name__ == '__main__':
    unittest.main()
