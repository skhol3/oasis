#!/usr/bin/env bash
# Sourced only by commands opting into compact output; no database operations.
compact_log_directory() {
  python3 -B - "$PROJECT_ROOT" <<'PY'
from pathlib import Path
import os
import sys
import tempfile

root = Path(sys.argv[1]).resolve()
target = root / 'dev/logs/odoo19'
if not target.resolve().is_relative_to(root):
    raise SystemExit('Compact logs must remain inside the project.')
os.umask(0o077)
target.mkdir(parents=True, exist_ok=True)
print(tempfile.mkdtemp(prefix='run-', dir=target))
PY
}
