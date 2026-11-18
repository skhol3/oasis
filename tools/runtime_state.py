#!/usr/bin/env python3
"""Per-checkout runtime state of the Odoo server that `start` runs, and port probes (internal CLI).

Usage:
  runtime_state.py show <project_root>       pid=<pid> port=<port> when a live server is recorded
  runtime_state.py record <project_root> <pid> <port> <odoo_bin>
  runtime_state.py stop <project_root>       SIGTERM this checkout's server, wait up to 20 s
  runtime_state.py others <project_root>     live servers of the other checkouts, one per line
  runtime_state.py port <interface> <first> <last> [<excluded>...]
                                             first port in [first, last] free on the interface
                                             (exit 1 when none; exit 2 and `Cannot bind port
                                             <p>: <reason>.` when a bind fails otherwise)
  runtime_state.py ephemeral-port            a free ephemeral port on 127.0.0.1

State lives in ${XDG_RUNTIME_DIR, or /tmp}/oasis-<uid>/<first 16 hex of sha256(realpath
project_root)>/server.json ({pid, port, started_at, project_root, odoo_bin}); both directories
are 0700 and refused when they are symlinks, not directories or owned by another user. Never
inside a repository or a shared directory. A record is live while its pid is a process of this
user whose command line (/proc, Linux) is the Odoo launch: argv[1] is the recorded odoo-bin
(argv[0] a python interpreter) or argv[0] is odoo-bin. Within GRACE seconds of started_at any
process of the pid is live (start writes the record before it execs Odoo). A stale or invalid
record is removed when read, only if the file still holds what was read.
"""
from datetime import datetime, timezone
import errno
import hashlib
import math
import json
import os
from pathlib import Path
import signal
import socket
import stat
import sys
import tempfile
import time

RECORD = 'server.json'
STOP_TIMEOUT = 20
GRACE = 10


class StateError(Exception):
    """An unsafe or unreadable state directory; the message names the path."""


class PortError(Exception):
    """A port that cannot be probed for a reason other than being in use."""


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


def is_odoo_launch(argv, odoo_bin):
    names = {odoo_bin, os.path.realpath(odoo_bin)}
    if argv[0] in names:
        return True
    return (len(argv) > 1 and argv[1] in names
            and os.path.basename(argv[0]).startswith('python'))


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
    return is_odoo_launch(argv, record['odoo_bin']) or in_grace(record)


def parse(raw):
    data = json.loads(raw.decode('utf-8'))
    if not isinstance(data, dict):
        raise ValueError('invalid record')
    pid, port = data.get('pid'), data.get('port')
    if (not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 or not isinstance(port, int)
            or isinstance(port, bool) or not isinstance(data.get('odoo_bin'), str)
            or not isinstance(data.get('project_root'), str)):
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


def write_record(project_root, pid, port, odoo_bin):
    directory = state_dir(project_root, create=True)
    record = {'pid': pid, 'port': port,
              'started_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'project_root': os.path.realpath(project_root), 'odoo_bin': odoo_bin}
    descriptor, temporary = tempfile.mkstemp(prefix='.server-', dir=directory)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(record, stream)
        os.replace(temporary, directory / RECORD)
    except BaseException:
        os.unlink(temporary)
        raise


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


def ephemeral_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


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
        if command == 'record' and len(args) == 4:
            write_record(args[0], integer(args[1]), integer(args[2]), args[3])
            return 0
        if command == 'stop' and len(args) == 1:
            return stop(args[0])
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
        if command == 'ephemeral-port' and not args:
            print(ephemeral_port())
            return 0
    except StateError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    except PortError as exc:
        print(exc, file=sys.stderr)
        return 2
    except ValueError:
        pass
    print('ERROR: Usage: runtime_state.py show|record|stop|others|port|ephemeral-port ...', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
