#!/usr/bin/env bash
# Sourced only by commands opting into compact output; no database operations.
compact_log_directory() {
  python3 -B - "$PROJECT_ROOT" "${CHECKOUT_KIND:-}" "${CHECKOUT_MAIN_ROOT:-}" \
    "${LOGS_DIR:-}" "${CHECKOUT_SLUG:-}" <<'PY'
from pathlib import Path
import os
import sys
import tempfile

root = Path(sys.argv[1]).resolve()
kind, main_root, logs, slug = sys.argv[2:6]
if logs:
    # [tooling].logs: one directory per checkout, <logs>/<slug or main>. Runs of the layout
    # before 0.8.0 (<logs>/odoo19/<slug or main>) stay where they are.
    base = Path(logs).resolve()
    target = base / (slug or 'main')
    refused = 'Compact logs must remain inside the configured logs directory.'
    # Checked before anything is created, and again on the created run directory.
    if not target.resolve().is_relative_to(base):
        raise SystemExit(refused)
    os.umask(0o077)
    target.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='run-', dir=target))
    if not run.resolve().is_relative_to(base):
        raise SystemExit(refused)
    print(run)
    raise SystemExit(0)
target = root / 'dev/logs/odoo19'
resolved = target.resolve()
# A linked worktree may keep its logs in the main checkout's dev/logs/odoo19; nothing else.
allowed = resolved.is_relative_to(root) or (
    kind == 'linked' and main_root
    and resolved.is_relative_to((Path(main_root) / 'dev/logs/odoo19').resolve()))
if not allowed:
    raise SystemExit('Compact logs must remain inside the project.')
os.umask(0o077)
target.mkdir(parents=True, exist_ok=True)
print(tempfile.mkdtemp(prefix='run-', dir=target))
PY
}
