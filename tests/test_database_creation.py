"""v0.20.0 S12: create-database is the one command that creates a database (tests/test_dev_users.py covers it
and its plan). install-module installs only into an existing database: a missing one is refused before Odoo
starts (odoo-bin -d <name> would create it), naming the create-database plan.

start and restart (v0.20.0 L19, the slice verifier's defect 2) open only existing databases too: odoo-bin creates
every database it is given that is missing (-d, or odoo.conf's db_name, a comma-separated list), so each one is
checked first and a missing one is refused (exit 2) naming the create-database plan; start without a database
(Odoo's database selector) runs as before. Without -d, the database also comes from PGDATABASE on 19.0 (its -d reads
that variable, over the configuration file; 15.0 does not read it) and from the configuration file of a later
-c/--config among the passed options instead of odoo.conf (v0.20.0 L22 (b)).

Synthetic fixtures with the fake docker and python of test_lifecycle, through the project wrappers (restart, which
has none, through the oasis entry point)."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import re
import shlex
import subprocess
import sys
import unittest
from pathlib import Path
import test_lifecycle as lifecycle


class CreationBase(unittest.TestCase):
    setUp_fixture = lifecycle.LifecycleTests.setUp
    invoke = lifecycle.LifecycleTests.invoke
    unchanged = lifecycle.LifecycleTests.unchanged

    def setUp(self):
        self.setUp_fixture()

    def plan_command(self):
        return shlex.join(['oasis', '--project', str(self.root), 'create-database', '--plan'])

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
        self.assertIn('The database must exist: install-module never creates one (create-database --plan does).',
                      result.stdout)
        self.assertNotIn('--confirm', result.stdout)
        self.unchanged()


class ServerBase(CreationBase):
    PORTS = ('--http-port=9000', '--gevent-port=9001')

    def missing(self, database):
        return f'Database {database} does not exist; create it with: {self.plan_command()}\n'

    def oasis(self, *args):
        return subprocess.run([sys.executable, '-B', str(lifecycle.STAGE / 'oasis'), '--project', str(self.root),
                               *args], text=True, cwd=self.root, env=self.env, capture_output=True,
                              stdin=subprocess.DEVNULL, timeout=60)

    def odoo_line(self, *args):
        return ' '.join(['odoo', str(self.source / 'odoo-bin'), '-c', str(self.root / 'dev/odoo.conf'), *args])

    def existing(self, *names):
        (self.root / 'commands.log.databases').write_text(''.join(f'{name}\n' for name in names))


class ServerDatabaseTests(ServerBase):

    def test_start_and_restart_refuse_a_missing_database_before_odoo_starts(self):
        (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text(f'http_port = {lifecycle.free_port()}\n'))
        cases = (('start', '-d', 'cc_dev_x'), ('start', '--database=cc_dev_x'), ('start', '-dcc_dev_x'),
                 ('start', '--detach', '-d', 'cc_dev_x'),
                 ('start', '--stop-after-init', '-d', 'cc_dev_x', '-i', 'base'),
                 ('start', '--stop-after-init', *self.PORTS, '-d', 'cc_dev_x', '-i', 'base'),
                 ('restart', '-d', 'cc_dev_x'), ('restart', '--database', 'cc_dev_x', '--dev', 'all'))
        for args in cases:
            with self.subTest(args=args):
                result = self.invoke(*args) if args[0] == 'start' else self.oasis(*args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', self.missing('cc_dev_x')))
                self.assertIn("datname = 'cc_dev_x'", self.log())
                self.assertEqual(self.odoo_lines(), [])
                self.commands.unlink()

    def test_each_database_of_odoo_conf_db_name_must_exist(self):
        # A free http_port: start's port checks come before the database's.
        (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text(
            f'http_port = {lifecycle.free_port()}\ndb_name = cc_dev_a, cc_dev_b\n'))
        self.existing('cc_dev_a')
        for args in (('start', '--stop-after-init', '-i', 'base'), ('start', '--detach'), ('start',),
                     ('restart',), ('restart', '--dev', 'all')):
            with self.subTest(args=args):
                result = self.invoke(*args) if args[0] == 'start' else self.oasis(*args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', self.missing('cc_dev_b')))
                self.assertIn("datname = 'cc_dev_a'", self.log())
                self.assertEqual(self.odoo_lines(), [])
                self.commands.unlink()
        # A database given with -d is the one Odoo opens: odoo.conf's db_name is not checked then.
        self.existing('cc_dev_c')
        result = self.invoke('start', '--stop-after-init', *self.PORTS, '-d', 'cc_dev_c', '-i', 'base')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(self.odoo_lines(), [self.odoo_line('--stop-after-init', *self.PORTS, '-d', 'cc_dev_c',
                                                            '-i', 'base')])
        self.assertNotIn("datname = 'cc_dev_b'", self.log())

    def test_an_existing_database_runs_exactly_as_before(self):
        self.env['FAKE_EXISTS'] = '1'
        result = self.invoke('start', '--stop-after-init', *self.PORTS, '-d', 'cc_dev_x', '-i', 'base')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(self.odoo_lines(), [self.odoo_line('--stop-after-init', *self.PORTS, '-d', 'cc_dev_x',
                                                            '-i', 'base')])
        self.commands.unlink()
        (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text('db_name = cc_dev_a,cc_dev_b\n'))
        result = self.invoke('start', '--stop-after-init', *self.PORTS, '-u', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(self.odoo_lines(), [self.odoo_line('--stop-after-init', *self.PORTS, '-u', 'coffee')])
        port = lifecycle.free_port()
        (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text(f'http_port = {port}\ndb_name = cc_dev_a\n'))
        for args, warning in ((('-d', 'cc_dev_x'), ''), ((), "WARNING: no database given (-d); Odoo will use "
                                                             "odoo.conf's db_name (cc_dev_a).\n")):
            with self.subTest(args=args):
                self.commands.unlink()
                result = self.invoke('start', *args)
                self.assertEqual((result.returncode, result.stdout), (0, ''))
                self.assertRegex(result.stderr, '^' + re.escape(warning)
                                 + rf'oasis start: http://localhost:{port} \(pid \d+\)\n$')
                self.assertEqual(self.odoo_lines(), [self.odoo_line(f'--http-port={port}', *args)])

    def test_start_without_a_database_runs_as_before(self):
        # Odoo's database selector: no database to check, so no query.
        for conf in ('', 'db_name = False\n', 'db_name =\n'):
            with self.subTest(conf=conf):
                (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text(conf))
                result = self.invoke('start', '--stop-after-init', *self.PORTS, '-u', 'coffee')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
                self.assertEqual(self.odoo_lines(), [self.odoo_line('--stop-after-init', *self.PORTS, '-u', 'coffee')])
                self.assertNotIn('pg_database', self.log())
                self.commands.unlink()
        # --print-command and Odoo's informational options never touch the service.
        self.env.pop('FAKE_EXISTS', None)
        result = self.invoke('start', '--print-command', '-d', 'cc_dev_x')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertNotIn('pg_database', self.log())
        result = self.invoke('start', '-d', 'cc_dev_x', '--version')
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('pg_database', self.log())


class SeriesAnswerTests(unittest.TestCase):
    """Review review-5cfcc5c198b45a72: a series table that cannot be read warns once and answers unknown, which
    checks PGDATABASE (fails closed) and keeps a -c path as given."""

    def answer(self, version):
        tools = Path(__file__).resolve().parents[1] / 'tools'
        script = (f'source {shlex.quote(str(tools / "server_args.sh"))}; ODOO_VERSION={shlex.quote(version)}; '
                  'configuration_reads_environment; odoo_reads_pgdatabase && echo pg; '
                  'odoo_expands_config_path && echo expand; true')
        result = subprocess.run(['bash', '-c', script], capture_output=True, text=True)
        return result.returncode, result.stdout, result.stderr

    def test_each_series_answers_from_the_table(self):
        self.assertEqual(self.answer('19.0'), (0, 'true\npg\nexpand\n', ''))
        self.assertEqual(self.answer('15.0'), (0, 'false\n', ''))

    def test_an_unreadable_table_warns_checks_pgdatabase_and_keeps_the_path(self):
        warning = ('WARNING: cannot read configuration_reads_environment of Odoo 9.9 from tools/odoo_versions.py; '
                   'checking PGDATABASE too.\n')
        self.assertEqual(self.answer('9.9'), (0, 'unknown\npg\n', warning * 3))


class EnvironmentDatabaseTests(ServerBase):
    """v0.20.0 L22 (b): 19.0's -d reads PGDATABASE (odoo/tools/config.py:377 env_name; the environment comes before
    the configuration file and after the command line, config.py:164-170), a comma-separated list. oasis never sets
    it, so a user's own PGDATABASE is what reaches Odoo."""

    def test_a_missing_pgdatabase_is_refused_before_odoo_starts(self):
        (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text(f'http_port = {lifecycle.free_port()}\n'))
        self.env['PGDATABASE'] = 'cc_dev_x'
        for args in (('start',), ('start', '--detach'), ('start', '--stop-after-init', '-i', 'base'),
                     ('start', '--stop-after-init', *self.PORTS, '-u', 'coffee'), ('restart',),
                     ('restart', '--dev', 'all')):
            with self.subTest(args=args):
                result = self.invoke(*args) if args[0] == 'start' else self.oasis(*args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', self.missing('cc_dev_x')))
                self.assertIn("datname = 'cc_dev_x'", self.log())
                self.assertEqual(self.odoo_lines(), [])
                self.commands.unlink()

    def test_pgdatabase_is_a_list_and_comes_before_odoo_conf_db_name(self):
        (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text(
            f'http_port = {lifecycle.free_port()}\ndb_name = cc_dev_a\n'))
        self.existing('cc_dev_a')
        for value, missing in (('cc_dev_a, cc_dev_b', 'cc_dev_b'), ('cc_dev_x', 'cc_dev_x')):
            with self.subTest(value=value):
                self.env['PGDATABASE'] = value
                result = self.invoke('start', '--stop-after-init', *self.PORTS, '-u', 'coffee')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', self.missing(missing)))
                self.assertEqual(self.odoo_lines(), [])
                self.commands.unlink()

    def test_an_existing_pgdatabase_runs_with_the_same_line_as_before(self):
        port = lifecycle.free_port()
        (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text(f'http_port = {port}\n'))
        self.existing('cc_dev_a', 'cc_dev_b')
        for value in ('cc_dev_a', 'cc_dev_a,cc_dev_b'):
            with self.subTest(value=value):
                self.env['PGDATABASE'] = value
                result = self.invoke('start', '--stop-after-init', *self.PORTS, '-u', 'coffee')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
                self.assertEqual(self.odoo_lines(), [self.odoo_line('--stop-after-init', *self.PORTS, '-u', 'coffee')])
                self.assertIn("datname = 'cc_dev_a'", self.log())
                self.commands.unlink()
        result = self.invoke('start')
        self.assertEqual((result.returncode, result.stdout), (0, ''))
        self.assertRegex(result.stderr, rf'^oasis start: http://localhost:{port} \(pid \d+\)\n$')
        self.assertEqual(self.odoo_lines(), [self.odoo_line(f'--http-port={port}')])

    def test_d_comes_before_pgdatabase_and_an_empty_one_hides_odoo_conf_db_name(self):
        (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text('db_name = cc_dev_b\n'))
        self.existing('cc_dev_c')
        self.env['PGDATABASE'] = 'cc_dev_x'
        result = self.invoke('start', '--stop-after-init', *self.PORTS, '-d', 'cc_dev_c', '-i', 'base')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(self.odoo_lines(), [self.odoo_line('--stop-after-init', *self.PORTS, '-d', 'cc_dev_c',
                                                            '-i', 'base')])
        self.assertNotIn("datname = 'cc_dev_x'", self.log())
        # Set but empty, it is an empty list that hides odoo.conf's db_name: Odoo's database selector, no query.
        self.commands.unlink()
        self.env['PGDATABASE'] = ''
        result = self.invoke('start', '--stop-after-init', *self.PORTS, '-u', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(self.odoo_lines(), [self.odoo_line('--stop-after-init', *self.PORTS, '-u', 'coffee')])
        self.assertNotIn('pg_database', self.log())

    def test_print_command_and_informational_options_never_check_pgdatabase(self):
        self.env['PGDATABASE'] = 'cc_dev_x'
        result = self.invoke('start', '--print-command')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertNotIn('pg_database', self.log())
        result = self.invoke('start', '--version')
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('pg_database', self.log())

    def test_odoo_15_does_not_read_pgdatabase(self):
        # 15.0's -d has no environment variable (odoo/tools/config.py:239): PGDATABASE never reaches Odoo there.
        lifecycle.use_odoo_15(self)
        ports = ('--http-port=9000', '--longpolling-port=9001')
        self.env['PGDATABASE'] = 'cc_dev_x'
        result = self.invoke('start', '--stop-after-init', *ports, '-u', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(self.odoo_lines(), [self.odoo_line('--stop-after-init', *ports, '-u', 'coffee')])
        self.assertNotIn('pg_database', self.log())


class ConfigFileDatabaseTests(ServerBase):
    """v0.20.0 L22 (b): a later -c/--config among the passed options is the file Odoo reads (optparse: the last one
    wins), so its db_name is checked instead of odoo.conf's, with the same reader."""

    def other_conf(self, options):
        path = self.root / 'dev/other.conf'
        path.write_text(lifecycle.conf_text(options))
        return path

    def forms(self, path):
        return (('-c', str(path)), (f'-c{path}',), ('--config', str(path)), (f'--config={path}',),
                ('--conf', str(path)), (f'--c={path}',), ('-c', 'dev/other.conf'))

    def test_a_missing_db_name_of_a_later_config_is_refused(self):
        (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text(f'http_port = {lifecycle.free_port()}\n'))
        path = self.other_conf('db_name = cc_dev_a, cc_dev_x\n')
        self.existing('cc_dev_a')
        cases = [('start', '--stop-after-init', *self.PORTS, *form, '-u', 'coffee') for form in self.forms(path)]
        cases += [('start', '--detach', '-c', str(path)), ('start', '-c', str(path)), ('restart', '--config', str(path))]
        for args in cases:
            with self.subTest(args=args):
                result = self.invoke(*args) if args[0] == 'start' else self.oasis(*args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', self.missing('cc_dev_x')))
                self.assertIn("datname = 'cc_dev_a'", self.log())
                self.assertEqual(self.odoo_lines(), [])
                self.commands.unlink()

    def test_an_existing_db_name_of_a_later_config_runs_and_odoo_conf_db_name_is_not_checked(self):
        (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text('db_name = cc_dev_missing\n'))
        path = self.other_conf('db_name = cc_dev_a\n')
        self.existing('cc_dev_a')
        for form in self.forms(path):
            with self.subTest(form=form):
                result = self.invoke('start', '--stop-after-init', *self.PORTS, *form, '-u', 'coffee')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
                self.assertEqual(self.odoo_lines(), [self.odoo_line('--stop-after-init', *self.PORTS, *form, '-u',
                                                                    'coffee')])
                self.assertIn("datname = 'cc_dev_a'", self.log())
                self.assertNotIn('cc_dev_missing', self.log())
                self.commands.unlink()

    def test_a_later_config_without_db_name_is_odoo_s_database_selector(self):
        (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text('db_name = cc_dev_missing\n'))
        for options in ('', 'db_name = False\n'):
            with self.subTest(options=options):
                path = self.other_conf(options)
                result = self.invoke('start', '--stop-after-init', *self.PORTS, '-c', str(path), '-u', 'coffee')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
                self.assertEqual(self.odoo_lines(), [self.odoo_line('--stop-after-init', *self.PORTS, '-c', str(path),
                                                                    '-u', 'coffee')])
                self.assertNotIn('pg_database', self.log())
                self.commands.unlink()

    def test_pgdatabase_comes_before_a_later_config_on_19(self):
        path = self.other_conf('db_name = cc_dev_a\n')
        self.existing('cc_dev_a')
        self.env['PGDATABASE'] = 'cc_dev_x'
        result = self.invoke('start', '--stop-after-init', *self.PORTS, '-c', str(path), '-u', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', self.missing('cc_dev_x')))
        self.assertEqual(self.odoo_lines(), [])


if __name__ == '__main__':
    unittest.main()
