#!/usr/bin/env python3
"""Per-checkout runtime state of the Odoo server that `start` runs, and port probes (internal CLI).

Usage:
  runtime_state.py show <project_root>       pid=<pid> port=<port> when a live server is recorded
  runtime_state.py database <project_root>   the database the live server was started with, if any
  runtime_state.py record <project_root> <pid> <port> <odoo_bin> [<python> [<database>]]
  runtime_state.py detach <project_root> <port> <log> <odoo_bin> <python> <interface> <database> --
                          <odoo argument>...
                                             start <python> <odoo_bin> <arguments> in a new
                                             session with stdin from /dev/null and stdout and
                                             stderr appended to <log> (0600), record it, and
                                             print pid=<pid> port=<port> log=<log> once it
                                             listens on <interface> (see below)
  runtime_state.py stop <project_root> [--force] [--program oasis|odoo19]
                                             SIGTERM this checkout's server, wait up to 20 s;
                                             with --force, then SIGKILL its session (see below);
                                             the program the timeout message names (oasis)
  runtime_state.py others <project_root>     live servers of the other checkouts, one per line
  runtime_state.py servers <project_root>    live servers of every checkout of the project's git
                                             repository, one `<checkout>: pid <pid>, port <port>[,
                                             database <database>][ (this checkout)]` line each
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
  runtime_state.py remember <project_root> <action id> <answers JSON>
                                             record the menu action that just ran (see below)

State lives in ${XDG_RUNTIME_DIR, or /tmp}/oasis-<uid>/<first 16 hex of sha256(realpath
project_root)>/server.json ({pid, port, started_at, project_root, odoo_bin, python, database}, the
last two optional: database is the one start was given with -d or --database); both directories
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
returning as soon as <interface>:<port> accepts connections (the address Odoo binds: start passes
--http-interface or the odoo.conf http_interface; 127.0.0.1 for none, 0.0.0.0 or ::). One that
exits meanwhile has its record removed, and the command prints `Odoo exited at once with status
<n>; the end of <log>:` and the last DETACH_TAIL lines it wrote, then exits 1. One that does not
listen in time is stopped (SIGTERM to its session, SIGKILL after STOP_GRACE seconds), its record
removed, and the command prints `Odoo did not listen on <host>:<port> within <s> s and was stopped;
the end of <log>:` and those lines, then exits 1.

The processes of a server are the recorded process, the members of the session and of the process
group it leads, and their descendants (of this user, started after it; never this process or its
ancestors). Stopping a detached server that does not listen sends SIGTERM to its session and, after
STOP_GRACE seconds (OASIS_STOP_GRACE, for the tests only), SIGKILL to every one of them still
running, so members that ignore SIGTERM or outlive the server do not stay. SIGKILL goes to the
recorded process first and, once it has ended (or KILL_WAIT seconds later), to the others; the
processes are then scanned again, and new ones killed, until a scan finds none (at most KILL_ROUNDS
rounds), so a prefork master cannot leave a worker it started meanwhile. `stop` sends SIGTERM to
the server and waits STOP_TIMEOUT seconds (OASIS_STOP_TIMEOUT, for the tests only) for it to end
(exit 1 when it does not, with `Odoo did not stop within <s> s: pid <pid>, port <port>; run
<program> stop --force.`); `stop --force` waits for it and its processes, then sends SIGKILL to
every one still running and removes the record once the server is gone. When the server's
/proc/<pid>/stat cannot be read, its other processes are unknown: only the server gets SIGKILL.

Repository servers (status): the live records, of this checkout and the others, whose checkout is
one of the worktrees `git worktree list` names for the project root, or inside one. When git
cannot list them (missing, failing, timed out), `servers` exits 2 with `ERROR: <reason>` instead
of listing none.

Menu memory (oasis menu and the Gentle Shell panel): `menu.json` (0600) in the same private state
directory, {last: {action, answers}, database}: the last action run from either menu with its
answers (an object of short strings and booleans: module, database, port and dev mode names, never
a secret; the menus skip user-run and terminal-only actions), and the last database the start /
restart flow (server.run) used. It survives stop, which removes only server.json. A file that is
missing, not a regular file or invalid reads as nothing remembered; it is replaced, never written
through a symlink.

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
import subprocess
import sys
import tempfile
import time

RECORD = 'server.json'
MENU = 'menu.json'
MENU_BYTES = 64 * 1024
MENU_ACTION = re.compile(r'[a-z]+\.[a-z_]+')
MENU_ANSWER = re.compile(r'[a-z_]+')
MENU_VALUE = re.compile(r'[^\x00-\x1f\x7f]{0,200}')
RUN_ACTION = 'server.run'
STOP_TIMEOUT = 20
GRACE = 10
DETACH_WAIT = 30.0
DETACH_TAIL = 20
STOP_GRACE = 5
# How long stop --force waits for the processes it sent SIGKILL to.
KILL_WAIT = 5
# How many times the processes of a server are scanned again for new ones after SIGKILL.
KILL_ROUNDS = 10
GIT_TIMEOUT = 20
# Addresses that mean every interface: the probe connects to the loopback instead.
ANY_INTERFACE = {'', '0.0.0.0', '::'}
RUNS = 'runs'
RUN_NAME_BYTES = 56
RUN_DATABASE = re.compile(r'[A-Za-z0-9_]+_r[0-9a-f]{6}(?:_update)?')
DATABASE = re.compile(r'[A-Za-z0-9_]+')


class StateError(Exception):
    """An unsafe or unreadable state directory; the message names the path."""


class PortError(Exception):
    """A port that cannot be probed for a reason other than being in use."""


class GitError(Exception):
    """git cannot list the worktrees of the repository; the message says why."""


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


def write_record(project_root, pid, port, odoo_bin, python=None, database=None):
    directory = state_dir(project_root, create=True)
    record = {'pid': pid, 'port': port,
              'started_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'project_root': os.path.realpath(project_root), 'odoo_bin': odoo_bin}
    if python:
        record['python'] = python
    if database:
        record['database'] = database
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


def probe_host(interface):
    """The address a detached server is probed on: its HTTP interface, the loopback for any."""
    interface = interface.strip()
    return '127.0.0.1' if interface in ANY_INTERFACE else interface


def accepts(host, port):
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


def process_info(pid):
    """(state, ppid, pgid, sid, start time) of a process of this user (/proc/<pid>/stat), or None."""
    try:
        if os.stat(f'/proc/{pid}').st_uid != os.getuid():
            return None
        with open(f'/proc/{pid}/stat', 'rb') as stream:
            raw = stream.read()
        # The command name may hold spaces and parentheses: the fields follow the last `)`.
        fields = raw[raw.rindex(b')') + 2:].split()
        return fields[0].decode(), int(fields[1]), int(fields[2]), int(fields[3]), int(fields[19])
    except (OSError, ValueError, IndexError):
        return None


def server_processes(leader, started):
    """{pid: start time} of the server's processes (see the docstring); started is the start time
    of the leader, so a reused pid, or a process older than the server, never counts."""
    table = {}
    for name in os.listdir('/proc'):
        if name.isdigit():
            info = process_info(int(name))
            if info is not None:
                table[int(name)] = info
    current = table.get(leader)
    if current is not None and current[4] != started:
        return {}
    newer = {pid: info for pid, info in table.items() if info[4] >= started}
    members = {pid for pid, info in newer.items() if leader in (pid, info[2], info[3])}
    while True:
        children = {pid for pid, info in newer.items() if info[1] in members} - members
        if not children:
            break
        members |= children
    ancestor, seen = os.getpid(), set()
    while ancestor > 0 and ancestor not in seen:
        seen.add(ancestor)
        members.discard(ancestor)
        info = table.get(ancestor)
        ancestor = info[1] if info else 0
    return {pid: table[pid][4] for pid in members}


def running(processes):
    """The processes still running: the same start time, and not a zombie."""
    left = {}
    for pid, started in processes.items():
        info = process_info(pid)
        if info is not None and info[4] == started and info[0] != 'Z':
            left[pid] = started
    return left


def wait_ended(processes, wait):
    """Wait up to wait seconds until none of the processes runs; the ones still running."""
    deadline = time.monotonic() + wait
    left = running(processes)
    while left and time.monotonic() < deadline:
        time.sleep(0.05)
        left = running(left)
    return left


def kill_all(processes, leader, started):
    """SIGKILL the processes that still run, the leader first: once it has ended (or KILL_WAIT
    seconds later) it cannot start a replacement for a worker it sees die. After each round the
    leader's processes (started is its start time) are scanned again and the new ones killed,
    until a scan finds none, at most KILL_ROUNDS rounds. Returns (every process seen, the pids
    sent SIGKILL)."""
    known, killed = dict(processes), set()
    for _ in range(KILL_ROUNDS):
        targets = [pid for pid in running(known) if pid not in killed]
        if not targets:
            break
        for pid in sorted(targets, key=lambda pid: pid != leader):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            killed.add(pid)
            if pid == leader:
                wait_ended({leader: known[leader]}, KILL_WAIT)
        known.update(server_processes(leader, started))
    return known, killed


def seconds(name, default):
    """A wait in seconds from the environment variable name (for the tests only), else default."""
    try:
        wait = float(os.environ.get(name, ''))
    except ValueError:
        return default
    return wait if math.isfinite(wait) and wait >= 0 else default


def end_session(pid):
    """Stop the detached server and whatever it started in its session, then reap it.

    SIGTERM to the session, then SIGKILL to every process of the server still running after the
    grace: the leader when it ignores SIGTERM, and members that ignore it or outlive the leader.
    The leader, a child of this process, is reaped only at the end, so its pid (the members'
    session id) cannot be reused meanwhile.
    """
    info = process_info(pid)
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        # Not a session leader yet (setsid still to run): the process alone.
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if info is not None:
        deadline = time.monotonic() + seconds('OASIS_STOP_GRACE', STOP_GRACE)
        while running(server_processes(pid, info[4])) and time.monotonic() < deadline:
            time.sleep(0.05)
        kill_all(server_processes(pid, info[4]), pid, info[4])
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    os.waitpid(pid, 0)


def detach_wait():
    return seconds('OASIS_DETACH_WAIT', DETACH_WAIT)


def tail(path, offset, count):
    """The last count lines written to path after offset."""
    try:
        with open(path, 'rb') as stream:
            stream.seek(offset)
            text = stream.read().decode('utf-8', 'replace')
    except OSError:
        return []
    return text.splitlines()[-count:]


def detach(project_root, port, log, odoo_bin, python, interface, arguments, database=None):
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
        write_record(project_root, pid, port, odoo_bin, python, database)
    except BaseException:
        # An unrecorded server could never be stopped with stop: end it.
        os.kill(pid, signal.SIGTERM)
        os.waitpid(pid, 0)
        raise
    host = probe_host(interface)
    wait = detach_wait()
    deadline = time.monotonic() + wait
    while True:
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            remove_record_of(project_root, pid)
            print(f'Odoo exited at once with status {os.waitstatus_to_exitcode(status)}; the end of {log}:',
                  file=sys.stderr)
            break
        if accepts(host, port):
            print(f'pid={pid} port={port} log={log}')
            return 0
        if time.monotonic() >= deadline:
            # Nothing listens: a server that cannot be reached is not started; never leave it unrecorded.
            end_session(pid)
            remove_record_of(project_root, pid)
            address = f'[{host}]' if ':' in host else host
            print(f'Odoo did not listen on {address}:{port} within {wait:g} s and was stopped; the end of {log}:',
                  file=sys.stderr)
            break
        time.sleep(0.05)
    for line in tail(log, offset, DETACH_TAIL):
        print(line, file=sys.stderr)
    return 1


def recorded_database(record):
    """The database a record names, when it is a valid name; else None."""
    database = record.get('database')
    return database if isinstance(database, str) and DATABASE.fullmatch(database) else None


def stop(project_root, force=False, program='oasis'):
    """SIGTERM the checkout's server and wait for it; with force, SIGKILL what is left (docstring)."""
    record = live_record(project_root)
    if record is None:
        print('No Odoo server running for this checkout.')
        return 0
    pid, port = record['pid'], record['port']
    info = process_info(pid) if force else None
    # Taken before SIGTERM: the descendants of the server, which may outlive it.
    processes = server_processes(pid, info[4]) if info is not None else {}
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    timeout = seconds('OASIS_STOP_TIMEOUT', STOP_TIMEOUT)
    deadline = time.monotonic() + timeout
    left = {}
    while True:
        if info is not None:
            processes.update(server_processes(pid, info[4]))
            left = running(processes)
        if not is_live(record) and not left:
            break
        if time.monotonic() >= deadline:
            if not force:
                print(f'Odoo did not stop within {timeout:g} s: pid {pid}, port {port}; run {program} stop --force.',
                      file=sys.stderr)
                return 1
            break
        time.sleep(0.1)
    if not left and not is_live(record):
        read_live(checkout_dir(project_root))
        print(f'Stopped Odoo for this checkout: pid {pid}, port {port}.')
        return 0
    if info is None:
        # Its /proc/<pid>/stat could not be read: its other processes are unknown, the server alone.
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + KILL_WAIT
        while is_live(record) and time.monotonic() < deadline:
            time.sleep(0.05)
        if is_live(record):
            print(f'Odoo is still running after SIGKILL: pid {pid}, port {port}.', file=sys.stderr)
            return 1
        remove_record_of(project_root, pid)
        print(f'Killed Odoo for this checkout after {timeout:g} s (SIGKILL; its other processes could not be '
              f'read): pid {pid}, port {port}.')
        return 0
    known, killed = kill_all(processes, pid, info[4])
    if pid in wait_ended(known, KILL_WAIT):
        print(f'Odoo is still running after SIGKILL: pid {pid}, port {port}.', file=sys.stderr)
        return 1
    remove_record_of(project_root, pid)
    if pid in left:
        print(f'Killed Odoo for this checkout after {timeout:g} s (SIGKILL to its session): pid {pid}, '
              f'port {port}.')
    else:
        print(f'Stopped Odoo for this checkout: pid {pid}, port {port}; killed {len(killed - {pid})} '
              'process(es) of its session that outlived it.')
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


def worktrees(project_root):
    """The real paths of the worktrees of project_root's git repository; GitError when git cannot
    list them (missing, failing or timed out), so a failure never reads as no worktrees."""
    env = {key: value for key, value in os.environ.items()
           if key not in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_INDEX_FILE')}
    try:
        result = subprocess.run(['git', '-C', str(project_root), 'worktree', 'list', '--porcelain'],
                                capture_output=True, text=True, env=env, timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise GitError(f'git worktree list did not finish within {GIT_TIMEOUT} s') from exc
    except (OSError, subprocess.SubprocessError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else str(exc)
        raise GitError(f'Cannot run git worktree list: {reason}') from exc
    if result.returncode != 0:
        lines = [line.strip() for line in result.stderr.splitlines() if line.strip()]
        if lines:
            raise GitError(f'git worktree list failed: {lines[-1]}')
        raise GitError(f'git worktree list exited with status {result.returncode}')
    return [os.path.realpath(line[len('worktree '):]) for line in result.stdout.splitlines()
            if line.startswith('worktree ')]


def repository_servers(project_root):
    """(record, own) for the live servers of every checkout of the repository, by checkout path."""
    trees = worktrees(project_root)
    own = live_record(project_root)
    found = [(record, False) for record in others(project_root)] + ([(own, True)] if own else [])
    inside = [(record, mine) for record, mine in found
              if any(record['project_root'] == tree or record['project_root'].startswith(tree.rstrip('/') + '/')
                     for tree in trees)]
    return sorted(inside, key=lambda item: item[0]['project_root'])


def server_line(record, own):
    database = recorded_database(record)
    shown = f', database {database}' if database else ''
    return (f"{record['project_root']}: pid {record['pid']}, port {record['port']}{shown}"
            + (' (this checkout)' if own else ''))


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


class MenuError(ValueError):
    """Not a menu action id with answers (remember)."""


def valid_menu_answers(answers):
    return (isinstance(answers, dict) and len(answers) <= 20
            and all(isinstance(key, str) and MENU_ANSWER.fullmatch(key)
                    and (isinstance(value, bool) or isinstance(value, str) and MENU_VALUE.fullmatch(value))
                    for key, value in answers.items()))


def read_menu(project_root):
    """{last: {action, answers} or None, database: str or None} remembered for the checkout."""
    empty = {'last': None, 'database': None}
    directory = state_dir(project_root, create=False)
    if directory is None:
        return empty
    try:
        descriptor = os.open(directory / MENU, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return empty
    try:
        with os.fdopen(descriptor, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return empty
            data = json.loads(stream.read(MENU_BYTES + 1).decode('utf-8'))
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        return empty
    if not isinstance(data, dict):
        return empty
    last, database = data.get('last'), data.get('database')
    if not (isinstance(last, dict) and isinstance(last.get('action'), str) and MENU_ACTION.fullmatch(last['action'])
            and valid_menu_answers(last.get('answers'))):
        last = None
    else:
        last = {'action': last['action'], 'answers': last['answers']}
    if not (isinstance(database, str) and DATABASE.fullmatch(database)):
        database = None
    if last is None and data.get('last') is not None or database is None and data.get('database') is not None:
        return empty
    return {'last': last, 'database': database}


def remember(project_root, action, answers):
    """Record the menu action that ran and its answers; the start / restart flow's database too."""
    if not (isinstance(action, str) and MENU_ACTION.fullmatch(action)) or not valid_menu_answers(answers):
        raise MenuError('Invalid menu action or answers.')
    database = read_menu(project_root)['database']
    chosen = answers.get('database')
    if action == RUN_ACTION and isinstance(chosen, str) and DATABASE.fullmatch(chosen):
        database = chosen
    content = {'last': {'action': action, 'answers': answers}}
    if database:
        content['database'] = database
    directory = state_dir(project_root, create=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.menu-', dir=directory)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(content, stream)
        # os.replace renames over the path itself: a symlink there is replaced, never followed.
        os.replace(temporary, directory / MENU)
    except BaseException:
        os.unlink(temporary)
        raise


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
        if command == 'record' and len(args) in (4, 5, 6):
            write_record(args[0], integer(args[1]), integer(args[2]), *args[3:])
            return 0
        if command == 'database' and len(args) == 1:
            record = live_record(args[0])
            if record is not None and recorded_database(record):
                print(recorded_database(record))
            return 0
        if command == 'stop' and args:
            rest, program = args[1:], 'oasis'
            if len(rest) >= 2 and rest[-2] == '--program' and rest[-1] in ('oasis', 'odoo19'):
                rest, program = rest[:-2], rest[-1]
            if rest in ([], ['--force']):
                return stop(args[0], force=bool(rest), program=program)
        if command == 'detach' and len(args) >= 8 and args[7] == '--':
            return detach(args[0], integer(args[1]), args[2], args[3], args[4], args[5], args[8:], args[6])
        if command == 'others' and len(args) == 1:
            for record in others(args[0]):
                print(f"{record['project_root']} (port {record['port']}, pid {record['pid']})")
            return 0
        if command == 'servers' and len(args) == 1:
            for record, own in repository_servers(args[0]):
                print(server_line(record, own))
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
        if command == 'remember' and len(args) == 3:
            try:
                answers = json.loads(args[2])
            except (ValueError, RecursionError):
                answers = None
            remember(args[0], args[1], answers)
            return 0
    except MenuError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    except RunLocked as exc:
        print(exc, file=sys.stderr)
        return 2
    except (StateError, RunError, GitError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    except PortError as exc:
        print(exc, file=sys.stderr)
        return 2
    except ValueError:
        pass
    print('ERROR: Usage: runtime_state.py show|database|record|detach|stop|others|servers|port|ephemeral-port|run-name|'
          'run-lock|run-unlock|run-owned|compose-lock|remember ...', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
