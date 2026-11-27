#!/usr/bin/env python3
"""Flag the forms of a module that are wrong on its Odoo series (did the agent follow its series' recipe?).

v0.19.0 S7, docs/recipe-evals.md. An agent may never open the skill; this checks the result instead: it
scans the module's .py, .xml, .js and .csv files for the forms another series uses that are wrong on the
given one, such as a list view root or a modifier syntax another series uses.

The forms come from recipes/eval_forms.py (FORMS, per series; series knowledge stays with the recipes).
Every series tools/odoo_versions.py supports needs an entry: a supported series without one is a usage
error, so adding a series means adding its forms. The file is read when a scan starts: a missing or broken
recipes/eval_forms.py is a usage error too.

Output: one `wrong=<path>:<line>: <form> (<reason>)` line per hit (path relative to the module directory,
sorted by path and line), then `hits=<n>`. Exit codes: 0 no hit, 1 hits, 2 usage error (unknown or
unlisted series, missing directory, missing or broken recipes/eval_forms.py). Standard library only.
"""
import importlib.util
import os
from pathlib import Path
import sys

USAGE = 'Usage: recipe_evals.py <series> <module-dir>'
HELP = USAGE + '''

Scan the .py, .xml, .js and .csv files of <module-dir> for the forms that are wrong on Odoo <series>
and print one wrong=<path>:<line>: <form> (<reason>) line per hit, then hits=<n>.
Exit 0 without hits, 1 with hits, 2 on a usage error.
'''
KINDS = ('py', 'xml', 'js', 'csv')
SKIPPED_DIRECTORIES = {'__pycache__', 'node_modules'}


class UsageError(Exception):
    """A reason to stop before scanning (exit 2)."""


def load_forms():
    """FORMS of recipes/eval_forms.py, beside the tools directory in the repository and the install;
    UsageError naming the file when it is missing, fails to load or holds no FORMS dictionary."""
    path = Path(__file__).resolve().parent.parent / 'recipes' / 'eval_forms.py'
    if not path.is_file():
        raise UsageError(f'Cannot load {path} (missing).')
    try:
        spec = importlib.util.spec_from_file_location('eval_forms', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as error:  # any failure of the file is the maintainer's to fix, not a hit
        reason = ' '.join(f'{type(error).__name__}: {error}'.split())
        raise UsageError(f'Cannot load {path} ({reason}).') from None
    forms = getattr(module, 'FORMS', None)
    if not isinstance(forms, dict):
        raise UsageError(f'Cannot load {path} (no FORMS dictionary).')
    return forms


def supported_series():
    path = Path(__file__).resolve().parent / 'odoo_versions.py'
    spec = importlib.util.spec_from_file_location('odoo_versions', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.supported()


def module_files(directory):
    """(relative POSIX path, kind) of every scanned file under directory, sorted by path."""
    found = []
    for parent, directories, files in os.walk(directory):
        directories[:] = sorted(name for name in directories
                                if not name.startswith('.') and name not in SKIPPED_DIRECTORIES)
        for name in files:
            kind = name.rpartition('.')[2]
            if '.' in name and kind in KINDS:
                path = Path(parent) / name
                found.append((path.relative_to(directory).as_posix(), kind))
    return sorted(found)


def hits(directory, forms):
    """Sorted (path, line, form) of every hit of forms under directory."""
    found = set()
    order = {entry: index for index, entry in enumerate(forms)}
    for relative, kind in module_files(directory):
        text = (directory / relative).read_text(encoding='utf-8', errors='replace')
        for entry in forms:
            if kind not in entry.kinds:
                continue
            for match in entry.pattern.finditer(text):
                start = match.start('hit') if 'hit' in entry.pattern.groupindex and match.group('hit') \
                    else match.start()
                found.add((relative, text.count('\n', 0, start) + 1, entry))
    return sorted(found, key=lambda hit: (hit[0], hit[1], order[hit[2]]))


def parse(arguments):
    """(series, directory, forms); UsageError when they cannot be scanned."""
    if len(arguments) != 2 or not all(arguments):
        raise UsageError(USAGE)
    series, directory = arguments
    supported = supported_series()
    if series not in supported:
        raise UsageError(f'Unknown series {series}; supported: {", ".join(supported)}.')
    forms = load_forms().get(series)
    if not forms:
        raise UsageError(f'No forms for series {series} in recipes/eval_forms.py: '
                         f'add the forms that are wrong on it to FORMS.')
    path = Path(directory)
    if not path.is_dir():
        raise UsageError(f'Not a module directory: {directory}')
    return series, path, forms


def main(arguments):
    if arguments in (['-h'], ['--help']):
        print(HELP, end='')
        return 0
    try:
        _series, directory, forms = parse(arguments)
    except UsageError as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 2
    found = hits(directory, forms)
    for path, line, entry in found:
        print(f'wrong={path}:{line}: {entry.form} ({entry.reason})')
    print(f'hits={len(found)}')
    return 1 if found else 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
