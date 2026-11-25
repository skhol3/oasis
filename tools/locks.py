"""The dependency locks of a requirements directory: why they need compiling, their compilation
and their fingerprint.

bootstrap (tools/bootstrap) and setup (tools/setup.py) compile runtime.txt and dev.txt from
runtime.in and dev.in when they are missing or stale, as docs/new-workspace.md does by hand, with
the same code here (compile), which then writes lock.sha256.

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
  locks.py compile <requirements dir> <python> <command to rerun>
      Runs `uv pip compile --python-version <python> <input> -o <lock>` in that directory for
      runtime.in, then dev.in (dev.in constrains itself with -c runtime.txt; uv's echo of the lock is
      dropped), then fingerprint. A failed compile stops before lock.sha256 (exit 2), naming the
      input and the command to run again.

Neither command ever writes an input (.in) file.
"""
import hashlib
import os
import re
import subprocess
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


def matches(line, base):
    """Whether one lock.sha256 line names a file, relative to base, with its digest."""
    match = ENTRY.fullmatch(line)
    if not match:
        return False
    try:
        return digest(base / match.group(2)) == match.group(1).lower()
    except OSError:
        return False


def current(requirements, root):
    """Whether lock.sha256 matches, as common.sh dependency_locks_current checks it with
    `sha256sum --check --strict`: every line from the requirements directory, else every line from
    the project root (a legacy lock)."""
    try:
        lines = (requirements / FINGERPRINT).read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    return bool(lines) and any(all(matches(line, base) for line in lines) for base in (requirements, root))


def compile_locks(requirements, python, rerun):
    """Compile runtime.txt, then dev.txt, then fingerprint; 0, or 2 after a failed compile (the message
    names the input and rerun, the command to run again)."""
    for source, lock in zip(INPUTS, LOCKS):
        try:
            status = subprocess.run(['uv', 'pip', 'compile', '--python-version', python, source, '-o', lock],
                                    cwd=requirements, stdout=subprocess.DEVNULL,
                                    env={**os.environ, 'PWD': str(requirements)}).returncode
        except OSError:
            status = 127
        if status != 0:
            print(f'uv pip compile of {source} failed (exit {status}); lock.sha256 was left as it was.\n'
                  f'Fix {requirements / source} or its access to the package index, then run {rerun} again.',
                  file=sys.stderr)
            return 2
    fingerprint(requirements)
    return 0


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
    if len(argv) == 4 and argv[0] == 'compile':
        return compile_locks(Path(argv[1]), argv[2], argv[3])
    print('Usage: locks.py state <requirements dir> <project root> | fingerprint <requirements dir> | '
          'compile <requirements dir> <python> <command to rerun>', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
