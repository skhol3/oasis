#!/usr/bin/env python3
"""Where a checkout's logs go (internal CLI): compact run directories and the detached server log.

Usage:
  log_dirs.py run <project_root> <checkout_kind> <main_root> <logs_dir> <slug>
      create a new run-* directory and print it (compact runs, tools/compact.sh)
  log_dirs.py server-log <project_root> <checkout_kind> <main_root> <logs_dir> <slug>
      create the checkout's log directory and print <it>/server.log (start --detach)

The checkout's log directory: with [tooling].logs (<logs_dir>, already resolved by config.py),
<logs_dir>/<slug or main>, which must stay inside <logs_dir>; otherwise <project_root>/dev/logs/odoo19,
which must resolve inside the project or, in a linked worktree, inside the main checkout's
dev/logs/odoo19. Each location is checked before anything is created; a run directory is checked
again once created. Directories are created 0700 (umask 077). A refusal prints its message to
stderr and exits 1, creating nothing.
"""
import os
from pathlib import Path
import sys
import tempfile

LOGS_REFUSED = 'Compact logs must remain inside the configured logs directory.'
PROJECT_REFUSED = 'Compact logs must remain inside the project.'
SERVER_LOG = 'server.log'


class LogLocationError(Exception):
    """A log location outside the places a checkout may write; the message says which rule."""


def checkout_directory(root, kind, main_root, logs, slug):
    """(directory, base, refusal) of the checkout's logs; base is the logs directory or None.

    Raises LogLocationError when the directory would be outside its allowed location. Creates
    nothing.
    """
    root = Path(root).resolve()
    if logs:
        # [tooling].logs: one directory per checkout, <logs>/<slug or main>. Runs of the layout
        # before 0.8.0 (<logs>/odoo19/<slug or main>) stay where they are.
        base = Path(logs).resolve()
        target = base / (slug or 'main')
        if not target.resolve().is_relative_to(base):
            raise LogLocationError(LOGS_REFUSED)
        return target, base, LOGS_REFUSED
    target = root / 'dev/logs/odoo19'
    resolved = target.resolve()
    # A linked worktree may keep its logs in the main checkout's dev/logs/odoo19; nothing else.
    allowed = resolved.is_relative_to(root) or (
        kind == 'linked' and main_root
        and resolved.is_relative_to((Path(main_root) / 'dev/logs/odoo19').resolve()))
    if not allowed:
        raise LogLocationError(PROJECT_REFUSED)
    return target, None, PROJECT_REFUSED


def run_directory(root, kind, main_root, logs, slug):
    """A new run-* directory below the checkout's log directory."""
    target, base, refused = checkout_directory(root, kind, main_root, logs, slug)
    os.umask(0o077)
    target.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='run-', dir=target))
    if base is not None and not run.resolve().is_relative_to(base):
        raise LogLocationError(refused)
    return run


def server_log(root, kind, main_root, logs, slug, create=False):
    """The checkout's server.log; with create, its directory is created (0700) and checked again."""
    target, base, refused = checkout_directory(root, kind, main_root, logs, slug)
    if create:
        os.umask(0o077)
        target.mkdir(parents=True, exist_ok=True)
        if base is not None and not target.resolve().is_relative_to(base):
            raise LogLocationError(refused)
    return target / SERVER_LOG


def main(argv):
    if len(argv) != 6 or argv[0] not in ('run', 'server-log'):
        print('ERROR: Usage: log_dirs.py run|server-log <project_root> <checkout_kind> <main_root> '
              '<logs_dir> <slug>', file=sys.stderr)
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
