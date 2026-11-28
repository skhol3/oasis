"""gc --apply --trash is Tier B (v0.16.0 S1): it runs only with --confirm <project root>, else it
refuses before any query naming the exact command; gc --apply stays Tier A. Fixtures: tests/test_trash.py."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
from datetime import datetime, timedelta, timezone
import shlex
import unittest

import test_trash as trash

USAGE = (f'Usage: {trash.ENTRY} gc [--apply] [--all-checkouts] | '
         'gc [--apply] --trash [--older-than <days>] [--confirm <project root>]\n')


class GcTrashConfirmTests(trash.TrashFixture):
    def setUp(self):
        super().setUp()
        self.old, old = self.trashed('cc_dev_coffee', datetime.now(timezone.utc) - timedelta(days=10))
        self.orphan = 'cc_test_coffee_r1a2b3c'
        self.seed({self.old: old, self.orphan: {}})
        self.filestore(self.old)
        self.filestore(self.orphan)

    def command(self, *args):
        return shlex.join(['oasis', '--project', str(self.root), 'gc', *args])

    def assert_refused(self, args, stderr):
        before = self.snapshot()
        calls = len(self.calls())
        result = self.cli('gc', *args)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', stderr))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls()[calls:], [])  # refused before any query

    def test_apply_trash_without_confirm_names_the_listing_and_the_exact_command(self):
        root = str(self.root)
        for args, listing, command in (
                (('--apply', '--trash'), self.command('--trash'),
                 self.command('--apply', '--trash', '--confirm', root)),
                (('--trash', '--older-than', '3', '--apply'), self.command('--trash', '--older-than', '3'),
                 self.command('--apply', '--trash', '--older-than', '3', '--confirm', root))):
            with self.subTest(args=args):
                self.assert_refused(args, 'ERROR: gc --apply --trash drops the expired trash entries for good '
                                          f'(Tier B: it needs explicit confirmation); nothing changed. List them '
                                          f'with {listing}, then run: {command}\n')
        self.assert_refused(('--apply', '--trash', '--confirm', '/elsewhere'),
                            f'ERROR: --confirm /elsewhere does not name the project root {root}; nothing changed. '
                            f'Run: {self.command("--apply", "--trash", "--confirm", root)}\n')
        result = self.cli('gc', '--apply', '--trash', f'--confirm={root}')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'dropped {self.old}\ndropped=1\nfailed=0\n', ''))

    def test_confirm_needs_both_apply_and_trash(self):
        # gc --apply without --trash needs no confirmation: tests/test_trash.py GcTrashTests.
        for args in (('--apply', '--confirm', str(self.root)), ('--trash', '--confirm', str(self.root)),
                     ('--apply', '--trash', '--confirm'), ('--apply', '--trash', '--confirm='),
                     ('--apply', '--trash', '--confirm', 'a', '--confirm', 'a')):
            with self.subTest(args=args):
                self.assert_refused(args, USAGE)


if __name__ == '__main__':
    unittest.main()
