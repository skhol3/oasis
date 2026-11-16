"""Run only the Odoo test process with short owned scratch (internal CLI)."""
from pathlib import Path
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile


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


def main():
    if len(sys.argv) < 3:
        print('Test scratch helper requires project root and command.', file=sys.stderr)
        return 2
    try:
        scratch = Path(tempfile.mkdtemp(prefix='odoo19-test-', dir='/tmp'))
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
    try:
        try:
            child = subprocess.Popen(sys.argv[2:], env={**os.environ, 'TMPDIR': str(scratch)})
            if received is not None:
                forward(received, None)
            code = child.wait()
            status = 128 + (-code) if code < 0 else code
            if received is not None:
                status = 128 + received
        except OSError:
            print('Cannot launch Odoo test process.', file=sys.stderr)
        try:
            retain_evidence(Path(sys.argv[1]).resolve(), scratch)
        except (OSError, subprocess.SubprocessError):
            print(f'Cannot retain browser evidence; test scratch kept at {scratch}. '
                  'Inspect it before manual removal.', file=sys.stderr)
            return status or 1
        try:
            shutil.rmtree(scratch)
        except OSError:
            print(f'Cannot clean owned test scratch: {scratch}. Inspect before manual removal.',
                  file=sys.stderr)
            return status or 1
        return status
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    sys.exit(main())
