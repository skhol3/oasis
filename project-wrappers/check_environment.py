#!/usr/bin/env python3
"""Preserve the original Python helper's direct <lockfile> CLI."""
import os
from pathlib import Path
import sys

tools = Path(os.environ.get('ODOO19_TOOLS_DIR', str(
    Path.home() / '.agents/skills/odoo19/tools')))
helper = tools / 'check_environment.py'
if not helper.is_file():
    print(f'Odoo 19 tools are not installed: {helper}', file=sys.stderr)
    raise SystemExit(2)
os.execv(sys.executable, [sys.executable, '-B', str(helper), *sys.argv[1:]])
