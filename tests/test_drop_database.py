"""drop-database is Tier B (v0.16.0 S1): it runs only with --confirm <database>, else it prints the
plan and refuses naming the exact command; nothing changes. Fixtures: tests/test_trash.py."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import re
import unittest

import test_trash as trash

PLAN = (r'\Adatabase=cc_dev_coffee\nsize=7\.6MB\nsessions={}\nfilestore=\S+/filestore/cc_dev_coffee\n'
        r'trash=cc_dev_coffee_trash_\d{{8}}_\d{{6}}\n\Z')


class DropDatabaseConfirmTests(trash.TrashFixture):
    def assert_refused(self, args, stderr, sessions=0):
        before = self.snapshot()
        result = self.cli('drop-database', *args)
        self.assertEqual((result.returncode, result.stderr), (2, stderr))
        self.assertRegex(result.stdout, PLAN.format(sessions))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.mutations(), [])

    def test_without_confirm_it_prints_the_plan_and_names_the_exact_command(self):
        self.seed({'cc_dev_coffee': {}, 'cc_dev_other': {}})
        self.filestore('cc_dev_coffee')
        command = f"oasis --project '{self.root}' drop-database cc_dev_coffee --confirm cc_dev_coffee"
        if re.fullmatch(r'[\w/.-]+', str(self.root)):
            command = command.replace(f"'{self.root}'", str(self.root))
        self.assert_refused(('cc_dev_coffee',),
                            'ERROR: drop-database moves cc_dev_coffee and its filestore to the trash (Tier B: it '
                            f'needs explicit confirmation); nothing changed. Run: {command}\n')
        self.assert_refused(('cc_dev_coffee', '--confirm', 'cc_dev_other'),
                            'ERROR: --confirm cc_dev_other does not name the database cc_dev_coffee; nothing '
                            f'changed. Run: {command}\n')
        result = self.cli('drop-database', 'cc_dev_coffee', '--confirm=cc_dev_coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertIn('Database moved to trash: cc_dev_coffee -> cc_dev_coffee_trash_', result.stdout)
        self.assertNotIn('cc_dev_coffee', self.databases())

    def test_open_sessions_are_not_closed_before_the_confirmation(self):
        self.seed({'cc_dev_coffee': {'sessions': 2}})
        self.filestore('cc_dev_coffee')
        root = self.root if re.fullmatch(r'[\w/.-]+', str(self.root)) else f"'{self.root}'"
        self.assert_refused(('cc_dev_coffee', '--terminate'),
                            'ERROR: drop-database moves cc_dev_coffee and its filestore to the trash (Tier B: it '
                            f'needs explicit confirmation); nothing changed. Run: oasis --project {root} '
                            'drop-database cc_dev_coffee --terminate --confirm cc_dev_coffee\n', sessions=2)

    def test_usage_names_the_confirmation(self):
        usage = 'Usage: {} <cc_dev_*|cc_test_*> [--terminate] [--confirm <database>]\n'.format(trash.ENTRY)
        for args in (('cc_dev_coffee', '--confirm'), ('cc_dev_coffee', '--confirm='),
                     ('cc_dev_coffee', '--confirm', 'a', '--confirm', 'a'), ('cc_dev_a', 'cc_dev_b')):
            with self.subTest(args=args):
                result = self.cli('drop-database', *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', usage))


if __name__ == '__main__':
    unittest.main()
