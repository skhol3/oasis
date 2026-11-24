"""list-databases lists only the current checkout's databases (v0.12.0 S2), through the public
entry point.

The trash fixture's stateful fake docker answers the prefix query common.sh sends (it keeps the
names that start with the query's LIKE prefixes, in name order) and logs every docker argv as
one JSON line. The main checkout is a real git repository with real linked worktrees
(test_shared_conf.shared_layout), so the other checkouts' slugs come from `git worktree list`
as gc and the trash read them.
"""
import subprocess
import unittest

import test_shared_conf as shared
import test_trash as trash

STAMP = '20261101_120000'
SEEDED = [
    'cc_dev_coffee', 'cc_test_coffee', f'cc_dev_coffee_trash_{STAMP}',
    # The worktree `a project-wt` (slug wt): its databases, a disposable run and its trash.
    'cc_dev_wt_coffee', 'cc_test_wt_coffee_r0a1b2c', f'cc_dev_wt_coffee_trash_{STAMP}',
    # The worktree `a project-wt-1` (slug wt_1) shares the `cc_dev_wt_` start of wt's namespace.
    'cc_dev_wt_1_coffee', 'cc_test_wt_1_coffee',
    # Main's: no existing checkout has the slug wtx, and `_` is not a wildcard (wtX1 is not wt_1).
    'cc_dev_wtx_coffee', 'cc_dev_wtX1_coffee',
    # Outside both prefixes, a bare prefix and an unescaped LIKE match of cc_dev_.
    'postgres', 'other_dev_coffee', 'cc_dev_', 'ccXdevXcoffee',
]
MAIN = ['cc_dev_coffee', f'cc_dev_coffee_trash_{STAMP}', 'cc_dev_wtX1_coffee', 'cc_dev_wtx_coffee',
        'cc_test_coffee']
WT = ['cc_dev_wt_coffee', f'cc_dev_wt_coffee_trash_{STAMP}', 'cc_test_wt_coffee_r0a1b2c']
WT_1 = ['cc_dev_wt_1_coffee', 'cc_test_wt_1_coffee']
QUERY = ("SELECT datname FROM pg_database WHERE datname LIKE 'cc\\_dev\\_%' ESCAPE '\\' "
         "OR datname LIKE 'cc\\_test\\_%' ESCAPE '\\' ORDER BY datname")


class NamespaceFixture(trash.TrashFixture):
    def listed(self, root):
        calls = len(self.calls())
        result = self.cli('list-databases', root=root)
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        # One prefix query with escaped LIKE wildcards; nothing else reaches the service.
        queries = [argv for argv in self.calls()[calls:] if 'up' not in argv]
        self.assertEqual([argv[-1] for argv in queries], [QUERY])
        self.assertEqual(self.mutations(), [])
        return result.stdout.splitlines()


class WorktreeNamespaceTests(NamespaceFixture):
    def setUp(self):
        super().setUp()
        shared.shared_layout(self)
        self.linked_1 = self.main.parent / 'a project-wt-1'
        subprocess.run([*shared.GIT, '-C', str(self.main), 'worktree', 'add', '-q', '-b', 'wt1',
                        str(self.linked_1)], check=True, capture_output=True, env=self.env)
        self.seed({name: {} for name in SEEDED})

    def test_each_checkout_lists_only_its_own_databases(self):
        for root, expected in ((self.main, MAIN), (self.linked, WT), (self.linked_1, WT_1)):
            with self.subTest(root=root.name):
                self.assertEqual(self.listed(root), expected)
        self.assertEqual(sorted(self.databases()), sorted(SEEDED))

    def test_the_main_checkout_takes_the_databases_of_a_removed_worktree(self):
        subprocess.run([*shared.GIT, '-C', str(self.main), 'worktree', 'remove', '--force', str(self.linked)],
                       check=True, capture_output=True, env=self.env)
        self.assertEqual(self.listed(self.main), sorted(MAIN + WT))
        self.assertEqual(self.listed(self.linked_1), WT_1)

    def test_a_checkout_file_slug_names_the_namespace(self):
        (self.linked / 'oasis-checkout.toml').write_text("[tooling]\ncheckout_slug = 'wtx'\n")
        self.assertEqual(self.listed(self.linked), ['cc_dev_wtx_coffee'])
        # The main checkout now leaves wtx to that worktree, and takes back wt's databases.
        self.assertEqual(self.listed(self.main), sorted(set(MAIN + WT) - {'cc_dev_wtx_coffee'}))

    def assert_main_listing_refused(self, stderr):
        calls = len(self.calls())
        result = self.cli('list-databases', root=self.main)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', stderr))
        self.assertEqual(self.mutations(), [])
        self.assertEqual([argv[-1] for argv in self.calls()[calls:] if 'up' not in argv], [QUERY])

    def test_an_unreadable_worktree_slug_stops_the_main_listing_and_names_the_fix(self):
        # Fails closed: without that worktree's slug, its databases could be listed as main's.
        checkout_file = self.linked / 'oasis-checkout.toml'
        checkout_file.write_text('[tooling\n')
        self.assert_main_listing_refused(
            f'ERROR: Cannot read the checkout slug of {self.linked}: Invalid TOML in {checkout_file}. '
            f'Fix {checkout_file}, then run the command again.\n')
        # A worktree that still has a legacy profile: its slug is not read, so the same stop.
        checkout_file.unlink()
        profile = self.linked / '.odoo19-agent.toml'
        profile.write_text("[tooling]\ncheckout_slug = 'wtx'\n")
        self.assert_main_listing_refused(
            f'ERROR: Cannot read the checkout slug of {self.linked}: {profile} is the old profile format, '
            'no longer read: run oasis migrate --plan to see its conversion to oasis-workspace.toml, then '
            'oasis migrate --apply.\n')
        profile.unlink()
        self.assertEqual(self.listed(self.main), MAIN)


class OutsideGitTests(NamespaceFixture):
    """A project outside git keeps today's listing: every name under both prefixes."""

    def test_every_prefixed_database_is_listed_one_per_line(self):
        self.seed({name: {} for name in SEEDED})
        self.assertEqual(self.listed(self.root), sorted(set(MAIN + WT + WT_1)))

    def test_no_database_prints_nothing(self):
        self.assertEqual(self.listed(self.root), [])

    def test_a_failing_query_keeps_its_exit_status_and_lists_nothing(self):
        (self.bindir / 'docker').write_text('#!/bin/sh\ncase "$*" in *"SELECT datname"*) '
                                            'echo "connection lost" >&2; exit 3 ;; esac\nexit 0\n')
        result = self.cli('list-databases')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (3, '', 'connection lost\n'))

    def test_arguments_are_refused_before_any_query(self):
        result = self.cli('list-databases', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.assertTrue(result.stderr.startswith('Usage: '), result.stderr)
        self.assertEqual(self.calls(), [])


class SluggedCheckoutTests(NamespaceFixture):
    """A checkout file slug outside git (git failed in a linked worktree): only <prefix><slug>_."""
    profile_extra = "checkout_slug = 'wt_1'\n"

    def test_only_the_slug_namespace_is_listed(self):
        self.seed({name: {} for name in SEEDED})
        self.assertEqual(self.listed(self.root), WT_1)


if __name__ == '__main__':
    unittest.main()
