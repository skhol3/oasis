#!/usr/bin/env python3
"""Per-checkout runtime state of the Odoo server that `start` runs, and port probes (internal CLI).

Usage:
  runtime_state.py show <project_root>       pid=<pid> port=<port> when a live server is recorded
  runtime_state.py record <project_root> <pid> <port> <odoo_bin> [<python>]
  runtime_state.py detach <project_root> <port> <log> <odoo_bin> <python> -- <odoo argument>...
                                             start <python> <odoo_bin> <arguments> in a new
                                             session with stdin from /dev/null and stdout and
                                             stderr appended to <log> (0600), record it, and
                                             print pid=<pid> port=<port> log=<log> (see below)
  runtime_state.py stop <project_root>       SIGTERM this checkout's server, wait up to 20 s
  runtime_state.py others <project_root>     live servers of the other checkouts, one per line
  runtime_state.py port <interface> <first> <last> [<excluded>...]
                                             first port in [first, last] free on the interface
                                             (exit 1 when none; exit 2 and `Cannot bind port
                                             <p>: <reason>.` when a bind fails otherwise)
  runtime_state.py ephemeral-port [<excluded>...]
                                             a free ephemeral port on 127.0.0.1, none of the
                                             excluded ones (a test run's second port)
  runtime_state.py run-name <namespace> <module>
                                             a new disposable test database name (see below)
  runtime_state.py run-lock <project_root> <database> <pid>
                                             create the run lock exclusively (exit 2 and
                                             `Disposable test database is locked: <database>`
                                             when one exists, live or not)
  runtime_state.py run-unlock <project_root> <database>
  runtime_state.py run-owned <project_root> <database> <pid>
                                             exit 0 when this checkout's lock of database is
                                             live and held by pid, 1 when not
  runtime_state.py compose-lock <compose_file>
                                             the path of the lock file that serializes
                                             `compose up` of that compose file (created 0600)

State lives in ${XDG_RUNTIME_DIR, or /tmp}/oasis-<uid>/<first 16 hex of sha256(realpath
project_root)>/server.json ({pid, port, started_at, project_root, odoo_bin, python}); both directories
are 0700 and refused when they are symlinks, not directories or owned by another user. Never
inside a repository or a shared directory. A record is live while its pid is a process of this
user whose command line (/proc, Linux) is the Odoo launch: argv[1] is the recorded odoo-bin
and argv[0] a python interpreter (a name starting with `python`, or the recorded python, realpaths
compared), or argv[0] is odoo-bin. Within GRACE seconds of started_at any
process of the pid is live (start writes the record before it execs Odoo). A stale or invalid
record is removed when read, only if the file still holds what was read.

Disposable test runs: `<namespace><module>_r<6 hex>`, at most 56 bytes so verify-module's
`_update` sibling fits PostgreSQL's 63; a longer name keeps the first N characters of the
module plus `_` and 4 hex of sha256(module). Each run holds a lock `runs/<database>.json`
({pid, started_at, database, project_root, argv}, 0600) in the same private state directory,
created exclusively (O_EXCL on the final path, then written and fsynced): an existing lock,
live or stale, is never replaced, so two runs never share a name. A lock is live while its pid
runs the recorded command line (argv read from /proc when it was written, compared exactly,
whatever the interpreter), so a reused pid does not keep an orphan alive.

Detached server (start --detach): the record names the new process, written right after it is
forked. The command then waits up to DETACH_WAIT seconds (OASIS_DETACH_WAIT, for the tests only),
returning as soon as 127.0.0.1:<port> accepts connections; a server still alive at the end counts
as started. One that exits meanwhile has its record removed, and the command prints
`Odoo exited at once with status <n>; the end of <log>:` and the last DETACH_TAIL lines it wrote,
then exits 1.

Compose lock: `compose-<first 16 hex of sha256(realpath compose_file)>.lock` (0600) directly in
the user root, shared by every checkout of this user whose profile names that compose file.
This helper only creates and checks it (a regular file of the current user); common.sh holds
it with flock(1) around `compose up`.
"""
from datetime import datetime, timezone
import errno
import hashlib
import math
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import stat
import sys
import tempfile
import time

RECORD = 'server.json'
STOP_TIMEOUT = 20
GRACE = 10
DETACH_WAIT = 10.0
DETACH_TAIL = 20
RUNS = 'runs'
RUN_NAME_BYTES = 56
RUN_DATABASE = re.compile(r'[A-Za-z0-9_]+_r[0-9a-f]{6}(?:_update)?')
DATABASE = re.compile(r'[A-Za-z0-9_]+')


class StateError(Exception):
    """An unsafe or unreadable state directory; the message names the path."""


class PortError(Exception):
    """A port that cannot be probed for a reason other than being in use."""


class RunError(Exception):
    """A disposable run name or lock that cannot be made; the message says why."""


class RunLocked(RunError):
    """A run lock of that database already exists; the message names the database."""


def user_root():
    base = os.environ.get('XDG_RUNTIME_DIR') or ''
    if not os.path.isabs(base):
        base = '/tmp'
    return Path(base) / f'oasis-{os.getuid()}'


def checkout_dir(project_root):
    digest = hashlib.sha256(os.path.realpath(project_root).encode()).hexdigest()[:16]
    return user_root() / digest


def check_dir(path):
    """True when path is a safe existing state directory, False when it does not exist."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        raise StateError(f'Runtime state directory is a symlink: {path}')
    if not stat.S_ISDIR(info.st_mode):
        raise StateError(f'Runtime state directory is not a directory: {path}')
    if info.st_uid != os.getuid():
        raise StateError(f'Runtime state directory is not owned by the current user: {path}')
    if info.st_mode & 0o077:
        os.chmod(path, 0o700)
    return True


def ensure_dir(path):
    if check_dir(path):
        return
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    check_dir(path)
    os.chmod(path, 0o700)


def state_dir(project_root, create):
    """The checkout's state directory, or None when it does not exist and create is False."""
    root = user_root()
    if create:
        ensure_dir(root)
    elif not check_dir(root):
        return None
    directory = checkout_dir(project_root)
    if create:
        ensure_dir(directory)
    elif not check_dir(directory):
        return None
    return directory


def command_line(pid):
    """argv of a process of this user, or None when there is none (gone, zombie, other user)."""
    try:
        if os.stat(f'/proc/{pid}').st_uid != os.getuid():
            return None
        with open(f'/proc/{pid}/cmdline', 'rb') as stream:
            raw = stream.read()
    except (OSError, ValueError):
        return None
    parts = raw.split(b'\0')
    if parts[-1] == b'':
        parts.pop()
    # A zombie has an empty command line: it is not running anything.
    return [os.fsdecode(part) for part in parts] or None


def is_odoo_launch(argv, odoo_bin, python=None):
    names = {odoo_bin, os.path.realpath(odoo_bin)}
    if argv[0] in names:
        return True
    if len(argv) < 2 or argv[1] not in names:
        return False
    if os.path.basename(argv[0]).startswith('python'):
        return True
    # The interpreter start ran (the profile's python) may have any name, e.g. pypy3.
    return bool(python) and (argv[0] == python or os.path.realpath(argv[0]) == os.path.realpath(python))


def in_grace(record):
    try:
        started = datetime.fromisoformat(record.get('started_at'))
    except (TypeError, ValueError):
        return False
    if started.tzinfo is None:
        return False
    age = (datetime.now(timezone.utc) - started).total_seconds()
    return math.isfinite(age) and 0 <= age < GRACE


def is_live(record):
    argv = command_line(record['pid'])
    if argv is None:
        return False
    return is_odoo_launch(argv, record['odoo_bin'], record.get('python')) or in_grace(record)


def parse(raw):
    data = json.loads(raw.decode('utf-8'))
    if not isinstance(data, dict):
        raise ValueError('invalid record')
    pid, port = data.get('pid'), data.get('port')
    if (not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 or not isinstance(port, int)
            or isinstance(port, bool) or not isinstance(data.get('odoo_bin'), str)
            or not isinstance(data.get('project_root'), str)
            or not isinstance(data.get('python', ''), str)):
        raise ValueError('invalid record')
    return data


def snapshot(path):
    """What the record path holds: None when missing, else a comparable (kind, content)."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode):
        return ('link', os.readlink(path))
    if not stat.S_ISREG(info.st_mode):
        return ('other', info.st_mode, info.st_ino)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return ('link', os.readlink(path))
        raise
    with os.fdopen(descriptor, 'rb') as stream:
        return ('file', stream.read())


def discard_stale(path, seen):
    """Remove the record only if it still holds what was judged stale (best effort)."""
    try:
        if snapshot(path) == seen:
            path.unlink()
    except FileNotFoundError:
        pass


def read_live(directory):
    """The live record of a state directory, or None; a stale or invalid record is removed."""
    path = directory / RECORD
    try:
        seen = snapshot(path)
    except OSError as exc:
        raise StateError(f'Cannot read runtime state: {path}') from exc
    if seen is None:
        return None
    record = None
    if seen[0] == 'file':
        try:
            record = parse(seen[1])
        except (ValueError, UnicodeDecodeError, RecursionError):
            record = None
    if record is not None and is_live(record):
        return record
    try:
        discard_stale(path, seen)
    except OSError as exc:
        raise StateError(f'Cannot remove stale runtime state: {path}') from exc
    return None


def live_record(project_root):
    directory = state_dir(project_root, create=False)
    return read_live(directory) if directory else None


def write_record(project_root, pid, port, odoo_bin, python=None):
    directory = state_dir(project_root, create=True)
    record = {'pid': pid, 'port': port,
              'started_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'project_root': os.path.realpath(project_root), 'odoo_bin': odoo_bin}
    if python:
        record['python'] = python
    descriptor, temporary = tempfile.mkstemp(prefix='.server-', dir=directory)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(record, stream)
        os.replace(temporary, directory / RECORD)
    except BaseException:
        os.unlink(temporary)
        raise


def remove_record_of(project_root, pid):
    """Remove the checkout's record only while it still names pid."""
    directory = state_dir(project_root, create=False)
    if directory is None:
        return
    path = directory / RECORD
    seen = snapshot(path)
    if seen is None or seen[0] != 'file':
        return
    try:
        record = parse(seen[1])
    except (ValueError, UnicodeDecodeError, RecursionError):
        return
    if record['pid'] == pid:
        discard_stale(path, seen)


def close_inherited_descriptors():
    """Close every descriptor above stderr, so the server holds no pipe or lock of its caller."""
    try:
        descriptors = [int(name) for name in os.listdir('/proc/self/fd')]
    except OSError:
        descriptors = range(3, 1024)
    for descriptor in descriptors:
        if descriptor > 2:
            try:
                os.close(descriptor)
            except OSError:
                pass


def accepts(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.2):
            return True
    except OSError:
        return False


def detach_wait():
    try:
        wait = float(os.environ.get('OASIS_DETACH_WAIT', ''))
    except ValueError:
        return DETACH_WAIT
    return wait if math.isfinite(wait) and wait >= 0 else DETACH_WAIT


def tail(path, offset, count):
    """The last count lines written to path after offset."""
    try:
        with open(path, 'rb') as stream:
            stream.seek(offset)
            text = stream.read().decode('utf-8', 'replace')
    except OSError:
        return []
    return text.splitlines()[-count:]


def detach(project_root, port, log, odoo_bin, python, arguments):
    """Start Odoo in a new session writing to log, record it and report it (see the docstring)."""
    try:
        descriptor = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600)
    except OSError as exc:
        raise StateError(f'Cannot open the server log: {log}') from exc
    offset = os.fstat(descriptor).st_size
    pid = os.fork()
    if pid == 0:  # pragma: no cover - the child execs Odoo or exits
        try:
            os.setsid()
            null = os.open(os.devnull, os.O_RDONLY)
            os.dup2(null, 0)
            os.dup2(descriptor, 1)
            os.dup2(descriptor, 2)
            close_inherited_descriptors()
            os.execv(python, [python, odoo_bin, *arguments])
        except BaseException as exc:  # noqa: BLE001 - report anything, never return into the parent
            try:
                os.write(2, f'Cannot start Odoo: {exc}\n'.encode())
            finally:
                os._exit(127)
    os.close(descriptor)
    try:
        write_record(project_root, pid, port, odoo_bin, python)
    except BaseException:
        # An unrecorded server could never be stopped with stop: end it.
        os.kill(pid, signal.SIGTERM)
        os.waitpid(pid, 0)
        raise
    deadline = time.monotonic() + detach_wait()
    while True:
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            remove_record_of(project_root, pid)
            print(f'Odoo exited at once with status {os.waitstatus_to_exitcode(status)}; the end of {log}:',
                  file=sys.stderr)
            for line in tail(log, offset, DETACH_TAIL):
                print(line, file=sys.stderr)
            return 1
        if accepts(port) or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    print(f'pid={pid} port={port} log={log}')
    return 0


def stop(project_root):
    record = live_record(project_root)
    if record is None:
        print('No Odoo server running for this checkout.')
        return 0
    pid, port = record['pid'], record['port']
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + STOP_TIMEOUT
    while is_live(record):
        if time.monotonic() >= deadline:
            print(f'Odoo did not stop within {STOP_TIMEOUT} s: pid {pid}, port {port}.', file=sys.stderr)
            return 1
        time.sleep(0.1)
    read_live(checkout_dir(project_root))
    print(f'Stopped Odoo for this checkout: pid {pid}, port {port}.')
    return 0


def others(project_root):
    """Live records of the other checkouts under the same user root."""
    root = user_root()
    if not check_dir(root):
        return []
    own = checkout_dir(project_root).name
    found = []
    for directory in sorted(root.iterdir()):
        if directory.name == own:
            continue
        try:
            if not check_dir(directory):
                continue
            record = read_live(directory)
        except StateError:
            continue
        if record is not None:
            found.append(record)
    return found


def run_database_name(namespace, module, token=None):
    """A new disposable database name for module under namespace (prefix and slug_)."""
    suffix = f'_r{token or secrets.token_hex(3)}'
    name = f'{namespace}{module}{suffix}'
    if len(name.encode()) <= RUN_NAME_BYTES:
        return name
    # The module part becomes its first N bytes, '_' and 4 hex of sha256(module).
    room = RUN_NAME_BYTES - len(namespace.encode()) - len(suffix) - 5
    if room < 1:
        raise RunError('Test prefix and checkout slug leave no room for a disposable database name: '
                       f'{namespace}')
    head = module.encode()[:room].decode('utf-8', 'ignore')
    digest = hashlib.sha256(module.encode()).hexdigest()[:4]
    return f'{namespace}{head}_{digest}{suffix}'


def is_run_database(name):
    """True for a name with the disposable run suffix (_r<6 hex>, optionally _update)."""
    return RUN_DATABASE.fullmatch(name) is not None


def lock_name(database):
    if not DATABASE.fullmatch(database or ''):
        raise RunError(f'Invalid run database name: {database}')
    return f'{database}.json'


def runs_dir(project_root, create):
    """The checkout's runs/ directory, or None when it does not exist and create is False."""
    directory = state_dir(project_root, create)
    if directory is None:
        return None
    runs = directory / RUNS
    if create:
        ensure_dir(runs)
    elif not check_dir(runs):
        return None
    return runs


def write_run_lock(project_root, database, pid):
    """Record that pid runs the disposable database: created exclusively, 0600, fsynced.

    An existing lock of that database (live or stale, or anything else at that path) raises
    RunLocked and is left as it is.
    """
    name = lock_name(database)
    argv = command_line(pid)
    if argv is None:
        raise RunError(f'No process of this user with pid {pid}.')
    directory = runs_dir(project_root, create=True)
    record = {'pid': pid, 'started_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'database': database, 'project_root': os.path.realpath(project_root), 'argv': argv}
    path = directory / name
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError as exc:
        raise RunLocked(f'Disposable test database is locked: {database}') from exc
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        # Only this call created the file: a half-written lock is removed.
        path.unlink(missing_ok=True)
        raise


def remove_run_lock(project_root, database, pid=None):
    """Remove the checkout's lock of database; with pid, only a lock that pid holds."""
    name = lock_name(database)
    directory = runs_dir(project_root, create=False)
    if directory is None:
        return
    path = directory / name
    if pid is not None:
        try:
            seen = snapshot(path)
            record = lock_record(seen, database)
            if record is not None and record['pid'] == pid:
                discard_stale(path, seen)
        except OSError as exc:
            raise StateError(f'Cannot remove run lock: {path}') from exc
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def run_lock_owned(project_root, database, pid):
    """True when this checkout's lock of database is live and held by pid."""
    name = lock_name(database)
    directory = runs_dir(project_root, create=False)
    if directory is None:
        return False
    try:
        record = lock_record(snapshot(directory / name), database)
    except OSError:
        return False
    return record is not None and record['pid'] == pid and command_line(pid) == record['argv']


def parse_run_lock(raw):
    data = json.loads(raw.decode('utf-8'))
    if not isinstance(data, dict):
        raise ValueError('invalid lock')
    pid, argv = data.get('pid'), data.get('argv')
    if (not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0
            or not isinstance(data.get('database'), str) or not isinstance(argv, list)
            or not argv or not all(isinstance(part, str) for part in argv)):
        raise ValueError('invalid lock')
    return data


def lock_record(seen, database):
    """The parsed lock of a snapshot for database, or None (missing, not a file, invalid)."""
    if seen is None or seen[0] != 'file':
        return None
    try:
        record = parse_run_lock(seen[1])
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None
    return record if record['database'] == database else None


def run_locks():
    """(path, snapshot, record or None, live) for every run lock of every checkout of this user."""
    root = user_root()
    if not check_dir(root):
        return []
    found = []
    for directory in sorted(root.iterdir()):
        try:
            if not check_dir(directory) or not check_dir(directory / RUNS):
                continue
            paths = sorted((directory / RUNS).glob('*.json'))
        except (StateError, OSError):
            continue
        for path in paths:
            try:
                seen = snapshot(path)
            except OSError:
                continue
            record = lock_record(seen, path.stem)
            live = record is not None and command_line(record['pid']) == record['argv']
            found.append((path, seen, record, live))
    return found


def live_run_databases():
    """Databases with a live run lock in any checkout of this user."""
    return {record['database'] for _path, _seen, record, live in run_locks() if live}


def discard_stale_run_locks(database):
    """Remove every stale lock of database, only if the file still holds what was judged stale."""
    for path, seen, _record, live in run_locks():
        if path.stem == database and not live and seen is not None:
            discard_stale(path, seen)


def compose_lock(compose_file):
    """The lock file of compose_file in the user root, created 0600 when missing."""
    root = user_root()
    ensure_dir(root)
    digest = hashlib.sha256(os.path.realpath(compose_file).encode()).hexdigest()[:16]
    path = root / f'compose-{digest}.lock'
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    except OSError as exc:
        raise StateError(f'Cannot open the compose lock: {path}') from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise StateError(f'Compose lock is not a regular file of the current user: {path}')
        if stat.S_IMODE(info.st_mode) != 0o600:
            os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)
    return path


def bind_addresses(interface):
    """The addresses Odoo would bind (its http_interface, default all IPv4) plus loopback."""
    host = interface or '0.0.0.0'
    addresses = []
    try:
        for family, kind, proto, _name, address in socket.getaddrinfo(
                host, None, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE):
            addresses.append((family, kind, proto, address[0]))
    except socket.gaierror:
        pass
    addresses.append((socket.AF_INET, socket.SOCK_STREAM, 0, '127.0.0.1'))
    return addresses


def port_is_free(interface, port):
    for family, kind, proto, host in bind_addresses(interface):
        with socket.socket(family, kind, proto) as probe:
            # Odoo's server sets SO_REUSEADDR too: TIME_WAIT sockets do not make a port busy.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
            except OSError as exc:
                if exc.errno == errno.EADDRINUSE:
                    return False
                if exc.errno != errno.EADDRNOTAVAIL:
                    reason = os.strerror(exc.errno) if exc.errno else str(exc)
                    raise PortError(f'Cannot bind port {port}: {reason[:1].lower()}{reason[1:]}.') from exc
    return True


def free_port(interface, first, last, excluded):
    for port in range(max(first, 1), min(last, 65535) + 1):
        if port not in excluded and port_is_free(interface, port):
            return port
    return None


def ephemeral_port(excluded=()):
    # The system may hand out an excluded port again; ask until it does not.
    for _ in range(100):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        if port not in excluded:
            return port
    raise PortError('Cannot find a free ephemeral port.')


def integer(value):
    if not value.isdigit():
        raise ValueError(value)
    return int(value)


def main(argv):
    command, args = (argv[0], argv[1:]) if argv else ('', [])
    try:
        if command == 'show' and len(args) == 1:
            record = live_record(args[0])
            if record is not None:
                print(f"pid={record['pid']} port={record['port']}")
            return 0
        if command == 'record' and len(args) in (4, 5):
            write_record(args[0], integer(args[1]), integer(args[2]), *args[3:])
            return 0
        if command == 'stop' and len(args) == 1:
            return stop(args[0])
        if command == 'detach' and len(args) >= 6 and args[5] == '--':
            return detach(args[0], integer(args[1]), args[2], args[3], args[4], args[6:])
        if command == 'others' and len(args) == 1:
            for record in others(args[0]):
                print(f"{record['project_root']} (port {record['port']}, pid {record['pid']})")
            return 0
        if command == 'port' and len(args) >= 3:
            port = free_port(args[0], integer(args[1]), integer(args[2]), {integer(a) for a in args[3:]})
            if port is None:
                return 1
            print(port)
            return 0
        if command == 'ephemeral-port':
            print(ephemeral_port({integer(a) for a in args}))
            return 0
        if command == 'run-name' and len(args) == 2:
            print(run_database_name(args[0], args[1]))
            return 0
        if command == 'run-lock' and len(args) == 3:
            write_run_lock(args[0], args[1], integer(args[2]))
            return 0
        if command == 'run-unlock' and len(args) == 2:
            remove_run_lock(args[0], args[1])
            return 0
        if command == 'run-owned' and len(args) == 3:
            return 0 if run_lock_owned(args[0], args[1], integer(args[2])) else 1
        if command == 'compose-lock' and len(args) == 1:
            print(compose_lock(args[0]))
            return 0
    except RunLocked as exc:
        print(exc, file=sys.stderr)
        return 2
    except (StateError, RunError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    except PortError as exc:
        print(exc, file=sys.stderr)
        return 2
    except ValueError:
        pass
    print('ERROR: Usage: runtime_state.py show|record|detach|stop|others|port|ephemeral-port|run-name|'
          'run-lock|run-unlock|run-owned|compose-lock ...', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
