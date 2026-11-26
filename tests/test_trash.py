"""The database trash (v0.11.0 S2): drop-database moves to the trash, `trash`, `trash restore`
and `gc --trash`, through the public entry point.

The lifecycle fixture (fake python) with a stateful fake docker: a JSON file holds the
databases of the fake PostgreSQL service ({name: {size, comment, sessions}}) and the fake
answers the queries common.sh sends (existence, sessions, size, rename with comment, the trash
listing, dropdb). Every docker argv is logged as one JSON line, so a refusal can be checked to
send no mutating statement. Filestores live under the fixture's data_dir (odoo.conf).
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys
import unittest

import test_lifecycle as lifecycle
import test_shared_conf as shared

CLI = lifecycle.STAGE / 'oasis'
ENTRY = str(CLI)
STAMP = r'(\d{8}_\d{6})'
RESERVED = 'Database names ending in _trash_<YYYYMMDD>_<HHMMSS> are reserved for the trash: {}\n'
NOT_TRASH = 'Not a trash database of this checkout: {}\n'
FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, re, sys
argv = sys.argv[1:]
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps(argv) + '\n')
if 'up' in argv:
    raise SystemExit(0)
state_path = os.environ['FAKE_STATE']
with open(state_path) as stream:
    state = json.load(stream)
databases = state['databases']
script = argv[argv.index('-c') + 1] if '-c' in argv else ''
rest = argv[argv.index('-c') + 3:] if '-c' in argv else []
def save():
    with open(state_path, 'w') as stream:
        json.dump(state, stream, indent=1, sort_keys=True)
def quoted(sql):
    found = re.search(r"datname = '([^']*)'", sql)
    return found.group(1) if found else None
if 'dropdb' in script:
    name = rest[-1]
    if os.environ.get('FAKE_DROP_FAILS_FOR') == name:
        print('drop failed', file=sys.stderr)
        raise SystemExit(1)
    if os.environ.get('FAKE_DROP_BREAKS_CONF'):
        # The conf becomes unreadable after the drop: the filestore path cannot be resolved.
        with open(os.environ['FAKE_DROP_BREAKS_CONF'], 'w') as stream:
            stream.write('no section header\n')
    databases.pop(name, None)
    save()
    raise SystemExit(0)
if 'exec psql' not in script:
    raise SystemExit(0)
sql = rest[-1]
if sql.startswith('ALTER DATABASE'):
    found = re.fullmatch(r'ALTER DATABASE "(\w+)" RENAME TO "(\w+)"; COMMENT ON DATABASE "(\w+)" IS (NULL|\'[^\']*\')', sql)
    if not found or found.group(2) != found.group(3) or os.environ.get('FAKE_RENAME_FAILS'):
        if os.environ.get('FAKE_RENAME_BLOCKS'):
            # Something takes the path the filestore would move back to while the rename fails.
            os.makedirs(os.environ['FAKE_RENAME_BLOCKS'], exist_ok=True)
        print('ERROR:  rename failed', file=sys.stderr)
        raise SystemExit(1)
    old, new, comment = found.group(1), found.group(2), found.group(4)
    if old not in databases or new in databases or databases[old]['sessions']:
        print('ERROR:  cannot rename', file=sys.stderr)
        raise SystemExit(1)
    databases[new] = {**databases.pop(old), 'comment': None if comment == 'NULL' else comment[1:-1]}
    save()
elif 'SELECT 1 FROM pg_database' in sql:
    if quoted(sql) in databases:
        print(1)
elif 'pg_terminate_backend' in sql:
    if quoted(sql) in databases:
        databases[quoted(sql)]['sessions'] = 0
        save()
elif 'FROM pg_stat_activity' in sql:
    print(databases.get(quoted(sql), {}).get('sessions', 0))
elif sql.startswith('SELECT pg_database_size('):
    print(databases[re.search(r"'(\w+)'", sql).group(1)]['size'])
elif 'shobj_description' in sql and quoted(sql):
    print(databases.get(quoted(sql), {}).get('comment') or '')
elif 'SELECT datname' in sql:
    prefixes = [pattern.replace('\\_', '_') for pattern in re.findall(r"datname LIKE '([^%']*)%'", sql)]
    trash = 'shobj_description' in sql
    for name in sorted(databases):
        if not any(name.startswith(prefix) for prefix in prefixes):
            continue
        if trash:
            if re.search(r'_trash_[0-9]{8}_[0-9]{6}$', name):
                print(f"{name}\t{databases[name]['size']}\t{databases[name]['comment'] or ''}")
        else:
            print(name)
'''


def shortened(original, stamp):
    """The documented shortening: the first 34 bytes of the original, `_`, 6 hex of its sha256
    and `_trash_<stamp>` (63 bytes)."""
    digest = hashlib.sha256(original.encode()).hexdigest()[:6]
    return f'{original[:34]}_{digest}_trash_{stamp}'


def stamp_of(when):
    return when.astimezone(timezone.utc).strftime('%Y%m%d_%H%M%S')


class TrashFixture(unittest.TestCase):
    setUp_fixture = lifecycle.LifecycleTests.setUp
    unchanged = lifecycle.LifecycleTests.unchanged
    profile_extra = ''

    def setUp(self):
        self.setUp_fixture()
        (self.bindir / 'docker').write_text(FAKE_DOCKER)
        self.state = self.root.parent / 'state.json'
        self.data = self.root.parent / 'data'
        (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text(f'data_dir = {self.data}\n'))
        self.env['FAKE_STATE'] = str(self.state)
        self.write_profile()
        self.seed({})

    def write_profile(self, extra=''):
        lifecycle.write_config(self.root, lifecycle.WORKSPACE + self.profile_extra + extra)

    def seed(self, databases):
        self.state.write_text(json.dumps({'databases': {
            name: {'size': 8_000_000, 'comment': None, 'sessions': 0, **values}
            for name, values in databases.items()}}, indent=1, sort_keys=True))

    def databases(self):
        return json.loads(self.state.read_text())['databases']

    def filestore(self, name, content='attachment\n'):
        path = self.data / 'filestore' / name / 'ab'
        path.mkdir(parents=True)
        (path / 'file').write_text(content)
        return path.parent

    def filestores(self):
        root = self.data / 'filestore'
        return sorted(path.name for path in root.iterdir()) if root.is_dir() else []

    def cli(self, *args, root=None):
        return subprocess.run([sys.executable, '-B', str(CLI), '--project', str(root or self.root), *args],
                              cwd=root or self.root, env=self.env, capture_output=True, text=True, input='')

    def calls(self):
        if not self.commands.exists():
            return []
        return [json.loads(line) for line in self.commands.read_text().splitlines() if line.startswith('[')]

    def mutations(self):
        """Every docker call that changes a database: rename, comment, terminate or drop."""
        found = []
        for argv in self.calls():
            text = ' '.join(argv)
            if any(word in text for word in ('ALTER DATABASE', 'COMMENT ON', 'pg_terminate_backend', 'dropdb')):
                found.append(text)
        return found

    def snapshot(self):
        tree = sorted(str(path.relative_to(self.data)) for path in self.data.rglob('*')) if self.data.exists() else []
        return self.state.read_text(), tree

    def trashed(self, original, when, size=8_000_000, comment=True):
        """A synthetic trash entry dropped at `when` (an aware datetime)."""
        name = f'{original}_trash_{stamp_of(when)}'
        return name, {'size': size, 'comment': f'oasis-trash original={original}' if comment else None}


class DropToTrashTests(TrashFixture):
    def test_drop_prints_the_plan_then_moves_database_and_filestore_to_the_trash(self):
        self.seed({'cc_dev_coffee': {'size': 8_000_000}, 'cc_dev_other': {}})
        store = self.filestore('cc_dev_coffee')
        before = datetime.now(timezone.utc).replace(microsecond=0)
        result = self.cli('drop-database', 'cc_dev_coffee', '--confirm', 'cc_dev_coffee')
        after = datetime.now(timezone.utc)
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        found = re.fullmatch(
            'database=cc_dev_coffee\nsize=7.6MB\nsessions=0\n'
            f'filestore={re.escape(str(store))}\n'
            f'trash=(cc_dev_coffee_trash_{STAMP})\n'
            r'Database moved to trash: cc_dev_coffee -> \1\n'
            r'Restore it with: oasis trash restore \1\n', result.stdout)
        self.assertIsNotNone(found, result.stdout)
        trash, stamp = found.groups()
        dropped = datetime.strptime(stamp, '%Y%m%d_%H%M%S').replace(tzinfo=timezone.utc)
        self.assertTrue(before <= dropped <= after, (before, dropped, after))
        self.assertEqual(self.databases(), {
            'cc_dev_other': {'size': 8_000_000, 'comment': None, 'sessions': 0},
            trash: {'size': 8_000_000, 'comment': 'oasis-trash original=cc_dev_coffee', 'sessions': 0}})
        # The filestore moved with its content; the original path is gone.
        self.assertFalse(store.exists())
        self.assertEqual((self.data / 'filestore' / trash / 'ab/file').read_text(), 'attachment\n')
        self.assertEqual(self.filestores(), [trash])

    def test_open_sessions_refuse_without_terminate_and_touch_nothing(self):
        self.seed({'cc_dev_coffee': {'sessions': 2}})
        self.filestore('cc_dev_coffee')
        before = self.snapshot()
        result = self.cli('drop-database', 'cc_dev_coffee', '--confirm', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stderr), (3, (
            'Refusing to drop database with 2 active session(s): cc_dev_coffee\n'
            'Retry with --terminate only after confirming those sessions may be closed.\n')))
        self.assertRegex(result.stdout, r'\Adatabase=cc_dev_coffee\nsize=7\.6MB\nsessions=2\n'
                         r'filestore=\S+/filestore/cc_dev_coffee\ntrash=cc_dev_coffee_trash_\d{8}_\d{6}\n\Z')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.mutations(), [])
        # --terminate keeps its meaning: close the sessions, then move to the trash.
        result = self.cli('drop-database', 'cc_dev_coffee', '--terminate', '--confirm', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn('sessions=2\n', result.stdout)
        [trash] = self.databases()
        self.assertRegex(trash, r'^cc_dev_coffee_trash_\d{8}_\d{6}$')
        self.assertEqual(self.filestores(), [trash])
        self.assertIn('pg_terminate_backend', self.mutations()[0])

    def test_without_a_filestore_the_plan_says_none(self):
        self.seed({'cc_test_coffee': {'size': 512}})
        result = self.cli('drop-database', 'cc_test_coffee', '--confirm', 'cc_test_coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertRegex(result.stdout, r'\Adatabase=cc_test_coffee\nsize=512B\nsessions=0\nfilestore=none\n'
                                        r'trash=cc_test_coffee_trash_\d{8}_\d{6}\n')
        self.assertEqual(self.filestores(), [])
        # No data_dir at all: nothing is known to move either.
        (self.root / 'dev/odoo.conf').write_text(lifecycle.conf_text())
        self.seed({'cc_dev_coffee': {}})
        result = self.cli('drop-database', 'cc_dev_coffee', '--confirm', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn('\nfilestore=none\n', result.stdout)

    def test_a_missing_database_keeps_the_existing_message_and_exit(self):
        self.seed({'cc_dev_other': {}})
        before = self.snapshot()
        result = self.cli('drop-database', 'cc_dev_coffee', '--confirm', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, 'Database does not exist: cc_dev_coffee\n', ''))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.mutations(), [])

    def test_usage_and_unmanaged_names_are_refused_as_before(self):
        for args, stderr in (
                ((), f'Usage: {ENTRY} <cc_dev_*|cc_test_*> [--terminate] [--confirm <database>]\n'),
                (('cc_dev_coffee', '--force'), f'Usage: {ENTRY} <cc_dev_*|cc_test_*> [--terminate] [--confirm <database>]\n'),
                (('other_db',), 'Managed databases must use cc_dev_<name> or cc_test_<name>: other_db\n')):
            with self.subTest(args=args):
                result = self.cli('drop-database', *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', stderr))
                self.unchanged()

    def test_a_filestore_that_is_not_a_directory_or_a_taken_trash_path_touches_nothing(self):
        self.seed({'cc_dev_coffee': {}})
        (self.data / 'filestore').mkdir(parents=True)
        (self.data / 'filestore/cc_dev_coffee').symlink_to(self.root)
        before = self.snapshot()
        result = self.cli('drop-database', 'cc_dev_coffee', '--confirm', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.assertEqual(result.stderr, 'Filestore of cc_dev_coffee is not a directory; not moved: '
                                        f'{self.data}/filestore/cc_dev_coffee\n')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.mutations(), [])

    def test_a_failed_rename_moves_the_filestore_back(self):
        self.seed({'cc_dev_coffee': {}})
        store = self.filestore('cc_dev_coffee')
        self.env['FAKE_RENAME_FAILS'] = '1'
        before = self.snapshot()
        result = self.cli('drop-database', 'cc_dev_coffee', '--confirm', 'cc_dev_coffee')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, 'ERROR:  rename failed\n'
                                        'Cannot move cc_dev_coffee to the trash; nothing changed.\n')
        self.assertTrue((store / 'ab/file').is_file())
        self.assertEqual(self.snapshot(), before)

    def test_a_failed_rename_whose_filestore_cannot_move_back_says_where_it_is(self):
        self.seed({'cc_dev_coffee': {}})
        self.filestore('cc_dev_coffee')
        self.env['FAKE_RENAME_FAILS'] = '1'
        self.env['FAKE_RENAME_BLOCKS'] = str(self.data / 'filestore/cc_dev_coffee')
        result = self.cli('drop-database', 'cc_dev_coffee', '--confirm', 'cc_dev_coffee')
        self.assertEqual(result.returncode, 1)
        trash = re.search(r'^trash=(\S+)$', result.stdout, re.M).group(1)
        self.assertEqual(result.stderr, 'ERROR:  rename failed\n'
                                        f'Filestore path already exists: {self.data}/filestore/cc_dev_coffee\n'
                                        'Cannot move cc_dev_coffee to the trash; its filestore stays at the trash '
                                        f'path of {trash}.\n')
        self.assertEqual(self.databases(), {'cc_dev_coffee': {'size': 8_000_000, 'comment': None, 'sessions': 0}})
        self.assertEqual((self.data / 'filestore' / trash / 'ab/file').read_text(), 'attachment\n')

    def window(self, original, seconds=120):
        """Trash names of original for every second from just before now to `seconds` later, so
        the name a drop computes is one of them."""
        start = datetime.now(timezone.utc) - timedelta(seconds=2)
        return [f'{original}_trash_{stamp_of(start + timedelta(seconds=step))}' for step in range(seconds)]

    def test_a_taken_trash_name_is_refused_before_the_plan(self):
        taken = self.window('cc_dev_coffee')
        self.seed({'cc_dev_coffee': {}, **{name: {} for name in taken}})
        self.filestore('cc_dev_coffee')
        before = self.snapshot()
        result = self.cli('drop-database', 'cc_dev_coffee', '--confirm', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        found = re.fullmatch(r'Trash name already exists: (cc_dev_coffee_trash_\d{8}_\d{6})\n', result.stderr)
        self.assertIsNotNone(found, result.stderr)
        self.assertIn(found.group(1), taken)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.mutations(), [])

    def test_a_taken_trash_filestore_path_is_refused_before_the_plan(self):
        self.seed({'cc_dev_coffee': {}})
        self.filestore('cc_dev_coffee')
        taken = self.window('cc_dev_coffee')
        for name in taken:
            (self.data / 'filestore' / name).mkdir()
        before = self.snapshot()
        result = self.cli('drop-database', 'cc_dev_coffee', '--confirm', 'cc_dev_coffee')
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        found = re.fullmatch(f'Filestore path already exists: {re.escape(str(self.data))}/filestore/'
                             r'(cc_dev_coffee_trash_\d{8}_\d{6})\n', result.stderr)
        self.assertIsNotNone(found, result.stderr)
        self.assertIn(found.group(1), taken)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.mutations(), [])

    def test_a_namespace_too_long_to_shorten_is_refused(self):
        dev, test = 'c' * 30 + '_dev_', 'c' * 30 + '_test_'
        (self.root / 'oasis-workspace.toml').write_text(
            lifecycle.WORKSPACE.replace("'cc_dev_'", f"'{dev}'").replace("'cc_test_'", f"'{test}'"))
        self.assertEqual(len(dev), 35)
        original = dev + 'coffeeshop'
        self.seed({original: {}})
        self.filestore(original)
        before = self.snapshot()
        result = self.cli('drop-database', original, '--confirm', original)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            2, '', f'Database prefix and checkout slug leave no room for a trash name: {dev}\n'))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.mutations(), [])

    def test_a_long_name_is_shortened_with_a_hash_to_63_bytes_and_restores(self):
        original = 'cc_dev_' + 'a' * 50 + 'bcdefg'
        self.assertEqual(len(original), 63)
        self.seed({original: {}})
        self.filestore(original)
        result = self.cli('drop-database', original, '--confirm', original)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        stamp = re.search(r'^trash=\S+_trash_' + STAMP + '$', result.stdout, re.M).group(1)
        trash = shortened(original, stamp)
        self.assertEqual(len(trash.encode()), 63)
        self.assertTrue(trash.startswith('cc_dev_aaaa'))
        self.assertIn(f'\ntrash={trash}\n', result.stdout)
        self.assertEqual(list(self.databases()), [trash])
        self.assertEqual(self.filestores(), [trash])
        # The original name comes back from the trash entry, not from the shortened name.
        result = self.cli('trash', 'restore', trash)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'Database restored from trash: {trash} -> {original}\n', ''))
        self.assertEqual(self.databases(), {original: {'size': 8_000_000, 'comment': None, 'sessions': 0}})
        self.assertEqual(self.filestores(), [original])

    def test_a_name_that_just_fits_is_not_shortened(self):
        original = 'cc_test_' + 'b' * 33
        self.assertEqual(len(original) + len('_trash_20261123_142501'), 63)
        self.seed({original: {}})
        result = self.cli('drop-database', original, '--confirm', original)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertRegex(result.stdout, rf'\ntrash={original}_trash_\d{{8}}_\d{{6}}\n')

    def test_trash_names_are_reserved_for_every_normal_command(self):
        trash = 'cc_dev_coffee_trash_20261101_120000'
        test_trash = 'cc_test_coffee_trash_20261101_120000'
        for command, args, database in (
                ('create-database', (trash,), trash),
                ('install-module', ('coffee', trash), trash),
                ('update-module', ('coffee', trash), trash),
                ('odoo-shell', (trash,), trash),
                ('start', ('-d', trash), trash),
                ('start', (f'--database={trash}',), trash),
                ('init-dev-database', ('coffee', trash), trash),
                ('module-status', ('coffee', trash), trash),
                ('drop-database', (trash,), trash),
                ('test-module', ('coffee', test_trash), test_trash),
                ('verify-module', ('coffee', test_trash), test_trash)):
            with self.subTest(command=command, args=args):
                result = self.cli(command, *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, '', RESERVED.format(database)))
                self.unchanged()

    def test_similar_names_are_not_reserved(self):
        for database in ('cc_dev_coffee_trash_2026110_120000', 'cc_dev_coffee_trash_20261101_120000_x',
                         'cc_dev_coffee_trash'):
            with self.subTest(database=database):
                self.seed({})
                result = self.cli('create-database', database)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (0, f'Database ready: {database}\n', ''))


class SluggedTrashTests(TrashFixture):
    profile_extra = "checkout_slug = 'wt_1'\n"

    def test_the_trash_name_keeps_the_namespace_and_the_listing_is_this_checkouts(self):
        original = 'cc_test_wt_1_' + 'c' * 50
        self.seed({original: {}, 'cc_dev_wt_1_coffee': {}})
        result = self.cli('drop-database', original, '--confirm', original)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        stamp = re.search(r'^trash=\S+_trash_' + STAMP + '$', result.stdout, re.M).group(1)
        trash = shortened(original, stamp)
        self.assertTrue(trash.startswith('cc_test_wt_1_ccc'))
        self.assertEqual(len(trash), 63)
        # Another checkout's trash (the main checkout's namespace) is neither listed nor restorable.
        now = datetime.now(timezone.utc)
        main_name, main_entry = self.trashed('cc_dev_coffee', now - timedelta(days=1))
        state = json.loads(self.state.read_text())
        state['databases'][main_name] = {**main_entry, 'sessions': 0}
        self.state.write_text(json.dumps(state))
        result = self.cli('trash')
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 2, result.stdout)
        self.assertTrue(lines[0].startswith(f'trash {trash} original={original} dropped='), lines[0])
        self.assertEqual(lines[1], 'trashed=1')
        result = self.cli('trash', 'restore', main_name)
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.assertEqual(result.stderr, 'Databases of checkout wt_1 must use cc_dev_wt_1_<name> or '
                                        f'cc_test_wt_1_<name>: {main_name}\n')


class TrashListAndRestoreTests(TrashFixture):
    def setUp(self):
        super().setUp()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.old, old = self.trashed('cc_dev_coffee', self.now - timedelta(days=10, hours=3, minutes=30), size=8_000_000)
        self.new, new = self.trashed('cc_test_coffee', self.now - timedelta(hours=5, minutes=30), size=2048)
        self.anonymous, anonymous = self.trashed('cc_dev_tea', self.now - timedelta(days=20), comment=False)
        self.seed({self.old: old, self.new: new, self.anonymous: anonymous, 'cc_dev_live': {},
                   'cc_test_coffee_r1a2b3c': {}})
        self.filestore(self.old)

    def dropped(self, name):
        stamp = name.rsplit('_trash_', 1)[1]
        return datetime.strptime(stamp, '%Y%m%d_%H%M%S').strftime('%Y-%m-%dT%H:%M:%SZ')

    def test_trash_lists_original_drop_time_age_and_size(self):
        before = self.snapshot()
        result = self.cli('trash')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, (
            f'trash {self.old} original=cc_dev_coffee dropped={self.dropped(self.old)} age=10d03h size=7.6MB\n'
            f'trash {self.new} original=cc_test_coffee dropped={self.dropped(self.new)} age=0d05h size=2.0kB\n'
            'trashed=2\n'), ''))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.mutations(), [])

    def test_empty_trash(self):
        self.seed({'cc_dev_live': {}})
        result = self.cli('trash')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, 'trashed=0\n', ''))

    def test_restore_renames_back_the_database_and_its_filestore(self):
        result = self.cli('trash', 'restore', self.old)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'Database restored from trash: {self.old} -> cc_dev_coffee\n', ''))
        databases = self.databases()
        self.assertNotIn(self.old, databases)
        self.assertEqual(databases['cc_dev_coffee'], {'size': 8_000_000, 'comment': None, 'sessions': 0})
        self.assertEqual(self.filestores(), ['cc_dev_coffee'])
        self.assertEqual((self.data / 'filestore/cc_dev_coffee/ab/file').read_text(), 'attachment\n')
        # Without a filestore only the database is renamed.
        result = self.cli('trash', 'restore', self.new)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'Database restored from trash: {self.new} -> cc_test_coffee\n', ''))
        self.assertEqual(self.filestores(), ['cc_dev_coffee'])

    def test_restore_refusals_touch_nothing(self):
        state = json.loads(self.state.read_text())
        state['databases']['cc_test_coffee'] = {'size': 1, 'comment': None, 'sessions': 0}
        mismatch = 'cc_dev_milk_trash_20261101_120000'
        state['databases'][mismatch] = {'size': 1, 'comment': 'oasis-trash original=cc_dev_coffee', 'sessions': 0}
        busy, entry = self.trashed('cc_dev_busy', self.now - timedelta(days=1))
        state['databases'][busy] = {**entry, 'sessions': 1}
        self.state.write_text(json.dumps(state))
        self.filestore('cc_dev_coffee', 'newer\n')
        before = self.snapshot()
        usage = f'Usage: {ENTRY} trash [restore <trash name>]\n'
        for args, code, stderr in (
                (('restore', self.new), 2, f'Refusing to restore {self.new}: database cc_test_coffee already exists.\n'),
                (('restore', self.old), 2, f'Filestore path already exists: {self.data}/filestore/cc_dev_coffee\n'),
                (('restore', 'cc_dev_live'), 2, NOT_TRASH.format('cc_dev_live')),
                (('restore', self.anonymous), 2, NOT_TRASH.format(self.anonymous)),
                (('restore', mismatch), 2, NOT_TRASH.format(mismatch)),
                (('restore', 'cc_dev_gone_trash_20261101_120000'), 2,
                 'Database does not exist: cc_dev_gone_trash_20261101_120000\n'),
                (('restore', 'other_trash_20261101_120000'), 2,
                 'Managed databases must use cc_dev_<name> or cc_test_<name>: other_trash_20261101_120000\n'),
                (('restore', busy), 3, f'Refusing to restore database with 1 active session(s): {busy}\n'),
                (('restore',), 2, usage),
                (('restore', self.old, 'extra'), 2, usage),
                (('purge', self.old), 2, usage)):
            with self.subTest(args=args):
                result = self.cli('trash', *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (code, '', stderr))
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.mutations(), [])

    def test_a_failed_restore_rename_moves_the_filestore_back(self):
        self.env['FAKE_RENAME_FAILS'] = '1'
        before = self.snapshot()
        result = self.cli('trash', 'restore', self.old)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (1, '', f'ERROR:  rename failed\nCannot restore {self.old}; nothing changed.\n'))
        self.assertEqual((self.data / 'filestore' / self.old / 'ab/file').read_text(), 'attachment\n')
        self.assertEqual(self.snapshot(), before)

    def test_a_failed_restore_whose_filestore_cannot_move_back_says_where_it_is(self):
        self.env['FAKE_RENAME_FAILS'] = '1'
        self.env['FAKE_RENAME_BLOCKS'] = str(self.data / 'filestore' / self.old)
        databases = self.databases()
        result = self.cli('trash', 'restore', self.old)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', (
            'ERROR:  rename failed\n'
            f'Filestore path already exists: {self.data}/filestore/{self.old}\n'
            f'Cannot restore {self.old}; its filestore stays at the path of cc_dev_coffee.\n')))
        self.assertEqual(self.databases(), databases)
        self.assertEqual((self.data / 'filestore/cc_dev_coffee/ab/file').read_text(), 'attachment\n')

    def test_help(self):
        result = self.cli('trash', '--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(f'Usage: {ENTRY} trash [restore <trash name>]\n'))
        self.assertIn('_trash_<YYYYMMDD>_<HHMMSS>', result.stdout)
        self.unchanged()


class GcTrashTests(TrashFixture):
    def setUp(self):
        super().setUp()
        now = datetime.now(timezone.utc)
        self.old, old = self.trashed('cc_dev_coffee', now - timedelta(days=10))
        self.recent, recent = self.trashed('cc_test_coffee', now - timedelta(days=2))
        self.anonymous, anonymous = self.trashed('cc_dev_tea', now - timedelta(days=30), comment=False)
        self.orphan = 'cc_test_coffee_r1a2b3c'
        self.seed({self.old: old, self.recent: recent, self.anonymous: anonymous, self.orphan: {},
                   'cc_dev_live': {}})
        for name in (self.old, self.recent, self.orphan):
            self.filestore(name)

    def gc(self, *args):
        return self.cli('gc', *args)

    def test_trash_without_apply_lists_what_it_would_drop(self):
        before = self.snapshot()
        for args, stdout in (
                ((), f'expired {self.old}\nexpired=1\n'),
                (('--older-than', '1'), f'expired {self.old}\nexpired {self.recent}\nexpired=2\n'),
                (('--older-than', '0'), f'expired {self.old}\nexpired {self.recent}\nexpired=2\n'),
                (('--older-than', '30'), 'expired=0\n'),
                (('--older-than', '36500'), 'expired=0\n'),
                (('--older-than', '007'), f'expired {self.old}\nexpired=1\n')):
            with self.subTest(args=args):
                result = self.gc('--trash', *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, stdout, ''))
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.mutations(), [])

    def test_apply_trash_drops_expired_entries_and_their_filestores_only(self):
        result = self.gc('--apply', '--trash', '--confirm', str(self.root))
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'dropped {self.old}\ndropped=1\nfailed=0\n', ''))
        self.assertEqual(sorted(self.databases()), sorted([self.recent, self.anonymous, self.orphan, 'cc_dev_live']))
        self.assertEqual(self.filestores(), sorted([self.recent, self.orphan]))
        result = self.gc('--apply', '--trash', '--older-than', '0', '--confirm', str(self.root))
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'dropped {self.recent}\ndropped=1\nfailed=0\n', ''))
        self.assertEqual(self.filestores(), [self.orphan])

    def test_a_failed_purge_is_reported_and_keeps_the_filestore(self):
        self.env['FAKE_DROP_FAILS_FOR'] = self.old
        result = self.gc('--apply', '--trash', '--older-than', '1', '--confirm', str(self.root))
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (1, f'dropped {self.recent}\ndropped=1\nfailed=1\n', f'drop failed\nfailed {self.old}\n'))
        self.assertIn(self.old, self.databases())
        self.assertIn(self.old, self.filestores())
        self.assertNotIn(self.recent, self.filestores())

    def test_a_filestore_left_after_the_drop_is_reported_with_its_path(self):
        store = self.data / 'filestore' / self.old
        for path in sorted(store.rglob('*'), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        store.rmdir()
        store.write_text('not a directory\n')
        result = self.gc('--apply', '--trash', '--older-than', '1', '--confirm', str(self.root))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            1, f'dropped {self.recent}\ndropped=1\nfailed=1\n',
            f'Filestore of {self.old} is not a directory; not removed: {store}\n'
            f'Database {self.old} was dropped, but its filestore is left: {store}; remove it by hand.\n'
            f'failed {self.old}\n'))
        self.assertNotIn(self.old, self.databases())
        self.assertEqual(store.read_text(), 'not a directory\n')

    def test_a_filestore_whose_path_cannot_be_resolved_is_reported_with_the_literal_path(self):
        conf = self.root / 'dev/odoo.conf'
        self.env['FAKE_DROP_BREAKS_CONF'] = str(conf)
        result = self.gc('--apply', '--trash', '--confirm', str(self.root))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            1, 'dropped=0\nfailed=1\n',
            f'Cannot read data_dir from {conf}: invalid configuration file. Filestore of {self.old} not removed.\n'
            f'Database {self.old} was dropped, but its filestore is left: <data_dir>/filestore/{self.old}; '
            'remove it by hand.\n'
            f'failed {self.old}\n'))
        self.assertNotIn(self.old, self.databases())
        # The filestore is never guessed at, so it stays where it was.
        self.assertIn(self.old, self.filestores())

    def test_plain_gc_and_gc_apply_are_unchanged_by_the_trash(self):
        before = self.snapshot()
        result = self.gc()
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'orphan {self.orphan}\norphans=1\n', ''))
        self.assertEqual(self.snapshot(), before)
        result = self.gc('--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'dropped {self.orphan}\ndropped=1\nfailed=0\n', ''))
        self.assertEqual(sorted(self.databases()), sorted([self.old, self.recent, self.anonymous, 'cc_dev_live']))
        self.assertEqual(self.filestores(), sorted([self.old, self.recent]))

    def test_usage(self):
        usage = f'Usage: {ENTRY} gc [--apply] [--all-checkouts] | gc [--apply] --trash [--older-than <days>] [--confirm <project root>]\n'
        for args in (('--older-than', '3'), ('--trash', '--older-than'), ('--trash', '--older-than', 'x'),
                     ('--trash', '--older-than', '-1'), ('--trash', '--older-than', '36501'),
                     ('--trash', '--older-than', '99999999999999999999'),
                     ('--apply', '--trash', '--older-than', '1000000000'), ('--trash', '--all-checkouts'),
                     ('--force',)):
            with self.subTest(args=args):
                before = self.snapshot()
                calls = len(self.calls())
                result = self.gc(*args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', usage))
                self.assertEqual(self.snapshot(), before)
                # Refused before any query.
                self.assertEqual(self.calls()[calls:], [])
        result = self.gc('--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(usage))
        self.assertIn('--trash', result.stdout)


class MainCheckoutTrashTests(TrashFixture):
    """The main checkout's trash excludes the namespaces of its existing linked worktrees."""

    def setUp(self):
        super().setUp()
        shared.shared_layout(self)
        (self.conf).write_text(self.conf.read_text() + f'data_dir = {self.data}\n')
        now = datetime.now(timezone.utc)
        self.main_trash, main_entry = self.trashed('cc_dev_coffee', now - timedelta(days=9))
        self.linked_trash, linked_entry = self.trashed('cc_dev_wt_coffee', now - timedelta(days=9))
        self.seed({self.main_trash: main_entry, self.linked_trash: linked_entry})

    def test_each_checkout_sees_and_purges_only_its_own_trash(self):
        for root, own in ((self.main, self.main_trash), (self.linked, self.linked_trash)):
            with self.subTest(root=root.name):
                result = self.cli('gc', '--trash', root=root)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (0, f'expired {own}\nexpired=1\n', ''))
                result = self.cli('trash', root=root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual([line.split()[1] for line in result.stdout.splitlines()[:-1]], [own])
        result = self.cli('trash', 'restore', self.linked_trash, root=self.main)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', NOT_TRASH.format(self.linked_trash)))
        self.assertEqual(sorted(self.databases()), sorted([self.main_trash, self.linked_trash]))


if __name__ == '__main__':
    unittest.main()
