"""Disposable test databases per run and `odoo19 gc` (S5), through the public interfaces.

The lifecycle fixture (fake docker/python recording every argv) with a private
XDG_RUNTIME_DIR per test. The fake docker below also records `createdb` and
`dropdb --if-exists` of single databases and answers the managed-database listing from
`<FAKE_LOG>.databases`, so creation, drops and gc can be checked from the outside.
"""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
from pathlib import Path
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import unittest

import test_lifecycle as lifecycle
import test_shared_conf as shared

# Workspace files must not be group-writable (trust rule); keep test results independent of the caller's umask.
os.umask(0o022)

STATE = lifecycle.STAGE / 'tools' / 'runtime_state.py'
CLI = lifecycle.STAGE / 'odoo19'
RUN = r'_r[0-9a-f]{6}'
RESERVED = 'Database names ending in _r<6 hex> are reserved for disposable runs: {}\n'
# Inserted first in the fake docker's case: single-database create/drop and the listing.
DOCKER_CASES = '''case "$*" in
  *"exec createdb"*)
    if [ "${FAKE_CREATE_FAILS:-0}" = 1 ]; then echo "create failed" >&2; exit 1; fi
    if [ "${FAKE_CREATE_ALREADY_EXISTS:-0}" = 1 ]; then
      printf "%s\\n" "$last" >> "$FAKE_LOG.databases"
      printf 'createdb: error: database creation failed: ERROR:  database "%s" already exists\\n' "$last" >&2; exit 1
    fi
    printf "%s\\n" "$last" >> "$FAKE_LOG.databases"
    if [ "${FAKE_CREATE_THEN_FAILS:-0}" = 1 ]; then echo "create failed late" >&2; exit 1; fi ;;
  *"exec dropdb --if-exists"*)
    if [ "${FAKE_DROP_FAILS:-0}" = 1 ] || [ "${FAKE_DROP_FAILS_FOR:-}" = "$last" ]; then
      echo "drop failed" >&2; exit 1
    fi
    if [ -f "$FAKE_LOG.databases" ]; then
      grep -vx "$last" "$FAKE_LOG.databases" > "$FAKE_LOG.kept" || true
      mv "$FAKE_LOG.kept" "$FAKE_LOG.databases"
    fi ;;
  *"SELECT datname FROM pg_database"*) cat "$FAKE_LOG.databases" 2>/dev/null || true ;;
'''
# Appended to the fake python: during an Odoo call, record the run locks and create the
# filestore Odoo would create; FAKE_WAIT_SIGNAL keeps the Odoo process alive until signalled
# (or for FAKE_WAIT_SECONDS, default 30).
PYTHON_PROBE = '''
database=; previous=
for argument; do [ "$previous" = -d ] && database=$argument; previous=$argument; done
case " $* " in
  *" --test-tags "*)
    if [ -n "${FAKE_LOCKS:-}" ]; then
      for lock in "$XDG_RUNTIME_DIR"/oasis-*/*/runs/*.json; do
        [ -f "$lock" ] && { cat "$lock"; echo; } >> "$FAKE_LOCKS"
      done
    fi ;;
esac
if [ -n "${FAKE_FILESTORE_LINK:-}" ] && [ -n "$database" ]; then
  mkdir -p "$FAKE_DATA/filestore"
  ln -s "$FAKE_FILESTORE_LINK" "$FAKE_DATA/filestore/$database"
elif [ -n "${FAKE_DATA:-}" ] && [ -n "$database" ]; then
  mkdir -p "$FAKE_DATA/filestore/$database/ab"
  printf 'attachment\\n' > "$FAKE_DATA/filestore/$database/ab/file"
fi
if [ -n "${FAKE_WAIT_SIGNAL:-}" ]; then
  printf 'waiting\\n' >> "$FAKE_WAIT_SIGNAL"
  exec sleep "${FAKE_WAIT_SECONDS:-30}"
fi
case " $* " in *" --test-tags "*) exit "${FAKE_TEST_EXIT:-0}" ;; esac
'''


def entries(text):
    """Fake command log entries: a docker argv may span lines (its sh -c script)."""
    found = []
    for line in text.splitlines():
        if line.startswith(('docker ', 'odoo ')):
            found.append(line)
        elif found:
            found[-1] += '\n' + line
    return found


def events(text):
    """(kind, database) for every database-relevant command, in order."""
    result = []
    for entry in entries(text):
        last = entry.split()[-1] if entry.split() else ''
        quoted = re.search(r"datname = '([^']*)'", entry)
        if entry.startswith('odoo '):
            database = re.search(r' -d (\S+)', entry).group(1)
            kind = 'tests' if ' --test-tags ' in entry else 'install' if ' -i ' in entry else 'update'
            result.append((kind, database))
        elif 'exec createdb' in entry:
            result.append(('create', last))
        elif 'exec dropdb --if-exists' in entry:
            result.append(('drop', last))
        elif 'dropdb --if-exists' in entry and 'createdb' in entry:
            result.append(('reset', last))
        elif 'pg_terminate_backend' in entry:
            result.append(('terminate', quoted.group(1)))
        elif 'SELECT 1 FROM pg_database' in entry:
            result.append(('exists', quoted.group(1)))
    return result


def shortened(namespace, module):
    """The documented 56-byte shortening: first N chars + '_' + 4 hex of sha256(module)."""
    room = 56 - len(namespace) - len('_r123456') - 5
    return namespace + module[:room] + '_' + hashlib.sha256(module.encode()).hexdigest()[:4]


# What a refused disposable name tells the user to do (common.sh require_free_disposable_database).
REMEDY = 'Run the command again for a new name; oasis gc --apply drops what interrupted runs left.'


class DisposableFixture(unittest.TestCase):
    setUp_fixture = lifecycle.LifecycleTests.setUp
    invoke = lifecycle.LifecycleTests.invoke
    unchanged = lifecycle.LifecycleTests.unchanged

    def setUp(self):
        self.setUp_fixture()
        docker = self.bindir / 'docker'
        docker.write_text(docker.read_text().replace('case "$*" in\n', DOCKER_CASES, 1))
        self.python.write_text(self.python.read_text() + PYTHON_PROBE)
        self.xdg = Path(self.env['XDG_RUNTIME_DIR'])
        self.data = self.root.parent / 'data'
        self.locks = self.root.parent / 'locks'
        self.env.update(FAKE_DATA=str(self.data), FAKE_LOCKS=str(self.locks))

    def write_conf(self, extra=''):
        (self.root / 'dev/odoo.conf').write_text(f'[options]\ndata_dir = {self.data}\n{extra}')

    def write_profile(self, extra):
        lifecycle.write_config(self.root, lifecycle.WORKSPACE + extra)

    def add_module(self, name):
        (self.root / name).mkdir()
        (self.root / name / '__manifest__.py').touch()

    def log(self):
        return self.commands.read_text() if self.commands.exists() else ''

    def events(self):
        return events(self.log())

    def run_locks(self):
        return sorted(path.name for path in self.xdg.glob(f'oasis-{os.getuid()}/*/runs/*.json'))

    def seen_locks(self):
        if not self.locks.exists():
            return []
        return [json.loads(chunk) for chunk in self.locks.read_text().split('\n') if chunk.strip()]

    def run_database(self):
        [database] = [database for kind, database in self.events() if kind == 'tests']
        return database

    def popen(self, command, *args, **kwargs):
        path = self.root / 'dev/scripts' / command
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((lifecycle.STAGE / 'project-wrappers' / command).read_bytes())
        process = subprocess.Popen(['bash', str(path), *args], cwd=self.root, env=self.env, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        return process

    def spawn_sleeper(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        return process

    def state(self, *args):
        return subprocess.run([sys.executable, '-B', str(STATE), *args], capture_output=True, text=True,
                              env=self.env)

    def lock_path(self, database, root=None):
        digest = hashlib.sha256(str(Path(root or self.root).resolve()).encode()).hexdigest()[:16]
        return self.xdg / f'oasis-{os.getuid()}' / digest / 'runs' / f'{database}.json'

    def wait_for_odoo(self, process, waiting):
        deadline = time.monotonic() + 20
        while not waiting.exists():
            self.assertIsNone(process.poll(), process.stderr.read() if process.poll() is not None else '')
            self.assertLess(time.monotonic(), deadline, 'test process never started')
            time.sleep(0.05)


class DisposableTestModuleTests(DisposableFixture):
    def assert_disposable_cycle(self, database, namespace='cc_test_', module='coffee'):
        self.assertRegex(database, '^' + re.escape(namespace + module) + RUN + '$')
        self.assertEqual(self.events(), [('exists', database), ('create', database), ('tests', database),
                                          ('terminate', database), ('drop', database)])
        self.assertEqual(self.run_locks(), [])

    def test_default_run_creates_tests_and_drops_its_own_database(self):
        self.write_conf()
        process = self.popen('test-module', 'coffee')
        stdout, stderr = process.communicate(timeout=60)
        self.assertEqual((process.returncode, stdout, stderr), (0, '', ''))
        database = self.run_database()
        self.assert_disposable_cycle(database)
        # The run lock existed while Odoo ran: this run's pid, its database and checkout.
        [lock] = self.seen_locks()
        self.assertEqual(set(lock), {'pid', 'started_at', 'database', 'project_root', 'argv'})
        self.assertEqual((lock['pid'], lock['database'], lock['project_root']),
                         (process.pid, database, str(self.root.resolve())))
        self.assertTrue(any(word.endswith('test_temp.py') for word in lock['argv']), lock['argv'])
        # The filestore Odoo created for the run is gone with the database.
        self.assertFalse((self.data / 'filestore' / database).exists())
        self.assertTrue((self.data / 'filestore').is_dir())

    def test_each_run_gets_a_new_name(self):
        names = set()
        for _ in range(2):
            self.commands.unlink(missing_ok=True)
            result = self.invoke('test-module', 'coffee')
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
            names.add(self.run_database())
        self.assertEqual(len(names), 2)

    def test_failing_tests_still_drop_the_database(self):
        self.env['FAKE_TEST_EXIT'] = '1'
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', ''))
        self.assert_disposable_cycle(self.run_database())

    def test_sigterm_to_test_module_drops_the_database(self):
        for signum, status, group in ((signal.SIGTERM, 143, False), (signal.SIGINT, 130, True)):
            with self.subTest(signal=signum.name, group=group):
                self.commands.unlink(missing_ok=True)
                waiting = self.root.parent / f'waiting-{signum}'
                self.env['FAKE_WAIT_SIGNAL'] = str(waiting)
                process = self.popen('test-module', 'coffee', start_new_session=True)
                deadline = time.monotonic() + 20
                while not waiting.exists():
                    self.assertIsNone(process.poll(), process.stderr.read() if process.poll() is not None else '')
                    self.assertLess(time.monotonic(), deadline, 'test process never started')
                    time.sleep(0.05)
                self.assertEqual(len(self.run_locks()), 1)
                if group:
                    os.killpg(process.pid, signum)
                else:
                    os.kill(process.pid, signum)
                stdout, stderr = process.communicate(timeout=30)
                self.assertEqual((process.returncode, stdout, stderr), (status, '', ''))
                self.assert_disposable_cycle(self.run_database())

    def test_filestore_of_the_run_only_is_removed(self):
        self.write_conf()
        other = self.data / 'filestore' / 'cc_test_coffee'
        other.mkdir(parents=True)
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertFalse((self.data / 'filestore' / self.run_database()).exists())
        self.assertEqual(sorted(path.name for path in (self.data / 'filestore').iterdir()), ['cc_test_coffee'])

    def test_a_symlinked_filestore_is_never_followed(self):
        self.write_conf()
        outside = self.root.parent / 'outside'
        outside.mkdir()
        (outside / 'keep').write_text('kept\n')
        self.env['FAKE_FILESTORE_LINK'] = str(outside)
        result = self.invoke('test-module', 'coffee')
        database = self.run_database()
        link = self.data / 'filestore' / database
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', (
            f'Filestore of {database} is not a directory; not removed: {link}\n')))
        self.assertTrue(link.is_symlink())
        self.assertEqual((outside / 'keep').read_text(), 'kept\n')
        self.assert_disposable_cycle(database)

    def test_without_data_dir_the_filestore_step_is_skipped(self):
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        database = self.run_database()
        self.assert_disposable_cycle(database)
        self.assertTrue((self.data / 'filestore' / database).is_dir())

    def test_compact_run_reports_the_disposable_database(self):
        for exit_code in (0, 7):
            with self.subTest(exit=exit_code):
                self.commands.unlink(missing_ok=True)
                self.env['FAKE_TEST_EXIT'] = str(exit_code)
                result = self.invoke('test-module', '--compact', 'coffee')
                self.assertEqual((result.returncode, result.stderr), (exit_code, ''))
                database = self.run_database()
                lines = result.stdout.splitlines()
                self.assertEqual(lines[:2], [f'phase=tests database={database} exit={exit_code}',
                                             'database_lifecycle=disposable dropped=yes'])
                self.assertEqual([line.split('=', 1)[0] for line in lines[2:]], ['stdout_log', 'stderr_log'])
                self.assert_disposable_cycle(database)

    def test_a_failed_drop_is_reported_and_keeps_the_lock_for_gc(self):
        self.env['FAKE_DROP_FAILS'] = '1'
        result = self.invoke('test-module', 'coffee')
        database = self.run_database()
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', (
            'drop failed\n'
            f'Cannot drop disposable test database {database}; run oasis gc --apply later.\n')))
        self.assertEqual(self.run_locks(), [f'{database}.json'])
        self.commands.unlink()
        result = self.invoke('test-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (1, ''))
        self.assertEqual(result.stdout.splitlines()[1], 'database_lifecycle=disposable dropped=no')

    def test_an_existing_database_of_the_same_name_is_never_touched(self):
        self.env['FAKE_EXISTS'] = '1'
        result = self.invoke('test-module', 'coffee')
        [(kind, database)] = [event for event in self.events()]
        self.assertEqual(kind, 'exists')
        self.assertRegex(database, '^cc_test_coffee' + RUN + '$')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'Disposable test database already exists: {database}; it was left as it is.\n'
                          f'{REMEDY}\n'))
        self.assertEqual(self.run_locks(), [])

    def test_a_failed_create_never_drops_the_name_and_removes_only_its_lock(self):
        # createdb fails without creating the database: the run checks the name again, finds
        # nothing of its own and drops nothing.
        self.env['FAKE_CREATE_FAILS'] = '1'
        result = self.invoke('test-module', 'coffee')
        database = self.events()[0][1]
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', (
            f'create failed\nCannot create disposable test database {database}; it was not dropped.\n')))
        self.assertEqual(self.events(), [('exists', database), ('create', database), ('exists', database)])
        self.assertEqual(self.run_locks(), [])
        self.commands.unlink()
        result = self.invoke('test-module', '--compact', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (1, ''))
        self.assertEqual(result.stdout.splitlines()[1], 'database_lifecycle=disposable dropped=yes')
        self.assertEqual([kind for kind, _ in self.events()], ['exists', 'create', 'exists'])

    def databases(self):
        path = Path(str(self.commands) + '.databases')
        return path.read_text().split() if path.exists() else []

    def test_a_create_that_finds_the_name_taken_never_drops_it(self):
        # Something without a run lock created the name between the free check and createdb:
        # createdb reports "already exists", so the database is not this run's and stays.
        self.env['FAKE_CREATE_ALREADY_EXISTS'] = '1'
        result = self.invoke('test-module', 'coffee')
        database = self.events()[0][1]
        self.assertEqual(self.events(), [('exists', database), ('create', database)])
        self.assertEqual((result.returncode, result.stdout), (1, ''))
        self.assertEqual(result.stderr, (
            f'createdb: error: database creation failed: ERROR:  database "{database}" already exists\n'
            f'Cannot create disposable test database {database}; it was not dropped.\n'))
        self.assertEqual(self.databases(), [database])
        self.assertEqual(self.run_locks(), [])

    def test_a_create_that_fails_after_creating_drops_what_it_created(self):
        # createdb created the database, then exited non-zero: no other run holds the name, so
        # the database is this run's own and is dropped with its lock.
        self.env['FAKE_CREATE_THEN_FAILS'] = '1'
        for compact in (False, True):
            with self.subTest(compact=compact):
                self.commands.unlink(missing_ok=True)
                result = self.invoke('test-module', *(['--compact'] if compact else []), 'coffee')
                database = self.events()[0][1]
                self.assertEqual(self.events(), [('exists', database), ('create', database),
                                                  ('exists', database), ('terminate', database),
                                                  ('drop', database)])
                message = ('create failed late\n'
                           f'Cannot create disposable test database {database}; '
                           'it was created anyway and is dropped.\n')
                if compact:
                    self.assertEqual((result.returncode, result.stderr), (1, ''))
                    lines = result.stdout.splitlines()
                    self.assertEqual(lines[:2], [f'phase=tests database={database} exit=1',
                                                 'database_lifecycle=disposable dropped=yes'])
                    self.assertEqual(Path(lines[3].split('=', 1)[1]).read_text(), message)
                else:
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', message))
                self.assertEqual(self.databases(), [])
                self.assertEqual(self.run_locks(), [])

    def test_a_create_that_fails_keeps_a_database_another_run_holds(self):
        # Another checkout's live run holds a lock of that name: the database is not this run's.
        database = 'cc_test_coffee_r123456'
        other = self.root.parent / 'other checkout'
        other.mkdir()
        sleeper = self.spawn_sleeper()
        self.assertEqual(self.state('run-lock', str(other), database, str(sleeper.pid)).returncode, 0)
        before = self.lock_path(database, other).read_bytes()
        self.env['FAKE_CREATE_THEN_FAILS'] = '1'
        result = self.invoke('test-module', '--disposable-run', database, 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, '', (
            f'create failed late\nCannot create disposable test database {database}; it was not dropped.\n')))
        self.assertEqual(self.events(), [('exists', database), ('create', database), ('exists', database)])
        self.assertEqual(self.databases(), [database])
        self.assertEqual(self.lock_path(database, other).read_bytes(), before)
        self.assertFalse(self.lock_path(database).exists())
        self.assertEqual(self.run_locks(), [f'{database}.json'])

    def test_a_locked_name_is_refused_and_neither_lock_nor_database_is_touched(self):
        database = 'cc_test_coffee_r123456'
        sleeper = self.spawn_sleeper()
        result = self.state('run-lock', str(self.root), database, str(sleeper.pid))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        before = self.lock_path(database).read_bytes()
        self.env['FAKE_EXISTS'] = '1'
        result = self.invoke('test-module', '--disposable-run', database, 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'Disposable test database is locked: {database}\n'))
        self.assertEqual(self.lock_path(database).read_bytes(), before)
        self.assertEqual(self.events(), [])
        # A stale lock (its run is gone) is not taken over either: gc removes it.
        sleeper.kill()
        sleeper.wait()
        result = self.invoke('test-module', '--disposable-run', database, 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'Disposable test database is locked: {database}\n'))
        self.assertEqual(self.lock_path(database).read_bytes(), before)
        self.assertEqual(self.events(), [])

    def test_compact_dropped_comes_from_the_run_not_from_the_lock(self):
        # Another live run holds the name: this run created nothing, so it left nothing behind,
        # although a lock of that name exists.
        database = 'cc_test_coffee_r123456'
        sleeper = self.spawn_sleeper()
        self.assertEqual(self.state('run-lock', str(self.root), database, str(sleeper.pid)).returncode, 0)
        result = self.invoke('test-module', '--compact', '--disposable-run', database, 'coffee')
        self.assertEqual((result.returncode, result.stderr), (2, ''))
        lines = result.stdout.splitlines()
        self.assertEqual(lines[:2], [f'phase=tests database={database} exit=2',
                                     'database_lifecycle=disposable dropped=yes'])
        stderr_log = Path(lines[3].split('=', 1)[1])
        self.assertEqual(stderr_log.read_text(), f'Disposable test database is locked: {database}\n')
        self.assertEqual(self.events(), [])
        self.assertTrue(self.lock_path(database).exists())

    def test_explicit_and_configured_databases_keep_reset_and_reuse(self):
        for extra, args, database in (('', ('coffee', 'cc_test_coffee'), 'cc_test_coffee'),
                                      ("test_database = 'cc_test_shared'\n", ('coffee',), 'cc_test_shared')):
            with self.subTest(database=database):
                self.write_profile(extra)
                self.commands.unlink(missing_ok=True)
                result = self.invoke('test-module', *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
                self.assertEqual(self.events(), [('exists', database), ('reset', database), ('tests', database)])
                self.assertEqual(self.seen_locks(), [])
                self.assertTrue((self.data / 'filestore' / database).is_dir())
                self.locks.unlink(missing_ok=True)

    def test_name_shortening_keeps_the_update_sibling_within_63_bytes(self):
        for slug, length, expected in (
                ('', 40, None), ('', 41, shortened('cc_test_', 'm' * 41)),
                ('wt_1', 35, None), ('wt_1', 41, shortened('cc_test_wt_1_', 'm' * 41))):
            with self.subTest(slug=slug, length=length):
                module = 'm' * length
                if not (self.root / module).exists():
                    self.add_module(module)
                self.write_profile(f"checkout_slug = '{slug}'\n" if slug else '')
                self.commands.unlink(missing_ok=True)
                result = self.invoke('test-module', module)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
                namespace = f'cc_test_{slug}_' if slug else 'cc_test_'
                stem = expected or namespace + module
                database = self.run_database()
                self.assertRegex(database, '^' + re.escape(stem) + RUN + '$')
                self.assertLessEqual(len(database.encode()), 56)
                if expected:
                    self.assertEqual(len(database.encode()), 56)

    def test_a_namespace_without_room_is_refused_before_any_command(self):
        prefix = 'a' * 45
        (self.root / 'oasis-workspace.toml').write_text(
            lifecycle.WORKSPACE.replace('cc_dev_', f'{prefix}_dev_').replace('cc_test_', f'{prefix}_test_'))
        result = self.invoke('test-module', 'coffee')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
            'ERROR: Test prefix and checkout slug leave no room for a disposable database name: '
            f'{prefix}_test_\n')))
        self.unchanged()

    def test_help_describes_disposable_databases(self):
        result = self.invoke('test-module', '--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertIn('disposable', result.stdout)
        self.assertIn('oasis gc', result.stdout)
        self.unchanged()


class DisposableVerifyModuleTests(DisposableFixture):
    def test_default_verify_uses_and_drops_a_disposable_pair(self):
        self.write_conf()
        result = self.invoke('verify-module', 'coffee')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        database = self.run_database()
        self.assertRegex(database, '^cc_test_coffee' + RUN + '$')
        update = database + '_update'
        self.assertIn(f'tests_database={database}\nupdate_database={update}\n', result.stdout)
        self.assertIn(f'database={database}\nmodule=coffee\ndatabase_state=ready\n', result.stdout)
        self.assertIn(f'database={update}\nmodule=coffee\ndatabase_state=ready\n', result.stdout)
        # Without --compact no lifecycle line (as test-module).
        self.assertNotIn('database_lifecycle', result.stdout)
        self.assertEqual(self.events()[:2], [('exists', database), ('exists', update)])
        flow = [event for event in self.events() if event[0] != 'exists']
        self.assertEqual(flow, [('reset', database), ('tests', database), ('reset', update),
                                ('install', update), ('update', update),
                                ('terminate', database), ('drop', database),
                                ('terminate', update), ('drop', update)])
        # Both locks were held while the tests ran, and are gone afterwards.
        self.assertEqual(sorted(lock['database'] for lock in self.seen_locks()), [database, update])
        self.assertEqual(self.run_locks(), [])
        self.assertEqual(sorted(path.name for path in (self.data / 'filestore').iterdir()), [])

    def test_failing_verify_still_drops_both(self):
        self.env['FAKE_TEST_EXIT'] = '3'
        result = self.invoke('verify-module', 'coffee')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        database = self.run_database()
        drops = [database for kind, database in self.events() if kind == 'drop']
        self.assertEqual(drops, [database, database + '_update'])
        self.assertNotIn('database_lifecycle', result.stdout)
        self.assertEqual(self.run_locks(), [])

    def test_compact_verify_reports_the_lifecycle(self):
        for drop_fails, dropped, status in (('0', 'yes', 0), ('1', 'no', 1)):
            with self.subTest(dropped=dropped):
                self.commands.unlink(missing_ok=True)
                self.env['FAKE_DROP_FAILS'] = drop_fails
                result = self.invoke('verify-module', '--compact', 'coffee')
                self.assertEqual(result.returncode, status, result.stdout + result.stderr)
                self.assertTrue(result.stdout.endswith(f'database_lifecycle=disposable dropped={dropped}\n'),
                                result.stdout)
                self.assertEqual(result.stdout.count('database_lifecycle='), 1)
                if dropped == 'no':
                    database = self.run_database()
                    self.assertTrue(result.stderr.endswith(
                        f'Cannot drop the disposable databases {database} and {database}_update; '
                        'run oasis gc --apply later.\n'), result.stderr)

    def test_existing_names_are_refused_and_nothing_is_dropped(self):
        self.env['FAKE_EXISTS'] = '1'
        result = self.invoke('verify-module', 'coffee')
        [(_, database)] = self.events()
        self.assertRegex(database, '^cc_test_coffee' + RUN + '$')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'Disposable test database already exists: {database}; it was left as it is.\n'
                          f'{REMEDY}\n'))
        self.assertEqual(self.run_locks(), [])

    def test_signals_drop_both_databases_and_leave_no_locks(self):
        # SIGTERM to verify-module only takes effect when the phase in progress returns (Bash
        # runs the trap then): the fake Odoo ends after FAKE_WAIT_SECONDS. Ctrl+C reaches the group.
        for signum, status, group, seconds in ((signal.SIGTERM, 143, False, '1'),
                                               (signal.SIGINT, 130, True, '30')):
            with self.subTest(signal=signum.name, group=group):
                self.commands.unlink(missing_ok=True)
                waiting = self.root.parent / f'verify-waiting-{signum}'
                self.env.update(FAKE_WAIT_SIGNAL=str(waiting), FAKE_WAIT_SECONDS=seconds)
                process = self.popen('verify-module', 'coffee', start_new_session=True)
                self.wait_for_odoo(process, waiting)
                self.assertEqual(len(self.run_locks()), 2)
                if group:
                    os.killpg(process.pid, signum)
                else:
                    os.kill(process.pid, signum)
                stdout, stderr = process.communicate(timeout=30)
                self.assertEqual(process.returncode, status, stdout + stderr)
                database = self.run_database()
                self.assertEqual([event for event in self.events() if event[0] in ('drop', 'terminate')], [
                    ('terminate', database), ('drop', database),
                    ('terminate', database + '_update'), ('drop', database + '_update')])
                self.assertNotIn(('install', database + '_update'), self.events())
                self.assertEqual(self.run_locks(), [])

    def fake_state_python(self):
        """A python3 first on PATH: FAKE_RUN_NAME fixes the disposable name; with
        FAKE_SIGNAL_AFTER_LOCK each run-lock sends that signal to its pid (verify-module) right
        after the lock was written, before verify-module can record it. Otherwise the real one."""
        fake = self.bindir / 'python3'
        fake.write_text(f'''#!/bin/sh
case "$3" in
  */runtime_state.py)
    case "$4" in
      run-name) if [ -n "${{FAKE_RUN_NAME:-}}" ]; then echo "$FAKE_RUN_NAME"; exit 0; fi ;;
      run-lock) if [ -n "${{FAKE_SIGNAL_AFTER_LOCK:-}}" ]; then
          status=0; "{sys.executable}" "$@" || status=$?
          kill -"$FAKE_SIGNAL_AFTER_LOCK" "$7"; exit $status
        fi ;;
    esac ;;
esac
exec "{sys.executable}" "$@"
''')
        fake.chmod(0o755)

    def test_a_name_another_live_run_holds_is_refused_and_left_alone(self):
        self.fake_state_python()
        database = 'cc_test_coffee_r123456'
        self.env['FAKE_RUN_NAME'] = database
        sleeper = self.spawn_sleeper()
        for held in (database, database + '_update'):
            with self.subTest(held=held):
                self.assertEqual(self.state('run-lock', str(self.root), held, str(sleeper.pid)).returncode, 0)
                before = self.lock_path(held).read_bytes()
                path = Path(str(self.commands) + '.databases')
                path.write_text(f'{held}\n')
                result = self.invoke('verify-module', 'coffee')
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, '', f'Disposable test database is locked: {held}\n'))
                # The other run's lock and database are untouched; no lock of this run is left.
                self.assertEqual(self.lock_path(held).read_bytes(), before)
                self.assertEqual(self.run_locks(), [f'{held}.json'])
                self.assertEqual(path.read_text(), f'{held}\n')
                self.assertEqual(self.events(), [])
                self.lock_path(held).unlink()
                path.unlink()

    def test_a_signal_while_taking_the_locks_leaves_no_lock(self):
        # The signal arrives after run-lock wrote the lock and before verify-module recorded it:
        # verify-module defers it until the lock is recorded, then removes its locks and exits.
        self.fake_state_python()
        for signum, status in ((signal.SIGTERM, 143), (signal.SIGINT, 130)):
            with self.subTest(signal=signum.name):
                self.commands.unlink(missing_ok=True)
                self.env['FAKE_SIGNAL_AFTER_LOCK'] = signum.name[3:]
                result = self.invoke('verify-module', 'coffee')
                self.assertEqual((result.returncode, result.stdout, result.stderr), (status, '', ''))
                self.assertEqual(self.run_locks(), [])
                self.assertEqual(self.events(), [])

    def test_explicit_verify_databases_are_not_dropped(self):
        result = self.invoke('verify-module', 'coffee', 'cc_test_isolated')
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)
        self.assertNotIn('database_lifecycle', result.stdout)
        self.assertEqual([event for event in self.events() if event[0] in ('drop', 'terminate')], [])


class GcFixture(DisposableFixture):
    LIVE = 'cc_test_wt_1_coffee_r111111'
    ORPHAN = 'cc_test_wt_1_coffee_r222222'
    OTHER_SLUG = 'cc_test_wt_2_coffee_r333333'
    MAIN = 'cc_test_coffee_r444444'
    DATABASES = ('cc_dev_wt_1_coffee', MAIN, 'cc_test_wt_1_coffee', LIVE, ORPHAN, ORPHAN + '_update',
                 'cc_test_wt_1_coffee_r55555', OTHER_SLUG)

    def setUp(self):
        super().setUp()
        self.write_profile("checkout_slug = 'wt_1'\n")
        self.write_conf()
        Path(str(self.commands) + '.databases').write_text(''.join(f'{name}\n' for name in self.DATABASES))
        for name in self.DATABASES:
            (self.data / 'filestore' / name).mkdir(parents=True)
        self.sleeper = self.spawn()
        self.lock(self.LIVE, self.sleeper.pid)
        # The orphan's lock names a live process whose command line is not the run's (pid reuse).
        self.lock(self.ORPHAN, self.sleeper.pid)
        path = self.lock_path(self.ORPHAN)
        record = json.loads(path.read_text())
        path.write_text(json.dumps({**record, 'argv': ['another', 'program']}))
        self.before = {name: self.lock_path(name).read_bytes() for name in (self.LIVE, self.ORPHAN)}

    def spawn(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        return process

    def lock(self, database, pid, root=None):
        result = subprocess.run([sys.executable, '-B', str(STATE), 'run-lock', str(root or self.root),
                                 database, str(pid)], capture_output=True, text=True, env=self.env)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))

    def lock_path(self, database, root=None):
        digest = hashlib.sha256(str(Path(root or self.root).resolve()).encode()).hexdigest()[:16]
        return self.xdg / f'oasis-{os.getuid()}' / digest / 'runs' / f'{database}.json'

    def gc(self, *args, root=None):
        return subprocess.run([sys.executable, '-B', str(CLI), '--project', str(root or self.root), 'gc', *args],
                              cwd=root or self.root, env=self.env, capture_output=True, text=True)

    def remaining(self):
        return Path(str(self.commands) + '.databases').read_text().split()

    def filestores(self):
        return sorted(path.name for path in (self.data / 'filestore').iterdir())


class GcTests(GcFixture):
    def assert_nothing_changed(self):
        self.assertEqual(self.remaining(), list(self.DATABASES))
        self.assertEqual(self.filestores(), sorted(self.DATABASES))
        self.assertEqual({name: self.lock_path(name).read_bytes() for name in (self.LIVE, self.ORPHAN)},
                         self.before)
        self.assertEqual([event for event in self.events() if event[0] in ('drop', 'terminate')], [])

    def test_dry_run_lists_only_this_namespace_orphans(self):
        result = self.gc()
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, (
            f'orphan {self.ORPHAN}\norphan {self.ORPHAN}_update\norphans=2\n'), ''))
        self.assert_nothing_changed()

    def test_apply_drops_only_the_orphans_and_their_filestores(self):
        result = self.gc('--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, (
            f'dropped {self.ORPHAN}\ndropped {self.ORPHAN}_update\ndropped=2\nfailed=0\n'), ''))
        self.assertEqual([event for event in self.events() if event[0] in ('drop', 'terminate')], [
            ('terminate', self.ORPHAN), ('drop', self.ORPHAN),
            ('terminate', self.ORPHAN + '_update'), ('drop', self.ORPHAN + '_update')])
        kept = [name for name in self.DATABASES if not name.startswith(self.ORPHAN)]
        self.assertEqual(self.remaining(), kept)
        self.assertEqual(self.filestores(), sorted(kept))
        # The orphan's stale lock is removed; the live run keeps its lock.
        self.assertFalse(self.lock_path(self.ORPHAN).exists())
        self.assertEqual(self.lock_path(self.LIVE).read_bytes(), self.before[self.LIVE])

    def test_a_failed_drop_is_reported_and_the_next_orphan_still_dropped(self):
        self.env['FAKE_DROP_FAILS_FOR'] = self.ORPHAN
        result = self.gc('--apply')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, (
            f'dropped {self.ORPHAN}_update\ndropped=1\nfailed=1\n'), f'drop failed\nfailed {self.ORPHAN}\n'))
        self.assertEqual([event for event in self.events() if event[0] in ('drop', 'terminate')], [
            ('terminate', self.ORPHAN), ('drop', self.ORPHAN),
            ('terminate', self.ORPHAN + '_update'), ('drop', self.ORPHAN + '_update')])
        self.assertEqual(self.remaining(), [name for name in self.DATABASES if name != self.ORPHAN + '_update'])
        # The failed orphan keeps its filestore and its stale lock for the next gc.
        self.assertIn(self.ORPHAN, self.filestores())
        self.assertNotIn(self.ORPHAN + '_update', self.filestores())
        self.assertEqual(self.lock_path(self.ORPHAN).read_bytes(), self.before[self.ORPHAN])

    def test_all_checkouts_widens_to_every_slug_of_the_test_prefix(self):
        result = self.gc('--all-checkouts')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, (
            f'orphan {self.MAIN}\norphan {self.ORPHAN}\norphan {self.ORPHAN}_update\n'
            f'orphan {self.OTHER_SLUG}\norphans=4\n'), ''))
        self.assert_nothing_changed()
        # A checkout with a slug may drop only its own namespace (the S8 guard).
        result = self.gc('--apply', '--all-checkouts')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', (
            'Checkout wt_1 may drop only its own databases (cc_test_wt_1_*); '
            'run gc --apply --all-checkouts from the main checkout.\n')))
        self.assert_nothing_changed()
        # The main checkout drops every namespace's orphans.
        self.write_profile('')
        result = self.gc('--apply', '--all-checkouts')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout, f'dropped {self.MAIN}\ndropped {self.ORPHAN}\ndropped {self.ORPHAN}_update\n'
                                        f'dropped {self.OTHER_SLUG}\ndropped=4\nfailed=0\n')
        self.assertEqual(self.remaining(), ['cc_dev_wt_1_coffee', 'cc_test_wt_1_coffee', self.LIVE,
                                            'cc_test_wt_1_coffee_r55555'])

    def test_a_finished_run_lock_is_an_orphan(self):
        self.sleeper.kill()
        self.sleeper.wait()
        result = self.gc()
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, (
            f'orphan {self.LIVE}\norphan {self.ORPHAN}\norphan {self.ORPHAN}_update\norphans=3\n'), ''))

    def test_nothing_to_do_exits_zero(self):
        Path(str(self.commands) + '.databases').write_text('cc_dev_wt_1_coffee\n')
        for args, stdout in (((), 'orphans=0\n'), (('--apply',), 'dropped=0\nfailed=0\n')):
            with self.subTest(args=args):
                result = self.gc(*args)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, stdout, ''))

    def test_usage_and_help(self):
        result = self.gc('--force')
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (2, '', f'Usage: {CLI} gc [--apply] [--all-checkouts] | gc [--apply] --trash [--older-than <days>]\n'))
        self.unchanged()
        result = self.gc('--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(f'Usage: {CLI} gc [--apply] [--all-checkouts] | gc [--apply] --trash [--older-than <days>]\n'))
        self.assertIn('--apply', result.stdout)
        self.unchanged()


class GcWorktreeTests(DisposableFixture):
    """The main checkout's namespace excludes the slugs of its existing linked worktrees."""

    def setUp(self):
        super().setUp()
        shared.shared_layout(self)
        self.main_orphan, self.linked_orphan = 'cc_test_coffee_r1a2b3c', 'cc_test_wt_coffee_r4d5e6f'
        Path(str(self.commands) + '.databases').write_text(
            f'cc_dev_coffee\n{self.main_orphan}\ncc_test_wt_coffee\n{self.linked_orphan}\n')

    gc = GcFixture.gc

    def test_each_checkout_sees_only_its_own_orphans(self):
        for root, orphan in ((self.main, self.main_orphan), (self.linked, self.linked_orphan)):
            with self.subTest(root=root.name):
                result = self.gc(root=root)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (0, f'orphan {orphan}\norphans=1\n', ''))
        result = self.gc('--all-checkouts', root=self.main)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'orphan {self.main_orphan}\norphan {self.linked_orphan}\norphans=2\n', ''))


class GcWorkspaceWorktreeTests(DisposableFixture):
    """Workspace mode: a linked worktree's slug comes from its oasis-checkout.toml."""

    WORKSPACE = '''workspace_version = 1
odoo_version = '19.0'

[tooling]
community = 'source/odoo'
environment = 'environments/example'
config = 'projects/config/odoo.conf'
env_file = 'projects/config/runtime-env'
compose = 'projects/config/compose.yml'
requirements = 'projects/config/requirements'
addons_paths = ['.']
db_service = 'db'
dev_prefix = 'cc_dev_'
test_prefix = 'cc_test_'
'''

    def setUp(self):
        super().setUp()
        shared.shared_layout(self)
        # The workspace sits above <projects>; neither checkout keeps a profile.
        (self.main.parent.parent / 'oasis-workspace.toml').write_text(self.WORKSPACE)
        for checkout in (self.main, self.linked):
            (checkout / 'oasis-workspace.toml').unlink()
        # The folder would derive `wt`; the checkout file sets another slug.
        (self.linked / 'oasis-checkout.toml').write_text("[tooling]\ncheckout_slug = 'shop'\n")
        self.main_orphan, self.linked_orphan = 'cc_test_coffee_r1a2b3c', 'cc_test_shop_coffee_r4d5e6f'
        Path(str(self.commands) + '.databases').write_text(
            f'cc_dev_coffee\n{self.main_orphan}\ncc_test_shop_coffee\n{self.linked_orphan}\n')

    gc = GcFixture.gc

    def test_each_checkout_sees_only_its_own_orphans(self):
        for root, orphan in ((self.main, self.main_orphan), (self.linked, self.linked_orphan)):
            with self.subTest(root=root.name):
                result = self.gc(root=root)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (0, f'orphan {orphan}\norphans=1\n', ''))
        result = self.gc('--all-checkouts', root=self.main)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'orphan {self.main_orphan}\norphan {self.linked_orphan}\norphans=2\n', ''))
        self.assertEqual([event for event in self.events() if event[0] in ('drop', 'terminate')], [])

    def test_an_untrusted_checkout_file_stops_gc_instead_of_guessing_the_slug(self):
        # Falling back to the folder slug `wt` would list `shop` databases as the main
        # checkout's orphans; gc must stop and drop nothing.
        checkout_file = self.linked / 'oasis-checkout.toml'
        checkout_file.chmod(0o664)
        for args in ((), ('--apply',)):
            with self.subTest(args=args):
                result = self.gc(*args, root=self.main)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')
                self.assertIn(f'Cannot read the checkout slug of {self.linked.resolve()}', result.stderr)
                self.assertIn('Refusing untrusted workspace file', result.stderr)
        self.assertEqual([event for event in self.events() if event[0] in ('drop', 'terminate')], [])


class ReservedRunNameTests(DisposableFixture):
    """Names with the run suffix belong to disposable runs: normal work refuses them (S5)."""

    def cli(self, command, *args):
        return subprocess.run([sys.executable, '-B', str(CLI), '--project', str(self.root), command, *args],
                              cwd=self.root, env=self.env, capture_output=True, text=True, input='')

    def test_commands_that_create_or_reuse_a_database_refuse_reserved_names(self):
        for command, args, database in (
                ('create-database', ('cc_test_coffee_r123456',), 'cc_test_coffee_r123456'),
                ('install-module', ('coffee', 'cc_dev_coffee_r1a2b3c'), 'cc_dev_coffee_r1a2b3c'),
                ('install-module', ('--with-demo', 'coffee', 'cc_test_coffee_r123456_update'),
                 'cc_test_coffee_r123456_update'),
                ('update-module', ('coffee', 'cc_test_coffee_r123456'), 'cc_test_coffee_r123456'),
                ('odoo-shell', ('cc_test_coffee_r123456',), 'cc_test_coffee_r123456'),
                ('start', ('-d', 'cc_dev_coffee_r1a2b3c'), 'cc_dev_coffee_r1a2b3c'),
                ('start', ('-dcc_dev_coffee_r1a2b3c',), 'cc_dev_coffee_r1a2b3c'),
                ('start', ('--database=cc_dev_coffee_r1a2b3c',), 'cc_dev_coffee_r1a2b3c'),
                ('init-dev-database', ('coffee', 'cc_dev_coffee_r1a2b3c'), 'cc_dev_coffee_r1a2b3c'),
                ('test-module', ('coffee', 'cc_test_coffee_r123456'), 'cc_test_coffee_r123456'),
                ('test-module', ('--compact', 'coffee', 'cc_test_coffee_r123456'), 'cc_test_coffee_r123456'),
                ('verify-module', ('coffee', 'cc_test_coffee_r123456'), 'cc_test_coffee_r123456'),
                ('verify-module', ('coffee', 'cc_test_iso', 'cc_test_iso_r123456_update'),
                 'cc_test_iso_r123456_update')):
            with self.subTest(command=command, args=args):
                result = self.cli(command, *args)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, '', RESERVED.format(database)))
                self.unchanged()
                self.assertEqual(self.run_locks(), [])

    def test_a_configured_reserved_test_database_is_refused(self):
        self.write_profile("test_database = 'cc_test_shared_r1a2b3c'\n")
        for command in ('test-module', 'verify-module'):
            with self.subTest(command=command):
                result = self.cli(command, 'coffee')
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, '', RESERVED.format('cc_test_shared_r1a2b3c')))
                self.unchanged()

    def test_a_live_run_lock_of_another_process_does_not_unlock_the_name(self):
        database = 'cc_test_coffee_r123456'
        sleeper = self.spawn_sleeper()
        self.assertEqual(self.state('run-lock', str(self.root), database, str(sleeper.pid)).returncode, 0)
        result = self.cli('update-module', 'coffee', database)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', RESERVED.format(database)))
        self.unchanged()

    def test_similar_names_without_the_exact_suffix_are_not_reserved(self):
        self.env['FAKE_EXISTS'] = '1'
        for database in ('cc_test_coffee_r12345', 'cc_test_coffee_rABCDEF', 'cc_test_coffee_r1234567',
                         'cc_test_coffee_r123456_updates'):
            with self.subTest(database=database):
                result = self.cli('update-module', 'coffee', database)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))

    def test_cleanup_and_inspection_still_accept_reserved_names(self):
        database = 'cc_test_coffee_r123456'
        result = self.cli('module-status', 'coffee', database)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, (
            f'database={database}\nmodule=coffee\ndatabase_state=missing\nmodule_state=unknown\n'), ''))
        result = self.cli('drop-database', database)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (0, f'Database does not exist: {database}\n', ''))
        Path(str(self.commands) + '.databases').write_text(f'{database}\n')
        self.commands.unlink()
        result = self.cli('drop-database', database)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertRegex(result.stdout, rf'\nDatabase moved to trash: {database} -> {database}_trash_\d{{8}}_\d{{6}}\n')
        [rename] = [entry for entry in entries(self.log()) if 'ALTER DATABASE' in entry]
        self.assertIn(f'ALTER DATABASE "{database}" RENAME TO "{database}_trash_', rename)


if __name__ == '__main__':
    unittest.main()
