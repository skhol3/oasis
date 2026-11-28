"""v0.20.0 S12: init-dev-database is the one command that creates a database (tests/test_dev_users.py covers it
and its plan). install-module installs only into an existing database: a missing one is refused before Odoo
starts (odoo-bin -d <name> would create it), naming the init-dev-database plan.

Synthetic fixtures with the fake docker and python of test_lifecycle, through the project wrappers."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import shlex
import unittest
import test_lifecycle as lifecycle


class CreationBase(unittest.TestCase):
    setUp_fixture = lifecycle.LifecycleTests.setUp
    invoke = lifecycle.LifecycleTests.invoke
    unchanged = lifecycle.LifecycleTests.unchanged

    def setUp(self):
        self.setUp_fixture()

    def plan_command(self):
        return shlex.join(['oasis', '--project', str(self.root), 'init-dev-database', '--plan'])

    def log(self):
        return self.commands.read_text() if self.commands.exists() else ''

    def created(self):
        return [line for line in self.log().splitlines() if 'createdb' in line]

    def odoo_lines(self):
        return [line for line in self.log().splitlines() if line.startswith('odoo ')]


class InstallModuleTests(CreationBase):
    def test_an_existing_database_installs_as_before(self):
        self.env['FAKE_EXISTS'] = '1'
        result = self.invoke('install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(self.odoo_lines(), [
            'odoo ' + str(self.source / 'odoo-bin') + ' -c ' + str(self.root / 'dev/odoo.conf')
            + ' -d cc_dev_coffee -i coffee --without-demo --stop-after-init'])
        self.assertEqual(self.created(), [])

    def test_a_missing_database_is_refused_before_odoo_starts_naming_the_plan(self):
        # The default database and an explicit one, dev or test: nothing is created, Odoo never starts.
        for args, database in ((('coffee',), 'cc_dev_coffee'), (('--with-demo', 'coffee', 'cc_test_x'), 'cc_test_x')):
            with self.subTest(args=args):
                result = self.invoke('install-module', *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
                    f'Database {database} does not exist; create it with: {self.plan_command()}\n')))
                self.assertIn(f"datname = '{database}'", self.log())
                self.assertEqual((self.created(), self.odoo_lines()), ([], []))
                self.commands.unlink()

    def test_confirm_and_dry_run_are_no_longer_options(self):
        for exists in ('0', '1'):
            for args, option in ((('coffee', '--confirm', 'cc_dev_coffee'), '--confirm'),
                                 (('coffee', '--confirm=cc_dev_coffee'), '--confirm=cc_dev_coffee'),
                                 (('coffee', '--dry-run'), '--dry-run')):
                with self.subTest(exists=exists, args=args):
                    self.env['FAKE_EXISTS'] = exists
                    result = self.invoke('install-module', *args)
                    self.assertEqual((result.returncode, result.stdout, result.stderr),
                                     (2, '', f'Unknown option: {option}\n'))
                    self.unchanged()

    def test_unknown_options_usage_and_help_as_before(self):
        result = self.invoke('install-module', '--bogus', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', 'Unknown option: --bogus\n'))
        self.unchanged()
        result = self.invoke('install-module', 'coffee', 'cc_dev_a', 'extra')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', 'Usage: install-module [--with-demo] <module> [database]\n'))
        self.unchanged()
        result = self.invoke('install-module', '--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout.splitlines()[0], 'Usage: install-module [--with-demo] <module> [database]')
        self.assertIn('The database must exist: install-module never creates one (init-dev-database --plan does).',
                      result.stdout)
        self.assertNotIn('--confirm', result.stdout)
        self.unchanged()


if __name__ == '__main__':
    unittest.main()
