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
      lock.sha256` run in that directory would (with overrides.txt last when it exists).
  locks.py compile <requirements dir> <python> <command to rerun>
      Runs `uv pip compile --python-version <python> <input> -o <lock>` in that directory for
      runtime.in, then dev.in (dev.in constrains itself with -c runtime.txt; uv's echo of the lock is
      dropped; its messages pass through to stderr as uv writes them), then fingerprint. A failed
      compile stops before lock.sha256 (exit 2), naming the input and the command to run again.
  locks.py recorded <requirements dir> <project root>
      Exit 0 when overrides.txt does not exist or lock.sha256 records it, else 1: bootstrap and
      check-environment add it to `sha256sum --check`, which cannot see a file lock.sha256 omits.
  locks.py uv-env
      Prints `export UV_LEGACY_TAR_BACKEND=1` when the uv on PATH needs it (below), else nothing:
      bootstrap evaluates it before its uv commands.

Old source archives (v0.16.0 S3, docs/setup.md#old-source-archives): uv 0.13 and later refuse some
old sdists (V7 tar headers, such as PyPDF2 1.26.0 of Odoo 15.0) with "invalid tar identity" unless
UV_LEGACY_TAR_BACKEND=1. Every uv command of compile, setup and bootstrap gets that variable when
`uv --version` reports 0.13 or later and the caller did not set it (a value set, even empty, is kept). A
compile that still fails with that message names the remedy instead of the package index.

overrides.txt (v0.15.0 S7) is an optional input next to runtime.in: when it exists, both compiles
get `--override overrides.txt` (uv replaces the requirements it names, nested -r included), and
lock.sha256 records it, so adding, changing or removing it makes the locks stale. Without it every
command does exactly what it did before. No command ever writes an input (.in or overrides.txt) file.
"""
import codecs
import hashlib
import io
import locale
import os
import re
import subprocess
import sys
from pathlib import Path

INPUTS = ('runtime.in', 'dev.in')
LOCKS = ('runtime.txt', 'dev.txt')
FILES = ('runtime.in', 'runtime.txt', 'dev.in', 'dev.txt')
# The optional input of uv's --override (S7): fingerprinted after FILES, only when it exists.
OVERRIDES = 'overrides.txt'
FINGERPRINT = 'lock.sha256'
LEGACY_TAR = 'UV_LEGACY_TAR_BACKEND'
# The first uv release whose tar backend refuses V7 archives without LEGACY_TAR.
LEGACY_TAR_FROM = (0, 13)
INVALID_TAR = 'invalid tar identity'
_UV_VERSION = []
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
    # overrides.txt added, changed, or removed while lock.sha256 still records it.
    overrides = os.path.realpath(requirements / OVERRIDES)
    if (requirements / OVERRIDES).is_file():
        if entries.get(overrides) != digest(requirements / OVERRIDES):
            return 'stale'
    elif overrides in entries:
        return 'stale'
    return 'edited'


def overrides_recorded(requirements, root):
    """Whether overrides.txt is absent or lock.sha256 names it (from either base, as recorded reads it)."""
    return (not (requirements / OVERRIDES).is_file()
            or os.path.realpath(requirements / OVERRIDES) in recorded(requirements, root))


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
    return (bool(lines) and any(all(matches(line, base) for line in lines) for base in (requirements, root))
            and overrides_recorded(requirements, root))


def uv_version():
    """(major, minor) of the uv on PATH (`uv --version`, run once), or None when it cannot be read."""
    if not _UV_VERSION:
        try:
            output = subprocess.run(['uv', '--version'], capture_output=True, text=True, timeout=30, cwd='/',
                                    stdin=subprocess.DEVNULL).stdout
        except (OSError, subprocess.SubprocessError):
            output = ''
        match = re.match(r'uv ([0-9]+)\.([0-9]+)', output)
        _UV_VERSION.append((int(match.group(1)), int(match.group(2))) if match else None)
    return _UV_VERSION[0]


def uv_environment(base=None):
    """base (default: os.environ) with UV_LEGACY_TAR_BACKEND=1 when uv needs it and base does not set it."""
    env = dict(os.environ if base is None else base)
    if LEGACY_TAR not in env and (uv_version() or (0, 0)) >= LEGACY_TAR_FROM:
        env[LEGACY_TAR] = '1'
    return env


def streamed(command, **options):
    """(exit status, stderr) of command, its stderr passed on to ours as it comes (tee), decoded as text mode
    decodes it (the locale's encoding, undecodable bytes replaced, line ends translated). When the relay fails
    (BrokenPipeError on our stderr, KeyboardInterrupt), the child is killed and waited for before the error
    goes on: it never outlives the command."""
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **options)
    decoder = io.IncrementalNewlineDecoder(codecs.getincrementaldecoder(locale.getpreferredencoding(False))(
        errors='replace'), translate=True)
    received = []
    try:
        with process.stderr:
            while True:
                chunk = os.read(process.stderr.fileno(), 65536)
                text = decoder.decode(chunk, final=not chunk)
                if text:
                    received.append(text)
                    sys.stderr.write(text)
                    sys.stderr.flush()
                if not chunk:
                    break
    except BaseException:
        process.kill()
        process.wait()
        raise
    return process.wait(), ''.join(received)


def compile_locks(requirements, python, rerun):
    """Compile runtime.txt, then dev.txt, then fingerprint; 0, or 2 after a failed compile (the message
    names the input and rerun, the command to run again). uv's messages pass through to stderr as uv writes
    them."""
    override = ['--override', OVERRIDES] if (requirements / OVERRIDES).is_file() else []
    env = uv_environment({**os.environ, 'PWD': str(requirements)})
    for source, lock in zip(INPUTS, LOCKS):
        try:
            status, errors = streamed(['uv', 'pip', 'compile', '--python-version', python, *override, source, '-o',
                                       lock], cwd=requirements, env=env)
        except OSError:
            status, errors = 127, ''
        if status != 0:
            if INVALID_TAR not in errors:
                remedy = f'Fix {requirements / source} or its access to the package index, then run {rerun} again.'
            elif env.get(LEGACY_TAR) == '1':
                remedy = (f'uv could not read an old source archive ({INVALID_TAR}) even with {LEGACY_TAR}=1: pin a '
                          f'version of that package with a wheel in {requirements / OVERRIDES} (uv pip compile '
                          f'--override), then run {rerun} again.')
            else:
                remedy = (f'uv could not read an old source archive ({INVALID_TAR}): set {LEGACY_TAR}=1 '
                          f'(docs/setup.md#old-source-archives), then run {rerun} again.')
            print(f'uv pip compile of {source} failed (exit {status}); lock.sha256 was left as it was.\n{remedy}',
                  file=sys.stderr)
            return 2
    fingerprint(requirements)
    return 0


def fingerprint(requirements):
    names = (*FILES, OVERRIDES) if (requirements / OVERRIDES).is_file() else FILES
    text = ''.join(f'{digest(requirements / name)}  {name}\n' for name in names)
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
    if len(argv) == 3 and argv[0] == 'recorded':
        return 0 if overrides_recorded(Path(argv[1]), Path(argv[2])) else 1
    if argv == ['uv-env']:
        if uv_environment().get(LEGACY_TAR) == '1' and LEGACY_TAR not in os.environ:
            print(f'export {LEGACY_TAR}=1')
        return 0
    print('Usage: locks.py state <requirements dir> <project root> | fingerprint <requirements dir> | '
          'compile <requirements dir> <python> <command to rerun> | recorded <requirements dir> <project root> | '
          'uv-env',
          file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
