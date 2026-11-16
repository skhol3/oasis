#!/usr/bin/env python3
"""Preserve direct Python invocation while passing project-owned roots explicitly."""
import os
from pathlib import Path
import shlex
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
tools = Path(os.environ.get('ODOO19_TOOLS_DIR', str(
    Path.home() / '.agents/skills/odoo19/tools')))
helper = tools / 'audit_dependencies.py'
config = tools / 'config.py'
if not helper.is_file() or not config.is_file():
    print(f'Odoo 19 tools are not installed: {helper}', file=sys.stderr)
    raise SystemExit(2)
result = subprocess.run([sys.executable, '-B', str(config), str(root)],
                        text=True, capture_output=True, check=False)
if result.returncode:
    sys.stderr.write(result.stderr)
    raise SystemExit(result.returncode)
values = dict(assignment.split('=', 1) for assignment in shlex.split(result.stdout))
arguments = ['--project-root', values['PROJECT_ROOT'],
             '--requirements-dir', values['REQUIREMENTS_DIR']]
for addon_root in values['ADDON_ROOTS'].split('\n'):
    arguments.extend(('--addon-root', addon_root))
project_python = values['PYTHON']
if not Path(project_python).is_file():
    print(f'Missing required local path: {project_python}', file=sys.stderr)
    raise SystemExit(1)
os.execv(project_python, [project_python, str(helper), *arguments, *sys.argv[1:]])
