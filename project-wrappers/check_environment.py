#!/usr/bin/env python3
"""Preserve the original Python helper's direct <lockfile> CLI."""
import os
from pathlib import Path
import sys

tools = Path(os.environ.get('OASIS_TOOLS_DIR') or str(Path.home() / '.agents/skills/oasis/tools'))
helper = tools / 'check_environment.py'
if not helper.is_file():
    print(f'oasis tools are not installed: {helper}', file=sys.stderr)
    raise SystemExit(2)
os.execv(sys.executable, [sys.executable, '-B', str(helper), *sys.argv[1:]])
