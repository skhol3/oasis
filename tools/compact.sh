#!/usr/bin/env bash
# Sourced only by commands opting into compact output; no database operations.
compact_log_directory() {
  python3 -B - "$PROJECT_ROOT" "${CHECKOUT_KIND:-}" "${CHECKOUT_MAIN_ROOT:-}" <<'PY'
from pathlib import Path
import os
import sys
import tempfile

root = Path(sys.argv[1]).resolve()
kind, main_root = sys.argv[2], sys.argv[3]
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
