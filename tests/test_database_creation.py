"""v0.20.0 S5 and S6: creating a database is the user's decision. create-database always, and install-module
when its database does not exist, are Tier B: a dry run, a refusal naming the exact --confirm command, and the
creation only with it; `create-database --plan` asks the name and the kind and chooses neither.

Synthetic fixtures with the fake docker and python of test_lifecycle, through the project wrappers and the
entry point."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import json
from pathlib import Path
import shlex
import subprocess
import sys
import unittest
import test_lifecycle as lifecycle

ROOT = Path(__file__).resolve().parents[1]


class CreationBase(unittest.TestCase):
    setUp_fixture = lifecycle.LifecycleTests.setUp
    invoke = lifecycle.LifecycleTests.invoke
    unchanged = lifecycle.LifecycleTests.unchanged

    def setUp(self):
        self.setUp_fixture()

    def oasis(self, *args):
        """The command through the entry point, as an agent runs it."""
        return subprocess.run([sys.executable, '-B', str(ROOT / 'oasis'), '--project', str(self.root), *args],
                              text=True, capture_output=True, env=self.env, input='', timeout=60)

    def confirm(self, *args):
        return shlex.join(['oasis', '--project', str(self.root), *args])

    def log(self):
        return self.commands.read_text() if self.commands.exists() else ''

    def created(self):
        return [line for line in self.log().splitlines() if 'createdb' in line]

    def odoo_lines(self):
        return [line for line in self.log().splitlines() if line.startswith('odoo ')]


class CreateDatabaseTests(CreationBase):
    def test_without_confirm_it_refuses_naming_the_exact_command(self):
        for database, kind in (('cc_dev_coffee', 'dev'), ('cc_test_coffee', 'test')):
            with self.subTest(database=database):
                result = self.invoke('create-database', database)
                command = self.confirm('create-database', database, '--confirm', database)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
                    f'ERROR: create-database creates the {kind} database {database} (Tier B: it needs explicit '
                    f'confirmation); nothing changed. Run: {command}\n')))
                self.unchanged()

    def test_a_confirm_that_names_another_database_refuses(self):
        for confirm in (('--confirm', 'cc_dev_other'), ('--confirm=cc_dev_other',)):
            with self.subTest(confirm=confirm):
                result = self.invoke('create-database', 'cc_dev_coffee', *confirm)
                command = self.confirm('create-database', 'cc_dev_coffee', '--confirm', 'cc_dev_coffee')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
                    'ERROR: --confirm cc_dev_other does not name the database cc_dev_coffee; nothing changed. '
                    f'Run: {command}\n')))
                self.unchanged()

    def test_dry_run_prints_the_database_and_its_kind(self):
        for database, kind in (('cc_dev_coffee', 'dev'), ('cc_test_coffee', 'test')):
            with self.subTest(database=database):
                result = self.invoke('create-database', database, '--dry-run')
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (0, f'database: {database}\nkind: {kind}\ndry run: nothing changed\n', ''))
                self.unchanged()

    def test_with_confirm_it_creates_as_before(self):
        result = self.invoke('create-database', 'cc_dev_coffee', '--confirm', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, 'Database ready: cc_dev_coffee\n', ''))
        self.assertEqual(len(self.created()), 1)
        self.assertIn(' sh cc_dev_coffee\n', self.log())

    def test_the_name_guards_come_first_as_before(self):
        for args, stderr in (
                (('other_db', '--confirm', 'other_db'),
                 'Managed databases must use cc_dev_<name> or cc_test_<name>: other_db\n'),
                (('other_db', '--dry-run'), 'Managed databases must use cc_dev_<name> or cc_test_<name>: other_db\n'),
                (('cc_dev_x_trash_20261124_101500',),
                 'Database names ending in _trash_<YYYYMMDD>_<HHMMSS> are reserved for the trash: '
                 'cc_dev_x_trash_20261124_101500\n')):
            with self.subTest(args=args):
                result = self.invoke('create-database', *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', stderr))
                self.unchanged()

    def test_usage_errors(self):
        usage = ('Usage: {0} <cc_dev_*|cc_test_*> [--dry-run | --confirm <database>]\n'
                 '       {0} --plan [--json] [--answer <id>=<value>]... [--answers <file.json>]\n').format(
            self.root / 'dev/scripts/create-database')
        for args in ((), ('cc_dev_a', 'cc_dev_b'), ('cc_dev_a', '--confirm'), ('cc_dev_a', '--dry'),
                     ('cc_dev_a', '--dry-run', '--dry-run'), ('cc_dev_a', '--confirm', 'x', '--confirm', 'x')):
            with self.subTest(args=args):
                result = self.invoke('create-database', *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', usage))
                self.unchanged()
        result = self.invoke('create-database', '--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(usage), result.stdout)
        self.assertIn('Tier B (oasis policy --json)', result.stdout)


class InstallModuleCreationTests(CreationBase):
    def test_an_existing_database_installs_without_confirmation_as_before(self):
        self.env['FAKE_EXISTS'] = '1'
        result = self.invoke('install-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(self.odoo_lines(), [
            'odoo ' + str(self.source / 'odoo-bin') + ' -c ' + str(self.root / 'dev/odoo.conf')
            + ' -d cc_dev_coffee -i coffee --without-demo --stop-after-init'])

    def test_a_missing_database_needs_confirm(self):
        # The command names the database, also when it is install-module's default.
        for args, database, kind, named in (
                (('coffee',), 'cc_dev_coffee', 'dev', ('coffee', 'cc_dev_coffee')),
                (('--with-demo', 'coffee', 'cc_test_x'), 'cc_test_x', 'test', ('--with-demo', 'coffee', 'cc_test_x'))):
            with self.subTest(args=args):
                result = self.invoke('install-module', *args)
                command = self.confirm('install-module', *named, '--confirm', database)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
                    f'ERROR: install-module creates the missing {kind} database {database} to install coffee '
                    f'(Tier B: it needs explicit confirmation); nothing changed. Run: {command}\n')))
                self.assertEqual((self.created(), self.odoo_lines()), ([], []))
                self.commands.unlink()

    def test_a_missing_database_with_confirm_is_created_and_installed(self):
        result = self.invoke('install-module', 'coffee', 'cc_dev_coffee', '--confirm', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(len([line for line in self.log().splitlines() if 'createdb -U' in line]), 1)
        self.assertEqual(self.odoo_lines(), [
            'odoo ' + str(self.source / 'odoo-bin') + ' -c ' + str(self.root / 'dev/odoo.conf')
            + ' -d cc_dev_coffee -i coffee --without-demo --stop-after-init'])

    def test_a_confirm_that_names_another_database_refuses_even_when_it_exists(self):
        for exists in ('0', '1'):
            with self.subTest(exists=exists):
                self.env['FAKE_EXISTS'] = exists
                result = self.invoke('install-module', 'coffee', '--confirm', 'cc_dev_other')
                command = self.confirm('install-module', 'coffee', 'cc_dev_coffee', '--confirm', 'cc_dev_coffee')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
                    'ERROR: --confirm cc_dev_other does not name the database cc_dev_coffee; nothing changed. '
                    f'Run: {command}\n')))
                self.assertEqual(self.odoo_lines(), [])
                self.commands.unlink()

    def test_dry_run_says_whether_it_would_create_the_database(self):
        for exists, state in (('0', 'new: install-module creates it'), ('1', 'existing')):
            with self.subTest(exists=exists):
                self.env['FAKE_EXISTS'] = exists
                result = self.invoke('install-module', '--with-demo', 'coffee', '--dry-run')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, (
                    f'database: cc_dev_coffee ({state})\nkind: dev\nmodule: coffee\ndemo: yes\n'
                    'dry run: nothing changed\n'), ''))
                self.assertEqual((self.created(), self.odoo_lines()), ([], []))
                self.commands.unlink()

    def test_unknown_options_and_usage_as_before(self):
        result = self.invoke('install-module', '--bogus', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', 'Unknown option: --bogus\n'))
        self.unchanged()
        result = self.invoke('install-module', 'coffee', 'cc_dev_a', 'extra')
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.assertTrue(result.stderr.startswith('Usage: install-module [--with-demo] <module> [database]\n'))
        self.unchanged()


class CreateDatabasePlanTests(CreationBase):
    def plan(self, *args):
        result = self.oasis('create-database', '--plan', '--json', *args)
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        return json.loads(result.stdout)

    def test_unanswered_the_name_and_the_kind_are_open_with_no_recommended_answer(self):
        document = self.plan()
        self.assertEqual({key: document[key] for key in ('format', 'version', 'command', 'checkout', 'complete',
                                                          'open', 'databases')},
                         {'format': 'oasis-database-plan', 'version': 1, 'command': 'create-database',
                          'checkout': str(self.root), 'complete': False, 'open': ['kind', 'suffix'], 'databases': []})
        self.assertEqual(document['questions'], [
            {'id': 'kind', 'text': 'Kind of the new database: dev, test or both',
             'options': [{'value': 'dev', 'label': 'a development database cc_dev_<suffix>'},
                         {'value': 'test', 'label': 'a test database cc_test_<suffix>'},
                         {'value': 'both', 'label': 'both: cc_dev_<suffix> and cc_test_<suffix>'}],
             'recommended': None, 'flag': '--answer kind=<dev|test|both>', 'answer': None, 'origin': None},
            {'id': 'suffix', 'text': 'Name of the new database after cc_dev_ or cc_test_ (letters, digits and '
                                     'underscores)',
             'options': [], 'recommended': None, 'flag': '--answer suffix=<name>', 'answer': None, 'origin': None}])
        # The prefixes are shown, as a workspace setting: not a question of the plan.
        self.assertEqual(document['inferred']['dev_prefix']['value'], 'cc_dev_')
        self.assertEqual(document['inferred']['test_prefix']['value'], 'cc_test_')
        self.assertIn('workspace setting', document['inferred']['dev_prefix']['origin'])
        self.assertIn('not per database', document['inferred']['dev_prefix']['origin'])
        self.assertEqual(document['lines'][-1], 'nothing changed: answer the open questions above '
                         '(docs/dev-database.md#the-plan-of-a-new-database), then run the plan again')
        self.unchanged()

    def test_both_gives_the_dry_run_and_the_confirm_command_of_each_database(self):
        document = self.plan('--answer', 'kind=both', '--answer', 'suffix=shop')
        self.assertEqual((document['complete'], document['open']), (True, []))
        dev = self.confirm('create-database', 'cc_dev_shop', '--confirm', 'cc_dev_shop')
        test = self.confirm('create-database', 'cc_test_shop', '--confirm', 'cc_test_shop')
        self.assertEqual(document['databases'], [{'database': 'cc_dev_shop', 'kind': 'dev', 'command': dev},
                                                 {'database': 'cc_test_shop', 'kind': 'test', 'command': test}])
        self.assertEqual([question['origin'] for question in document['questions']], ['from --answer'] * 2)
        tail = document['lines'][document['lines'].index('database: cc_dev_shop'):]
        self.assertEqual(tail, ['database: cc_dev_shop', 'kind: dev', 'dry run: nothing changed',
                                'database: cc_test_shop', 'kind: test', 'dry run: nothing changed',
                                f'run: {dev}', f'run: {test}',
                                'nothing changed: creating a database is Tier B (oasis policy --json): the user '
                                'confirms each command above'])
        self.unchanged()

    def test_answers_file_and_the_text_plan(self):
        answers = self.root / 'answers.json'
        answers.write_text(json.dumps({'kind': 'test', 'suffix': 'shop'}))
        result = self.oasis('create-database', '--plan', '--answers', str(answers))
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        command = self.confirm('create-database', 'cc_test_shop', '--confirm', 'cc_test_shop')
        self.assertTrue(result.stdout.endswith(
            'database: cc_test_shop\nkind: test\ndry run: nothing changed\n'
            f'run: {command}\n'
            'nothing changed: creating a database is Tier B (oasis policy --json): the user confirms the command above\n'),
            result.stdout)
        self.assertIn(f'kind: test (from --answers)\n', result.stdout)
        self.unchanged()

    def test_a_slugged_checkout_names_its_namespace(self):
        lifecycle.write_config(self.root, lifecycle.WORKSPACE + "checkout_slug = 'wt_1'\n")
        document = self.plan('--answer', 'kind=dev', '--answer', 'suffix=shop')
        self.assertEqual([entry['database'] for entry in document['databases']], ['cc_dev_wt_1_shop'])
        self.assertEqual(document['inferred']['checkout_slug']['value'], 'wt_1')

    def test_refused_answers_change_nothing(self):
        for args, stderr in (
                (('--answer', 'kind=staging'), 'ERROR: Invalid answer staging for kind: answer dev, test or both.\n'),
                (('--answer', 'prefix=acme_dev_'),
                 'ERROR: --answer: unknown question prefix (this plan asks kind, suffix).\n'),
                (('--answer', 'kind=dev', '--answer', 'suffix=bad-name'),
                 'Database name must use only letters, numbers, and underscores.\n'),
                (('--answer', 'kind=dev', '--answer', 'suffix=x_r1a2b3c'),
                 'Database names ending in _r<6 hex> are reserved for disposable runs: cc_dev_x_r1a2b3c\n'),
                (('--answer', 'kind=dev', '--answer', 'suffix='),
                 'ERROR: Invalid answer for suffix: the name needs at least one character after the prefix.\n'),
                (('--answer', 'kind=dev', '--answer', 'kind=test'),
                 'ERROR: The question kind is answered twice: by --answer and by --answer.\n')):
            with self.subTest(args=args):
                result = self.oasis('create-database', '--plan', '--json', *args)
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertEqual(result.stderr, stderr if stderr.startswith('ERROR: ') else 'ERROR: ' + stderr)
                self.unchanged()

    def test_plan_usage_error(self):
        result = self.oasis('create-database', '--plan', 'cc_dev_x')
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.assertEqual(result.stderr, f'Usage: {(ROOT / "oasis").resolve()} create-database --plan [--json] '
                                        '[--answer <id>=<value>]... [--answers <file.json>]\n')
        self.unchanged()


if __name__ == '__main__':
    unittest.main()
