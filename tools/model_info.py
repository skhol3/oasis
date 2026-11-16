#!/usr/bin/env python3
"""Compact static summary of one Odoo model from source, without starting Odoo.

Python files are parsed with ast only: project or Odoo code is never imported or
executed, and no environment, service or database is used.
"""
import ast
import importlib.util
import os
from pathlib import Path
import re
import sys

USAGE = 'Usage: model-info <model> [--field <name>] [--module <technical>] [--methods] [--all-fields]'
HELP = USAGE + '''

Summarize one Odoo model from source without starting Odoo: where it is defined,
the modules that extend it, its fields, field overrides and methods.
Scans the Odoo source (odoo/addons, addons), the optional Enterprise source and the
profile's tooling addon roots; the first module with a given name wins.
Python files are parsed with ast; no project code is imported or executed, and no
environment, service or database is used. Odoo/Enterprise source test_* modules and
tests/, migrations/, upgrades/ and static/ directories are skipped. Mixins named in
_inherit are listed, their fields are not expanded.

  --field <name>        only this field: definition and overrides with file:line
  --module <technical>  only the extension, fields, overrides and methods of this module
  --methods             every method with its decorators and super() calls

By default methods list public names per module and count private (_name) ones;
--module or --methods list them all. A bare compute/inverse flag means the
conventional _compute_<field>/_inverse_<field> method; labels equal to the one Odoo
derives from the field name are omitted and labels over 40 characters are cut.
  --all-fields          do not cap the field list (default cap: 40)
'''
MODEL = re.compile(r'[a-z0-9_]+(\.[a-z0-9_]+)*')
FIELD = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
MODULE = re.compile(r'[A-Za-z0-9_]+')
FIELD_CAP = 40
STRING_CHARS = 40
SKIP_DIRS = {'tests', 'migrations', 'upgrades', 'static', 'i18n', 'node_modules', '__pycache__'}
MODEL_ATTRS = ('_name', '_inherit', '_inherits', '_description', '_order', '_rec_name', '_table')
# Positional parameters per field type (Odoo 19 signatures); others take `string` first.
POSITIONAL = {
    'Many2one': ('comodel_name', 'string'),
    'One2many': ('comodel_name', 'inverse_name', 'string'),
    'Many2many': ('comodel_name', 'relation', 'column1', 'column2', 'string'),
    'Selection': ('selection', 'string'),
    'Reference': ('selection', 'string'),
}
FLAGS = ('selection', 'selection_add', 'required', 'readonly', 'store', 'index', 'compute',
         'related', 'inverse', 'default', 'tracking', 'company_dependent', 'groups')


def fail(message):
    print('ERROR: ' + message, file=sys.stderr)
    return 2


def parse_arguments(arguments):
    options = {'model': None, 'field': None, 'module': None, 'methods': False, 'all_fields': False}
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in ('--field', '--module'):
            if index + 1 >= len(arguments):
                return None
            options[argument[2:]] = arguments[index + 1]
            index += 2
            continue
        if argument == '--methods':
            options['methods'] = True
        elif argument == '--all-fields':
            options['all_fields'] = True
        elif argument.startswith('-') or options['model'] is not None:
            return None
        else:
            options['model'] = argument
        index += 1
    return options if options['model'] is not None else None


def literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None


def token(node):
    """Short text for a keyword value: literal constant, dotted name, else '?'."""
    if isinstance(node, ast.Constant):
        return str(node.value)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return ast.unparse(node)
    return '?'


def selection_keys(node):
    value = literal(node)
    if isinstance(value, (list, tuple)) and all(
            isinstance(item, (list, tuple)) and item for item in value):
        return '[' + ', '.join(str(item[0]) for item in value) + ']'
    return None


def field_call(node):
    """Field type for `fields.Type(...)`, else None."""
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == 'fields'):
        return node.func.attr
    return None


def default_label(name):
    """The label Odoo derives from a field name when `string` is not set."""
    base = name[:-4] if name.endswith('_ids') else name[:-3] if name.endswith('_id') else name
    return base.replace('_', ' ').title()


def describe_field(name, kind, call):
    values = dict(zip(POSITIONAL.get(kind, ('string',)), call.args))
    values.update((item.arg, item.value) for item in call.keywords if item.arg)
    text = kind
    if 'comodel_name' in values:
        comodel = token(values['comodel_name'])
        if 'inverse_name' in values:
            comodel += ':' + token(values['inverse_name'])
        text += f'({comodel})'
    string = values.get('string')
    if (isinstance(string, ast.Constant) and isinstance(string.value, str)
            and string.value != default_label(name)):
        label = string.value if len(string.value) <= STRING_CHARS else string.value[:STRING_CHARS - 1] + '…'
        text += f' "{label}"'
    for flag in FLAGS:
        if flag not in values:
            continue
        node = values[flag]
        if flag == 'default':
            text += ' default'
        elif flag == 'selection':
            text += ' ' + (selection_keys(node) or 'selection=dynamic')
        elif flag == 'selection_add':
            keys = selection_keys(node)
            text += ' +' + keys if keys else ' selection_add=dynamic'
        elif isinstance(node, ast.Constant) and (
                node.value is True or (flag in ('compute', 'inverse') and node.value == f'_{flag}_{name}')):
            # Conventional `_compute_<field>`/`_inverse_<field>` methods are implied by the bare flag.
            text += ' ' + flag
        else:
            text += f' {flag}={token(node)}'
    return text


def super_called(function):
    return any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == 'super' for node in ast.walk(function))


def describe_decorator(node):
    target = node.func if isinstance(node, ast.Call) else node
    name = ast.unparse(target)
    if not isinstance(node, ast.Call):
        return '@' + name
    arguments = [str(item.value) if isinstance(item, ast.Constant) else '…' for item in node.args]
    arguments += [f'{item.arg}={token(item.value)}' for item in node.keywords if item.arg]
    return f'@{name}({", ".join(arguments)})'


def describe_method(function):
    parts = [function.name, *(describe_decorator(item) for item in function.decorator_list)]
    if super_called(function):
        parts.append('super')
    return ' '.join(parts)


def as_list(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        return list(value)
    return []


def scan_roots(values):
    source = Path(values['ODOO_SOURCE'])
    roots = [(source / 'odoo/addons', True), (source / 'addons', True)]
    if values.get('ENTERPRISE_SOURCE'):
        roots.append((Path(values['ENTERPRISE_SOURCE']), True))
    roots += [(Path(path), False) for path in values['ADDON_ROOTS'].splitlines()]
    seen = set()
    for root, is_source in roots:
        resolved = root.resolve()
        if resolved not in seen and resolved.is_dir():
            seen.add(resolved)
            yield resolved, is_source


def modules(values):
    """(name, root, directory) per module; the first module with a name wins."""
    names = set()
    for root, is_source in scan_roots(values):
        for entry in sorted(os.scandir(root), key=lambda item: item.name):
            if (entry.name in names or not entry.is_dir() or entry.name.startswith('.')
                    or (is_source and entry.name.startswith('test_'))
                    or not os.path.isfile(os.path.join(entry.path, '__manifest__.py'))):
                continue
            names.add(entry.name)
            yield entry.name, root, Path(entry.path)


def python_files(directory):
    for current, dirs, files in os.walk(directory):
        dirs[:] = sorted(item for item in dirs if item not in SKIP_DIRS and not item.startswith('.'))
        for name in sorted(files):
            if name.endswith('.py') and name != '__manifest__.py':
                yield Path(current, name)


def model_classes(tree, model):
    """(kind, class node, attributes) for classes that define or extend the model."""
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        attributes = {}
        for statement in node.body:
            if (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                    and statement.targets[0].id in MODEL_ATTRS):
                attributes[statement.targets[0].id] = literal(statement.value)
        name = attributes.get('_name')
        inherit = as_list(attributes.get('_inherit'))
        if name == model and model not in inherit:
            yield 'definition', node, attributes
        elif (name is None or name == model) and model in inherit:
            yield 'extension', node, attributes


def collect(values, model):
    needles = (f"'{model}'".encode(), f'"{model}"'.encode())
    found = []
    for module, root, directory in modules(values):
        for path in python_files(directory):
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if not any(needle in data for needle in needles):
                continue
            try:
                tree = ast.parse(data, filename=str(path))
            except (SyntaxError, ValueError):
                continue
            relative = path.relative_to(root).as_posix()
            for kind, node, attributes in model_classes(tree, model):
                found.append({'kind': kind, 'module': module, 'path': relative, 'node': node,
                              'attributes': attributes})
    return found


def header(model, definition):
    attributes = definition['attributes'] if definition else {}
    text = f'model: {model}'
    if isinstance(attributes.get('_description'), str):
        text += f' — {attributes["_description"]}'
    table = attributes.get('_table')
    details = [f'table {table if isinstance(table, str) else model.replace(".", "_")}']
    if isinstance(attributes.get('_order'), str):
        details.append(f"order '{attributes['_order']}'")
    if isinstance(attributes.get('_rec_name'), str):
        details.append(f'rec_name {attributes["_rec_name"]}')
    return f'{text} ({", ".join(details)})'


def defined_line(model, definition):
    if not definition:
        return 'defined: not found in scanned roots'
    attributes = definition['attributes']
    text = f'defined: {definition["module"]} {definition["path"]}:{definition["node"].lineno}'
    mixins = [item for item in as_list(attributes.get('_inherit')) if item != model]
    if mixins:
        text += ' inherits ' + ', '.join(mixins)
    delegated = attributes.get('_inherits')
    if isinstance(delegated, dict) and delegated:
        text += ' delegates ' + ', '.join(f'{key}({value})' for key, value in delegated.items())
    return text


def mixins_of(model, entry):
    mixins = [item for item in as_list(entry['attributes'].get('_inherit')) if item != model]
    return f'(+{", ".join(mixins)})' if mixins else ''


def members(entries):
    """Fields (added or overridden) and methods per class entry, in scan order."""
    seen = set()
    fields, overrides, methods = [], [], {}
    for entry in entries:
        for statement in entry['node'].body:
            if (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)):
                kind = field_call(statement.value)
                if not kind:
                    continue
                name = statement.targets[0].id
                item = {'name': name, 'module': entry['module'], 'path': entry['path'],
                        'line': statement.lineno, 'text': describe_field(name, kind, statement.value)}
                (overrides if name in seen else fields).append(item)
                seen.add(name)
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                listed = methods.setdefault(entry['module'], {})
                listed.setdefault(statement.name, describe_method(statement))
    return fields, overrides, methods


def render(model, options, found):
    definitions = [entry for entry in found if entry['kind'] == 'definition']
    definition = definitions[0] if definitions else None
    entries = ([definition] if definition else []) + [entry for entry in found if entry is not definition]
    definer = definition['module'] if definition else None
    fields, overrides, methods = members(entries)
    selected = options['module']
    if selected is not None and selected not in {entry['module'] for entry in entries}:
        print(f'module does not define or extend {model}: {selected}', file=sys.stderr)
        return 1
    keep = (lambda item: item['module'] == selected) if selected else (lambda item: True)
    lines = [header(model, definition)]
    if options['field']:
        matches = [item for item in fields + overrides if item['name'] == options['field'] and keep(item)]
        if not matches:
            print(f'field not found: {model}.{options["field"]}', file=sys.stderr)
            return 1
        lines.append(f'field {options["field"]}:')
        lines += [f'  {item["path"]}:{item["line"]} {item["text"]}' for item in matches]
        print('\n'.join(lines))
        return 0
    lines.append(defined_line(model, definition))
    extensions = {}
    for entry in entries:
        if entry['module'] != definer:
            extensions.setdefault(entry['module'], []).append(entry)
    if selected and selected in extensions:
        located = ', '.join(f'{entry["path"]}:{entry["node"].lineno}' for entry in extensions[selected])
        mixins = ''.join(mixins_of(model, entry) for entry in extensions[selected])
        lines.append(f'extended in {selected}: {located}' + (f' {mixins}' if mixins else ''))
    elif not selected and extensions:
        names = [module + ''.join(mixins_of(model, entry) for entry in group)
                 for module, group in extensions.items()]
        lines.append(f'extended by ({len(names)}): ' + ', '.join(names))
    shown = [item for item in fields if keep(item)]
    if shown:
        lines.append(f'fields ({len(shown)}):')
        limit = len(shown) if options['all_fields'] else FIELD_CAP
        for item in shown[:limit]:
            tag = f' [{item["module"]}]' if item['module'] != definer and not selected else ''
            lines.append(f'  {item["name"]} {item["text"]}{tag}')
        if len(shown) > limit:
            lines.append(f'  ... +{len(shown) - limit} more (use --all-fields or --field)')
    redefined = [item for item in overrides if keep(item)]
    if redefined:
        lines.append(f'overrides ({len(redefined)}):')
        grouped = {}
        for item in redefined:
            grouped.setdefault(item['module'], []).append(f'{item["name"]} {item["text"]}')
        lines += [f'  {module}: ' + '; '.join(texts) for module, texts in grouped.items()]
    listed = {module: names for module, names in methods.items() if not selected or module == selected}
    # Without --module or --methods, private names are counted, not listed, to keep the summary small.
    private_hidden = not selected and not options['methods'] and any(
        name.startswith('_') for names in listed.values() for name in names)
    if listed:
        lines.append('methods (private: use --module or --methods):' if private_hidden else 'methods:')
        for module, names in listed.items():
            if options['methods']:
                lines.append(f'  {module}:')
                lines += [f'    {text}' for text in names.values()]
                continue
            shown_names = [name for name in names if not private_hidden or not name.startswith('_')]
            hidden = len(names) - len(shown_names)
            lines.append(f'  {module}: ' + ', '.join(shown_names + ([f'+{hidden} private'] if hidden else [])))
    print('\n'.join(lines))
    return 0


def main():
    arguments = sys.argv[1:]
    if arguments in (['--help'], ['-h']):
        print(HELP, end='')
        return 0
    options = parse_arguments(arguments)
    if options is None:
        return fail(USAGE)
    if not MODEL.fullmatch(options['model']):
        return fail('Invalid model name: use lowercase dotted words such as sale.order.')
    if options['field'] is not None and not FIELD.fullmatch(options['field']):
        return fail('Invalid field name.')
    if options['module'] is not None and not MODULE.fullmatch(options['module']):
        return fail('Module must use only letters, numbers, and underscores.')
    selected = os.environ.get('ODOO19_PROJECT_ROOT', '')
    if not selected or not Path(selected).is_absolute() or not Path(selected).is_dir():
        return fail('ODOO19_PROJECT_ROOT must name an absolute existing project directory.')
    # Load the packaged parser by its own path; never import project Python code.
    spec = importlib.util.spec_from_file_location('odoo19_config', Path(__file__).with_name('config.py'))
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    try:
        values = config.load(Path(selected).resolve())
    except config.InvalidConfig as exc:
        return fail(str(exc))
    found = collect(values, options['model'])
    if not found:
        print(f'model not found: {options["model"]}', file=sys.stderr)
        return 1
    return render(options['model'], options, found)


if __name__ == '__main__':
    raise SystemExit(main())
