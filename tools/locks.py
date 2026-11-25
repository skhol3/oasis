"""The dependency locks of a requirements directory: why they need compiling, and their fingerprint.

bootstrap (tools/bootstrap) compiles runtime.txt and dev.txt from runtime.in and dev.in when
they are missing or stale, as docs/new-workspace.md does by hand, then writes lock.sha256 here.

  locks.py state <requirements dir> <project root>
      For locks that common.sh dependency_locks_current did not accept, prints one word:
      missing  runtime.txt, dev.txt or lock.sha256 does not exist;
      stale    lock.sha256 does not record the current runtime.in and dev.in (an input
               changed, or the file cannot be read): compiling again brings them up to date;
      edited   it records them, so a lock (or another entry) was changed by hand: bootstrap
               refuses, it never overwrites such a lock.
      Entries resolve from the requirements directory, then, for a legacy lock, from the
      project root, like dependency_locks_current.
  locks.py fingerprint <requirements dir>
      Writes lock.sha256 exactly as `sha256sum runtime.in runtime.txt dev.in dev.txt >
      lock.sha256` run in that directory would.

Neither command ever writes an input (.in) file.
"""
import hashlib
import os
import re
import sys
from pathlib import Path

INPUTS = ('runtime.in', 'dev.in')
LOCKS = ('runtime.txt', 'dev.txt')
FILES = ('runtime.in', 'runtime.txt', 'dev.in', 'dev.txt')
FINGERPRINT = 'lock.sha256'
# sha256sum's line: the digest, a space, then a space (text) or '*' (binary), then the name.
ENTRY = re.compile(r'([0-9a-fA-F]{64}) [ *](.+)')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def recorded(requirements, root):
    """The digest lock.sha256 records for each file it names, keyed by its resolved path."""
    entries = {}
    try:
        text = (requirements / FINGERPRINT).read_text()
    except (OSError, UnicodeDecodeError):
        return entries
    for line in text.splitlines():
        match = ENTRY.fullmatch(line)
        if not match:
            continue
        for base in (requirements, root):
            entries.setdefault(os.path.realpath(base / match.group(2)), match.group(1).lower())
    return entries


def state(requirements, root):
    if any(not (requirements / name).is_file() for name in (*LOCKS, FINGERPRINT)):
        return 'missing'
    entries = recorded(requirements, root)
    for name in INPUTS:
        if entries.get(os.path.realpath(requirements / name)) != digest(requirements / name):
            return 'stale'
    return 'edited'


def fingerprint(requirements):
    text = ''.join(f'{digest(requirements / name)}  {name}\n' for name in FILES)
    (requirements / FINGERPRINT).write_text(text)


def main(argv):
    if len(argv) == 3 and argv[0] == 'state':
        print(state(Path(argv[1]), Path(argv[2])))
        return 0
    if len(argv) == 2 and argv[0] == 'fingerprint':
        fingerprint(Path(argv[1]))
        return 0
    print('Usage: locks.py state <requirements dir> <project root> | fingerprint <requirements dir>',
          file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
