#!/usr/bin/env bash
# Sourced by commands opting into compact output and by start --detach; no database operations.
# The location rules live in log_dirs.py (one place for run directories and server.log).
_log_dirs() {
  python3 -I -B "$(dirname "${BASH_SOURCE[0]}")/log_dirs.py" "$1" "${LOGS_DIR:-}" "${CHECKOUT_SLUG:-}"
}

# A new run-* directory: <logs>/<slug or main>/ ([tooling].logs, else logs next to the workspace file).
compact_log_directory() {
  _log_dirs run
}

# This checkout's server.log in the same directory (created 0700 when missing).
server_log_path() {
  _log_dirs server-log
}
