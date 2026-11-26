"""Run only the Odoo test process with short owned scratch (internal CLI).

Usage:
  test_temp.py <project_root> <command...>
  test_temp.py --disposable <database> <odoo.conf> <project_root> <command...>
      the same run on a new disposable test database: create its run lock exclusively (an
      existing lock, live or not, exits 2 and touches nothing), check that the name is free,
      create it, run the tests, then drop it, remove its filestore and the lock (success,
      failure, SIGINT and SIGTERM alike). Only a database this run created is dropped: when
      createdb fails, the name is dropped only if it exists now and no other live run of this
      user holds a lock of it (createdb created it, then failed); otherwise (the name was
      taken in the meantime) nothing is dropped. A database that
      cannot be dropped keeps its lock and is reported; `oasis gc --apply` removes it later.
      With OASIS_RUN_RESULT set (test-module --compact), the run writes `yes` (it left no
      database behind: dropped, or never created) or `no` to that new file at the end.
  test_temp.py --discard <database> <odoo.conf> <project_root>
      drop a disposable database and its filestore, then remove its run lock (verify-module).

This process owns the cleanup because it already owns the signals: it forwards SIGINT and
SIGTERM to the Odoo test process and cleans up after that process ends, whether the signal
reached the whole process group (a terminal) or only this process (test-module execs it).
"""
from pathlib import Path
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile

import config
import odoo_addons_path
import runtime_state

TOOLS = Path(__file__).resolve().parent
RESULT = 'OASIS_RUN_RESULT'
USAGE = ('Usage: test_temp.py [--disposable <database> <odoo.conf>] <project_root> <command...> | '
         '--discard <database> <odoo.conf> <project_root>')


def database_step(function, database):
    """Run one common.sh database function in a fresh Bash (errexit kept); its exit status."""
    return subprocess.run(['bash', '-c', 'source "$1"; "$2" "$3"', 'test-temp',
                           str(TOOLS / 'common.sh'), function, database]).returncode


def create_step(database):
    """Run create_disposable_database; its exit status and whether createdb found the name taken.

    stderr is relayed unchanged. "already exists" means another creator won the name, so the
    database is never this run's own.
    """
    result = subprocess.run(['bash', '-c', 'source "$1"; "$2" "$3"', 'test-temp',
                             str(TOOLS / 'common.sh'), 'create_disposable_database', database],
                            stderr=subprocess.PIPE, text=True, errors='replace')
    sys.stderr.write(result.stderr)
    sys.stderr.flush()
    return result.returncode, 'already exists' in result.stderr


def filestore_path(conf, database):
    """<data_dir>/filestore/<database>, or None without a known data_dir.

    data_dir is DATA_DIR ([tooling].data_dir, which Odoo receives as --data-dir; common.sh
    exports it) when set; otherwise only the conf's data_dir is read. Without an absolute
    data_dir (absent, or relative to an unknown working directory) nothing is known. An
    unreadable conf raises odoo_addons_path.ConfError. tools/trash.py moves filestores with it.
    """
    data_dir = os.environ.get('DATA_DIR', '')
    if not data_dir:
        value = (odoo_addons_path.read_option(conf, 'data_dir') or '').strip()
        data_dir = os.path.expanduser(value) if value else ''
    if not os.path.isabs(data_dir):
        return None
    return Path(data_dir) / 'filestore' / database


def remove_filestore(conf, database):
    """Remove <data_dir>/filestore/<database> (filestore_path).

    Without a known data_dir there is nothing known to remove. A filestore entry that is not a
    directory is never followed.
    """
    try:
        path = filestore_path(conf, database)
    except odoo_addons_path.ConfError as exc:
        print(f'{exc} Filestore of {database} not removed.', file=sys.stderr)
        return False
    if path is None:
        return True
    try:
        if not stat.S_ISDIR(os.lstat(path).st_mode):
            print(f'Filestore of {database} is not a directory; not removed: {path}', file=sys.stderr)
            return False
        shutil.rmtree(path)
    except FileNotFoundError:
        return True
    except OSError:
        print(f'Cannot remove the filestore of {database}: {path}', file=sys.stderr)
        return False
    return True


def discard(conf, database):
    """Drop a disposable database, then remove its filestore; True when the database is gone."""
    if database_step('drop_disposable_database', database) != 0:
        return False
    remove_filestore(conf, database)
    return True


def held_by_another_run(database):
    """True when a live run lock of database belongs to another process (any checkout)."""
    return any(live and record['database'] == database and record['pid'] != os.getpid()
               for _path, _seen, record, live in runtime_state.run_locks())


def unlock(root, database, pid=None):
    try:
        runtime_state.remove_run_lock(root, database, pid)
    except (runtime_state.StateError, runtime_state.RunError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return False
    return True


def retain_evidence(root, scratch):
    """Keep browser logs and visual diagnostics, not browser profiles or cookies."""
    source = scratch / 'odoo_tests'
    if source.is_symlink() or not source.is_dir():
        return
    destination = None

    def unreadable(error):
        raise error

    for directory, dirs, files in os.walk(source, followlinks=False, onerror=unreadable):
        base = Path(directory)
        dirs[:] = [name for name in dirs if not (base / name).is_symlink()]
        for name in files:
            path = base / name
            relative = path.relative_to(source)
            if not stat.S_ISREG(path.lstat().st_mode):
                continue
            if 'chrome_logs' not in relative.parts[:-1] and path.suffix.lower() not in {
                    '.png', '.jpg', '.jpeg', '.webm', '.mp4'}:
                continue
            if destination is None:
                # Reuse the existing project log allocator and its containment/privacy guards.
                result = subprocess.run(
                    ['bash', '-c', 'source "$1"; compact_log_directory', 'test-temp',
                     str(Path(__file__).with_name('compact.sh'))],
                    env={**os.environ, 'PROJECT_ROOT': str(root)},
                    capture_output=True, text=True, check=True)
                destination = Path(result.stdout.strip()) / 'odoo_tests'
            target = destination / relative
            # mkdir(parents=True) applies the mode only to the leaf; keep every
            # retained directory private, including odoo_tests itself.
            for directory in (destination, *(destination / Path(*relative.parts[:depth])
                                             for depth in range(1, len(relative.parts)))):
                directory.mkdir(exist_ok=True, mode=0o700)
                directory.chmod(0o700)
            # Never follow an evidence-file symlink, even if replaced during collection.
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, 'rb') as incoming, os.fdopen(
                    os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            target.chmod(0o600)


def report_result(dropped):
    """Write the run's own cleanup result for test-module --compact (a new private file)."""
    path = os.environ.get(RESULT)
    if not path:
        return
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write('yes\n' if dropped else 'no\n')
    except OSError:
        print(f'Cannot record the disposable run result: {path}', file=sys.stderr)


def main():
    args = sys.argv[1:]
    if args[:1] == ['--discard']:
        if len(args) != 4:
            print(USAGE, file=sys.stderr)
            return 2
        database, conf, root = args[1:]
        if not discard(conf, database):
            return 1
        return 0 if unlock(root, database) else 1
    disposable = conf = None
    if args[:1] == ['--disposable']:
        if len(args) < 5:
            print(USAGE, file=sys.stderr)
            return 2
        disposable, conf, args = args[1], args[2], args[3:]
    if len(args) < 2:
        print('Test scratch helper requires project root and command.', file=sys.stderr)
        return 2
    root, command = args[0], args[1:]
    try:
        scratch = Path(tempfile.mkdtemp(prefix='oasis-test-', dir='/tmp'))
    except OSError:
        print('Cannot create private test scratch under /tmp.', file=sys.stderr)
        return 1
    child = None
    received = None

    def forward(signum, _frame):
        nonlocal received
        received = signum
        if child is not None:
            try:
                child.send_signal(signum)
            except ProcessLookupError:
                pass

    previous = {sig: signal.signal(sig, forward) for sig in (signal.SIGINT, signal.SIGTERM)}
    status = 1
    locked = created = False
    try:
        if disposable is not None:
            # The lock comes first, so gc never takes the database for an orphan, and it is
            # exclusive, so no other run uses the name.
            try:
                runtime_state.write_run_lock(root, disposable, os.getpid())
                locked = True
            except runtime_state.RunLocked as exc:
                print(exc, file=sys.stderr)
                status = 2
            except (runtime_state.StateError, runtime_state.RunError) as exc:
                print(f'ERROR: {exc}', file=sys.stderr)
                status = 2
            if locked:
                status = database_step('require_free_disposable_database', disposable)
            if locked and status == 0 and received is None:
                status, taken = create_step(disposable)
                if status == 0:
                    # Only now is the database this run's own: from here on it is dropped.
                    created = True
                elif (not taken and database_step('database_exists', disposable) == 0
                      and not held_by_another_run(disposable)):
                    # The name was free and this run holds its lock: createdb created it, then
                    # failed. It is this run's own and is dropped at the end.
                    created = True
                    print(f'Cannot create disposable test database {disposable}; '
                          'it was created anyway and is dropped.', file=sys.stderr)
                else:
                    print(f'Cannot create disposable test database {disposable}; it was not dropped.',
                          file=sys.stderr)
        if disposable is None or (created and status == 0 and received is None):
            environment = {key: value for key, value in os.environ.items() if key != RESULT}
            try:
                child = subprocess.Popen(command, env={**environment, 'TMPDIR': str(scratch)})
                if received is not None:
                    forward(received, None)
                code = child.wait()
                status = 128 + (-code) if code < 0 else code
            except OSError:
                print('Cannot launch Odoo test process.', file=sys.stderr)
                status = 1
        if received is not None:
            status = 128 + received
        try:
            retain_evidence(Path(root).resolve(), scratch)
        except (OSError, subprocess.SubprocessError):
            print(f'Cannot retain browser evidence; test scratch kept at {scratch}. '
                  'Inspect it before manual removal.', file=sys.stderr)
            status = status or 1
        else:
            try:
                shutil.rmtree(scratch)
            except OSError:
                print(f'Cannot clean owned test scratch: {scratch}. Inspect before manual removal.',
                      file=sys.stderr)
                status = status or 1
        dropped = True
        if created and not discard(conf, disposable):
            print(f'Cannot drop disposable test database {disposable}; '
                  f'run {config.program_name()} gc --apply later.',
                  file=sys.stderr)
            status = status or 1
            dropped = False
        elif locked and not unlock(root, disposable, os.getpid()):
            status = status or 1
        if disposable is not None:
            report_result(dropped)
        return status
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    sys.exit(main())
