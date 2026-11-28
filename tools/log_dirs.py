#!/usr/bin/env python3
"""Where a checkout's logs go (internal CLI): compact run directories and the detached server log.

Usage:
  log_dirs.py run <logs_dir> <slug>
      create a new run-* directory and print it (compact runs, tools/compact.sh)
  log_dirs.py server-log <logs_dir> <slug>
      create the checkout's log directory and print <it>/server.log (start --detach)

The checkout's log directory is <logs_dir>/<slug or main>, which must stay inside <logs_dir>: the LOGS_DIR
config.py resolved, [tooling].logs or, without it (v0.17.0), logs next to the workspace file. Each location is
checked before anything is created; a run directory is checked again once created. Directories are created 0700
(umask 077). A refusal prints its message to stderr and exits 1, creating nothing.
"""
import os
from pathlib import Path
import sys
import tempfile

LOGS_REFUSED = 'Compact logs must remain inside the configured logs directory.'
SERVER_LOG = 'server.log'


class LogLocationError(Exception):
    """A log location outside the places a checkout may write; the message says which rule."""


def checkout_directory(logs, slug):
    """(directory, base) of the checkout's logs: <logs>/<slug or main> and the resolved logs directory.

    Raises LogLocationError when there is no logs directory or the checkout directory would be outside it.
    Creates nothing.
    """
    if not logs:
        raise LogLocationError(LOGS_REFUSED)
    base = Path(logs).resolve()
    target = base / (slug or 'main')
    if not target.resolve().is_relative_to(base):
        raise LogLocationError(LOGS_REFUSED)
    return target, base


def run_directory(logs, slug):
    """A new run-* directory below the checkout's log directory."""
    target, base = checkout_directory(logs, slug)
    os.umask(0o077)
    target.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='run-', dir=target))
    if not run.resolve().is_relative_to(base):
        raise LogLocationError(LOGS_REFUSED)
    return run


def server_log(logs, slug, create=False):
    """The checkout's server.log; with create, its directory is created (0700) and checked again."""
    target, base = checkout_directory(logs, slug)
    if create:
        os.umask(0o077)
        target.mkdir(parents=True, exist_ok=True)
        if not target.resolve().is_relative_to(base):
            raise LogLocationError(LOGS_REFUSED)
    return target / SERVER_LOG


def main(argv):
    if len(argv) != 3 or argv[0] not in ('run', 'server-log'):
        print('ERROR: Usage: log_dirs.py run|server-log <logs_dir> <slug>', file=sys.stderr)
        return 2
    try:
        if argv[0] == 'run':
            print(run_directory(*argv[1:]))
        else:
            print(server_log(*argv[1:], create=True))
    except LogLocationError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
