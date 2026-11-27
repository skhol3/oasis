#!/usr/bin/env python3
"""Build the `library` module the recipes of one Odoo series describe, and check it is complete.

v0.19.0 S6. The code skills (odoo-backend, odoo-views-frontend, odoo-security, odoo-testing) hold the
recipes of a series in `<skill>/references/<series>/<recipe>.md`. A recipe shows a file as a paragraph
that starts with the label `library/<path>` (backticks, possibly followed by text such as `, final:`)
right before a fenced code block (blank lines allowed between them); the block is the file's content.
A file several recipes show must be the same copy in each, so the order the recipes are read in does
not matter (they are read by skill, then by file name).

The tool writes every labelled file under `<destination>/library/`, then checks without a database or
Odoo that the module is complete: every `data` and `demo` file of the manifest, every module the
`__init__.py` files import and every `assets` path or glob of the module has a source; Python files
compile, XML files parse and CSV files are rectangular. The next step is the module's tests on a fresh
database, `oasis --project <root> test-module --compact library`.

Exit codes: 0 complete; 1 built but incomplete or a file does not parse (stdout lists what); 2 refused
before writing anything (usage, `<destination>/library` already exists, two recipes give different
content for one path, a label leaves `library/`, or the series has no rendered recipes).
Standard library only.
"""
import ast
import csv
import glob
import io
import os
from pathlib import Path, PurePosixPath
import py_compile
import re
import sys
import tempfile
import xml.etree.ElementTree as ElementTree

USAGE = 'Usage: recipe_module.py <series> <destination> [--root <dir>]'
HELP = USAGE + '''

Build the library module of the recipes of <series> into <destination>/library and check it is
complete and parses, without a database. --root is the bundle root that holds the skills (default:
the directory above this script's tools/).
'''
SKILLS = ('odoo-backend', 'odoo-views-frontend', 'odoo-security', 'odoo-testing')
MODULE = 'library'
SERIES = re.compile(r'\d+\.0')
FENCE = re.compile(r'^```([a-z]*)\n(.*?)^```$', re.M | re.S)
LABEL = re.compile(r'^`(library/[\w./-]+)`')
NEXT = 'oasis --project <root> test-module --compact library'


class Refused(Exception):
    """A reason to stop before writing anything (exit 2)."""


def parse_arguments(arguments):
    """(series, destination, root) from the command line; Refused on a usage error."""
    root = Path(__file__).resolve().parents[1]
    positional = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == '--root':
            if index + 1 >= len(arguments) or not arguments[index + 1]:
                raise Refused(USAGE)
            root = Path(arguments[index + 1])
            index += 2
            continue
        if argument.startswith('-'):
            raise Refused(USAGE)
        positional.append(argument)
        index += 1
    if len(positional) != 2 or not positional[1]:
        raise Refused(USAGE)
    series, destination = positional
    if not SERIES.fullmatch(series):
        raise Refused(f'Invalid series {series!r}: expected <major>.0.')
    return series, Path(destination), root


def label_of(text, start):
    """The `library/<path>` label of the fenced block starting at offset start, or None.

    The label is the last non-blank line before the block, or the first line of the paragraph that
    line ends (a label sentence may wrap over several lines)."""
    lines = text[:start].splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines or lines[-1].startswith('```'):
        return None
    paragraph = len(lines) - 1
    while paragraph > 0 and lines[paragraph - 1].strip() and not lines[paragraph - 1].startswith('```'):
        paragraph -= 1
    for line in (lines[-1], lines[paragraph]):
        match = LABEL.match(line)
        if match:
            return match[1]
    return None


def recipes(root, series):
    """The rendered recipe files of the series, by skill then file name."""
    found = []
    for skill in SKILLS:
        directory = root / skill / 'references' / series
        if directory.is_dir():
            found += sorted(path for path in directory.glob('*.md') if path.is_file())
    return found


def collect(root, series):
    """{library/<path>: content} from every recipe of the series; Refused on a conflict."""
    files = recipes(root, series)
    if not files:
        raise Refused(f'No rendered recipes for {series} under {root} '
                      f'(<skill>/references/{series}/*.md of {", ".join(SKILLS)}).')
    contents, sources = {}, {}
    for path in files:
        name = path.relative_to(root).as_posix()
        text = path.read_text(encoding='utf-8')
        for match in FENCE.finditer(text):
            label = label_of(text, match.start())
            if label is None:
                continue
            parts = PurePosixPath(label).parts
            if '..' in parts or '.' in parts or len(parts) < 2:
                raise Refused(f'{name}: the label {label} leaves {MODULE}/.')
            if label in contents and contents[label] != match[2]:
                raise Refused(f'{label} differs between {sources[label]} and {name}.')
            contents.setdefault(label, match[2])
            sources.setdefault(label, name)
    return contents


def module_exists(directory, name):
    path = directory.joinpath(*name.split('.'))
    return path.with_suffix('.py').is_file() or (path / '__init__.py').is_file()


def import_problems(destination, module):
    """The modules the `__init__.py` files import relatively that have no source, as paths."""
    missing = []
    for init in sorted(module.rglob('__init__.py')):
        try:
            tree = ast.parse(init.read_text(encoding='utf-8'))
        except SyntaxError:
            continue  # named by the compile check
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level == 0:
                continue
            base = init.parent
            for _ in range(node.level - 1):
                base = base.parent
            names = [node.module] if node.module else [alias.name for alias in node.names]
            for name in names:
                if not module_exists(base, name):
                    target = base.joinpath(*name.split('.')).with_suffix('.py')
                    missing.append(target.relative_to(destination).as_posix())
    return missing


def asset_paths(assets):
    """The module's own paths or globs among the manifest `assets` entries."""
    paths = []
    for entries in (assets or {}).values():
        for entry in entries or []:
            if isinstance(entry, str):
                candidates = [entry]
            elif isinstance(entry, (list, tuple)) and entry and entry[0] not in ('include', 'remove'):
                candidates = [item for item in entry[1:] if isinstance(item, str)]
            else:
                candidates = []
            paths += [item for item in candidates if item.startswith(MODULE + '/')]
    return paths


def completeness(destination):
    """(missing paths, invalid lines) of the module built under destination."""
    module = destination / MODULE
    missing, invalid = [], []
    manifest_path = module / '__manifest__.py'
    manifest = {}
    for required in (manifest_path, module / '__init__.py'):
        if not required.is_file():
            missing.append(required.relative_to(destination).as_posix())
    if manifest_path.is_file():
        try:
            manifest = ast.literal_eval(manifest_path.read_text(encoding='utf-8'))
        except (SyntaxError, ValueError) as error:
            invalid.append(f'{MODULE}/__manifest__.py: not a literal dictionary ({error})')
        if not isinstance(manifest, dict):
            if not invalid:
                invalid.append(f'{MODULE}/__manifest__.py: not a literal dictionary')
            manifest = {}
    for key in ('data', 'demo'):
        for name in manifest.get(key) or []:
            if isinstance(name, str) and not (module / name).is_file():
                missing.append(f'{MODULE}/{name}')
    missing += import_problems(destination, module)
    for pattern in asset_paths(manifest.get('assets')):
        if not any(os.path.isfile(path)
                   for path in glob.glob(str(destination / pattern), recursive=True)):
            missing.append(pattern)
    invalid += parse_problems(destination, module)
    return list(dict.fromkeys(missing)), invalid


def parse_problems(destination, module):
    """One line per Python file that does not compile, XML file that does not parse, CSV file that
    is empty or not rectangular."""
    problems = []
    with tempfile.TemporaryDirectory(prefix='oasis-recipe-module-') as scratch:
        for path in sorted(item for item in module.rglob('*') if item.is_file()):
            name = path.relative_to(destination).as_posix()
            if path.suffix == '.py':
                try:
                    py_compile.compile(str(path), cfile=str(Path(scratch) / 'compiled.pyc'), doraise=True)
                except py_compile.PyCompileError as error:
                    cause = error.exc_value
                    if isinstance(cause, SyntaxError):
                        problems.append(f'{name}: {cause.msg} (line {cause.lineno})')
                    else:
                        problems.append(f'{name}: {error.exc_type_name}')
            elif path.suffix == '.xml':
                try:
                    ElementTree.parse(path)
                except ElementTree.ParseError as error:
                    problems.append(f'{name}: {error}')
            elif path.suffix == '.csv':
                rows = list(csv.reader(io.StringIO(path.read_text(encoding='utf-8'))))
                if not rows or len({len(row) for row in rows}) != 1:
                    problems.append(f'{name}: csv rows differ in length')
    return problems


def main(arguments):
    if arguments in (['-h'], ['--help']):
        print(HELP, end='')
        return 0
    try:
        series, destination, root = parse_arguments(arguments)
        if (destination / MODULE).exists():
            raise Refused(f'{destination / MODULE} already exists: give a destination without {MODULE}/.')
        contents = collect(root, series)
    except Refused as refusal:
        print(f'ERROR: {refusal}', file=sys.stderr)
        return 2
    for label, content in contents.items():
        target = destination.joinpath(*PurePosixPath(label).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
    missing, invalid = completeness(destination)
    print(f'files={len(contents)}')
    if missing:
        print('missing=' + ','.join(missing))
    for line in invalid:
        print(f'invalid={line}')
    if missing or invalid:
        return 1
    print('ok')
    print(f'next={NEXT}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
