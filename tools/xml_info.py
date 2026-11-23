#!/usr/bin/env python3
"""Compact static summaries of Odoo XML data from source, without starting Odoo.

`view` lists the views of one model with their extension tree; `xmlid` shows where one XML id is
defined, what extends it and where it is referenced. XML files are parsed with expat and Python
or CSV files are only searched as text: nothing is imported or executed, and no environment,
service or database is used.
"""
import importlib.util
import os
from pathlib import Path
import re
import sys
import xml.parsers.expat

VIEW_USAGE = 'Usage: view-info <model> [--type <tag>] [--module <technical>]'
VIEW_HELP = VIEW_USAGE + '''

List the views of one Odoo model from source without starting Odoo: each base view with its
type (the root tag of its arch), XML id and file:line, and below it the views that extend it.
A view without a model field takes the model of the view it inherits. Extensions show how many
changes they make (xpath elements and elements with a position attribute).
Scans the Odoo source (odoo/addons, addons), the optional Enterprise source and the profile's
tooling addon roots; the first module with a given name wins. Odoo/Enterprise source test_*
modules and tests/, migrations/, upgrades/, static/ and i18n/ directories are skipped.

  --type <tag>          only base views of this type (form, list, kanban, search, ...) with
                        their extensions
  --module <technical>  only the views this module defines, with what each one extends

`unresolved:` lists extensions whose inherited view is not in the scanned roots, with the views
that extend them; `skipped:` lists files that are not well-formed XML. Long lists are capped
(40 extensions per view, 10 unresolved, 5 skipped files) and end with the count of the rest.
'''
XMLID_USAGE = 'Usage: xmlid-info <module>.<name>'
XMLID_HELP = XMLID_USAGE + '''

Show where one XML id is defined (record, template or menuitem) with its fields, the views
that extend it and the files that reference it, without starting Odoo. References are found as
text in XML, Python and CSV files: the full id anywhere, and inside the defining module also
the name alone in ref, parent and action attributes, groups lists, %(name)d, ref('name')
and CSV cells. Extensions and references list at most 20 entries each.
The same roots and skipped directories as view-info apply.
'''
MODEL = re.compile(r'[a-z0-9_]+(\.[a-z0-9_]+)*')
MODULE = re.compile(r'[A-Za-z0-9_]+')
VIEW_TYPE = re.compile(r'[a-z_]+')
XML_ID = re.compile(r'[A-Za-z0-9_]+\.[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*')
SKIP_DIRS = {'tests', 'migrations', 'upgrades', 'static', 'i18n', 'node_modules', '__pycache__'}
TYPE_ORDER = ('form', 'list', 'kanban', 'search')
VALUE_CHARS = 60
FIELD_CAP = 12
REFERENCE_CAP = 20
SKIPPED_CAP = 5
REWRITE_CAP = 10
EXTENSION_CAP = 40
UNRESOLVED_CAP = 10
REFERENCE_SUFFIXES = ('.xml', '.py', '.csv')
# The two ways a data file names the inherited view: <template inherit_id="..."> and
# <field name="inherit_id" ref="..."/>.
INHERIT_ATTRIBUTE = re.compile(r'''\binherit_id=["'][^"']*["']''')
INHERIT_FIELD = re.compile(r'''<field\b[^>]*\bname=["']inherit_id["'][^>]*>''')
REF_ATTRIBUTE = re.compile(r'''\bref=["'][^"']*["']''')


def fail(message):
    print('ERROR: ' + message, file=sys.stderr)
    return 2


def sibling(name):
    """A packaged helper loaded from its file (python3 -I keeps the tools directory off sys.path)."""
    spec = importlib.util.spec_from_file_location(f'oasis_xml_info_{name}', Path(__file__).with_name(f'{name}.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def qualify(module, name):
    """An XML id as written in a data file, with the module it belongs to."""
    return name if '.' in name else f'{module}.{name}'


def files_of(directory, suffixes):
    for current, dirs, files in os.walk(directory):
        dirs[:] = sorted(item for item in dirs if item not in SKIP_DIRS and not item.startswith('.'))
        for name in sorted(files):
            if name.endswith(suffixes):
                yield Path(current, name)


class ParseError(Exception):
    def __init__(self, line):
        super().__init__(line)
        self.line = line


def parse_records(content, module):
    """The record, template and menuitem elements of one data file, in document order.

    Each is a dict: id (qualified), tag, model, line, fields (name -> text, in order; a ref
    attribute as its qualified id), arch_root (first element of the arch field) and changes
    (xpath elements and elements with a position attribute).
    """
    records = []
    stack = []
    open_record = []  # at most one: records do not nest
    open_field = []
    menus = []  # enclosing menuitems, for the implicit parent of nested ones

    def start(name, attributes):
        depth = len(stack)
        stack.append(name)
        if open_record:
            record = open_record[0]
            if record['tag'] == 'record' and depth == record['depth'] + 1 and name == 'field':
                open_field.append({'name': attributes.get('name', ''), 'depth': depth, 'text': [],
                                   'ref': attributes.get('ref'), 'eval': attributes.get('eval')})
                return
            in_arch = record['tag'] == 'template' or (open_field and open_field[0]['name'] == 'arch')
            if in_arch:
                if record['arch_root'] is None:
                    record['arch_root'] = name
                if name == 'xpath' or 'position' in attributes:
                    record['changes'] += 1
            return
        if not attributes.get('id') or name not in ('record', 'template', 'menuitem'):
            return
        record = {'id': qualify(module, attributes['id']), 'tag': name, 'line': parser.CurrentLineNumber,
                  'model': attributes.get('model', ''), 'fields': {}, 'arch_root': None, 'changes': 0,
                  'depth': depth}
        if name == 'menuitem':
            parent = attributes.get('parent') or (menus[-1][1] if menus else None)
            for key, value in (('name', attributes.get('name')), ('parent', parent),
                               ('action', attributes.get('action')), ('groups', attributes.get('groups'))):
                if value:
                    record['fields'][key] = qualify(module, value) if key in ('parent', 'action') else value
            records.append(record)
            menus.append((depth, record['id']))
            return
        if name == 'template':
            record['model'] = 'ir.ui.view'
            for key in ('name', 'inherit_id'):
                if attributes.get(key):
                    record['fields'][key] = qualify(module, attributes[key]) if key == 'inherit_id' else attributes[key]
        open_record.append(record)

    def characters(data):
        if open_field and open_field[0]['name'] != 'arch' and len(open_field[0]['text']) < 20:
            open_field[0]['text'].append(data)

    def end(name):
        stack.pop()
        depth = len(stack)
        if menus and menus[-1][0] == depth:
            menus.pop()
        if open_field and open_field[0]['depth'] == depth:
            field = open_field.pop()
            if field['name'] and field['name'] != 'arch':
                if field['ref']:
                    value = qualify(module, field['ref'])
                else:
                    value = field['eval'] or ' '.join(''.join(field['text']).split())
                open_record[0]['fields'][field['name']] = value
        elif open_record and open_record[0]['depth'] == depth:
            records.append(open_record.pop())

    parser = xml.parsers.expat.ParserCreate()
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = characters
    try:
        parser.Parse(content, True)
    except xml.parsers.expat.ExpatError as exc:
        raise ParseError(exc.lineno) from exc
    return records


def scan(values, wanted):
    """Parse the XML files whose bytes pass `wanted`: (records, skipped files).

    Every record gets `module` and `path` (relative to its addons root).
    """
    model_info = sibling('model_info')
    records, skipped = [], []
    for module, root, directory in model_info.modules(values):
        for path in files_of(directory, '.xml'):
            try:
                content = path.read_bytes()
            except OSError:
                continue
            if not wanted(content):
                continue
            relative = str(path.relative_to(root))
            try:
                found = parse_records(content, module)
            except ParseError as exc:
                skipped.append((module, f'{relative} (XML error at line {exc.line})'))
                continue
            for record in found:
                record['module'], record['path'] = module, relative
                records.append(record)
    return records, skipped


def owns(record):
    """Whether the record is written by the module its XML id belongs to: the definition, when
    other modules also write on the id."""
    return record['module'] == record['id'].split('.', 1)[0]


def is_view(record):
    return record['model'] == 'ir.ui.view'


def view_type(record):
    """The type of a base view: qweb for a template, else the root tag of its arch."""
    return 'qweb' if record['tag'] == 'template' else (record['arch_root'] or 'unknown')


def location(record):
    return f'{record["path"]}:{record["line"]}'


def plural(count, noun):
    return f'{count} {noun}' + ('' if count == 1 else 's')


def details(record):
    """` (2 changes, mode=primary)` for an extension, empty when there is nothing to say."""
    parts = []
    if record['changes']:
        parts.append(plural(record['changes'], 'change'))
    if record['fields'].get('mode'):
        parts.append(f'mode={record["fields"]["mode"]}')
    return f' ({", ".join(parts)})' if parts else ''


def base_line(record):
    text = f'{view_type(record)} {record["id"]} {location(record)}'
    for key in ('priority', 'mode'):
        if record['fields'].get(key):
            text += f' {key}={record["fields"][key]}'
    return text


def base_order(record):
    kind = view_type(record)
    rank = TYPE_ORDER.index(kind) if kind in TYPE_ORDER else len(TYPE_ORDER)
    priority = record['fields'].get('priority', '')
    return (rank, kind, int(priority) if priority.isdigit() else 16, record['id'])


def skipped_lines(skipped):
    """`skipped:` lines for files that are not well-formed XML, at most SKIPPED_CAP."""
    lines = [f'skipped: {text}' for _module, text in skipped[:SKIPPED_CAP]]
    if len(skipped) > SKIPPED_CAP:
        lines.append(f'skipped: +{len(skipped) - SKIPPED_CAP} more files')
    return lines


def view_info(values, model, kind, module):
    encoded = model.encode()
    records, skipped = scan(values, lambda content: encoded in content or b'inherit_id' in content)
    views = {}
    for record in records:
        # The owning module's record is the view; without one, the first in scan order.
        if is_view(record) and (record['id'] not in views or (owns(record) and not owns(views[record['id']]))):
            views[record['id']] = record

    def model_of(record, seen=()):
        if record['fields'].get('model'):
            return record['fields']['model']
        parent = views.get(record['fields'].get('inherit_id', ''))
        if parent is None or parent['id'] in seen:
            return None
        return model_of(parent, seen + (record['id'],))

    selected = [record for record in views.values() if model_of(record) == model]
    chosen = {record['id'] for record in selected}
    bases, children, unresolved = [], {}, []
    for record in selected:
        parent = record['fields'].get('inherit_id')
        if not parent:
            bases.append(record)
        elif parent in chosen:
            children.setdefault(parent, []).append(record)
        elif parent in views:
            bases.append(record)  # extends a view of another model: shown as its own base
        else:
            unresolved.append(record)
    bases.sort(key=base_order)
    if kind:
        bases = [record for record in bases if view_type(record) == kind]
        unresolved = []

    def subtree(record, depth):
        for child in sorted(children.get(record['id'], []), key=lambda item: item['id']):
            yield child, depth
            yield from subtree(child, depth + 1)

    def tree_lines(record):
        """The extensions below a view, at most EXTENSION_CAP, with the count of the rest."""
        items = list(subtree(record, 1))
        shown = [f'{"  " * depth}+ {item["id"]} {location(item)}{details(item)}' for item, depth in items[:EXTENSION_CAP]]
        if len(items) > EXTENSION_CAP:
            shown.append(f'  +{len(items) - EXTENSION_CAP} more extensions (narrow with --module)')
        return shown

    # Views that extend an unresolved extension hang below it, so none is dropped.
    extensions = [item for root in bases + unresolved for item in subtree(root, 1)]
    lines = []
    if module:
        own_bases = [record for record in bases if record['module'] == module]
        own_extensions = sorted((record for record, _depth in extensions if record['module'] == module),
                                key=lambda record: (record['path'], record['line']))
        unresolved = [record for record in unresolved if record['module'] == module]
        skipped = [item for item in skipped if item[0] == module]
        if not own_bases and not own_extensions and not unresolved:
            print(f'no views found for model: {model} (module {module})', file=sys.stderr)
            return 1
        lines.append(f'model: {model} — module {module}: {plural(len(own_bases), "view")}, '
                     f'{plural(len(own_extensions), "extension")}')
        lines += [base_line(record) for record in own_bases]
        lines += [f'+ {record["id"]} {location(record)}{details(record)} extends {record["fields"]["inherit_id"]}'
                  for record in own_extensions[:EXTENSION_CAP]]
        if len(own_extensions) > EXTENSION_CAP:
            lines.append(f'+{len(own_extensions) - EXTENSION_CAP} more extensions')
        lines += [f'unresolved: {record["id"]} {location(record)} inherits {record["fields"]["inherit_id"]}'
                  for record in unresolved[:UNRESOLVED_CAP]]
    else:
        if not bases and not unresolved:
            suffix = f' (type {kind})' if kind else ''
            print(f'no views found for model: {model}{suffix}', file=sys.stderr)
            return 1
        lines.append(f'model: {model} — {plural(len(bases), "view")}, {plural(len(extensions), "extension")}')
        for base in bases:
            lines.append(base_line(base))
            lines += tree_lines(base)
        for record in unresolved[:UNRESOLVED_CAP]:
            lines.append(f'unresolved: {record["id"]} {location(record)} inherits {record["fields"]["inherit_id"]}')
            lines += tree_lines(record)
    if len(unresolved) > UNRESOLVED_CAP:
        lines.append(f'unresolved: +{len(unresolved) - UNRESOLVED_CAP} more')
    print('\n'.join(lines + skipped_lines(skipped)))
    return 0


def references(values, xml_id, definitions):
    """`path:line` of every text reference to the id, definitions and inherit_id references aside."""
    model_info = sibling('model_info')
    owner, name = xml_id.split('.', 1)
    full = re.compile(r'(?<![\w.])' + re.escape(xml_id) + r'(?![\w.])')
    short = re.compile(r'''(?:\b(?:ref|parent|action)=["']|%\(|\bref\(["'])''' + re.escape(name) + r'''(?=["')])''')
    groups = re.compile(r'''\bgroups=["']([^"']*)["']''')

    def in_groups(line):
        # groups="a,b": a comma-separated list, each item optionally negated with `!`.
        return any(item.strip().lstrip('!') == name
                   for match in groups.finditer(line) for item in match.group(1).split(','))
    needle = name.encode()
    defined = {(record['path'], record['line']) for record in definitions}
    found = []
    for module, root, directory in model_info.modules(values):
        for path in files_of(directory, REFERENCE_SUFFIXES):
            try:
                content = path.read_bytes()
            except OSError:
                continue
            if needle not in content:
                continue
            relative = str(path.relative_to(root))
            for number, line in enumerate(content.decode('utf-8', 'replace').splitlines(), 1):
                if (relative, number) in defined:
                    continue
                if relative.endswith('.xml') and 'inherit_id' in line:
                    # The inherited view is already under "extended by": leave only that
                    # reference out, so another one on the same line still counts.
                    # (the ref of the inherit_id field, wherever it stands in the tag).
                    line = INHERIT_FIELD.sub(lambda tag: REF_ATTRIBUTE.sub(' ', tag.group(0)),
                                             INHERIT_ATTRIBUTE.sub(' ', line))
                local = module == owner and (short.search(line) or in_groups(line) or (
                    # A CSV cell holds the bare name (ir.model.access.csv group and model columns).
                    relative.endswith('.csv') and name in (cell.strip().strip('"') for cell in line.split(','))))
                if full.search(line) or local:
                    found.append(f'{relative}:{number}')
    return found


def xmlid_info(values, xml_id):
    name = xml_id.split('.', 1)[1].encode()
    records, skipped = scan(values, lambda content: name in content)
    definitions = [record for record in records if record['id'] == xml_id]
    # The owning module's record first (stable for the rest): the others write on it.
    definitions.sort(key=lambda record: not owns(record))
    if not definitions:
        # A file that could not be parsed may be the one that defines it: name those files.
        print('\n'.join([f'xml id not found: {xml_id}'] + skipped_lines(skipped)), file=sys.stderr)
        return 1
    record = definitions[0]
    kind = 'record ' + record['model'] if record['tag'] == 'record' else record['tag']
    lines = [f'xml id: {xml_id}', f'defined: {location(record)} {kind}']
    fields = dict(record['fields'])
    if is_view(record) and not fields.get('inherit_id'):
        # A base view: its type goes after the model, before whatever else it sets.
        ordered = {}
        for key, value in fields.items():
            ordered[key] = value
            if key == 'model':
                ordered['type'] = view_type(record)
        ordered.setdefault('type', view_type(record))
        fields = ordered
    shown = list(fields.items())[:FIELD_CAP]
    for key, value in shown:
        text = value if len(value) <= VALUE_CHARS else value[:VALUE_CHARS - 1] + '…'
        lines.append(f'  {key}: {text}')
    if len(fields) > FIELD_CAP:
        lines.append(f'  +{len(fields) - FIELD_CAP} more fields')
    lines += [f'also written in: {location(other)}' for other in definitions[1:REWRITE_CAP + 1]]
    if len(definitions) > REWRITE_CAP + 1:
        lines.append(f'also written in: +{len(definitions) - REWRITE_CAP - 1} more files')
    extensions = [other for other in records
                  if is_view(other) and other['fields'].get('inherit_id') == xml_id and other['id'] != xml_id]
    if extensions:
        lines.append(f'extended by ({len(extensions)}):')
        lines += [f'  {other["id"]} {location(other)}' for other in extensions[:REFERENCE_CAP]]
        if len(extensions) > REFERENCE_CAP:
            lines.append(f'  +{len(extensions) - REFERENCE_CAP} more')
    found = references(values, xml_id, definitions)
    if found:
        lines.append(f'referenced by ({len(found)}):')
        lines += [f'  {item}' for item in found[:REFERENCE_CAP]]
        if len(found) > REFERENCE_CAP:
            lines.append(f'  +{len(found) - REFERENCE_CAP} more')
    print('\n'.join(lines + skipped_lines(skipped)))
    return 0


def parse_view_arguments(arguments):
    """(model, type or None, module or None), or None for a usage error."""
    if not arguments or arguments[0].startswith('-'):
        return None
    model, kind, module, index = arguments[0], None, None, 1
    while index < len(arguments):
        option = arguments[index]
        if index + 1 >= len(arguments):
            return None
        if option == '--type' and kind is None:
            kind = arguments[index + 1]
        elif option == '--module' and module is None:
            module = arguments[index + 1]
        else:
            return None
        index += 2
    return model, kind, module


def load_values():
    """The project's resolved configuration, or an error message."""
    config = sibling('config')
    root = config.selected_root()
    if root is None:
        return None, config.PROJECT_ROOT_REQUIRED
    try:
        return config.load(root), None
    except config.InvalidConfig as exc:
        return None, str(exc)


def main(arguments):
    command, arguments = (arguments[0], arguments[1:]) if arguments else ('', [])
    if command not in ('view', 'xmlid'):
        return fail('Usage: xml_info.py view|xmlid ...')
    if arguments in (['--help'], ['-h']):
        print(VIEW_HELP if command == 'view' else XMLID_HELP, end='')
        return 0
    if command == 'view':
        parsed = parse_view_arguments(arguments)
        if parsed is None:
            return fail(VIEW_USAGE)
        model, kind, module = parsed
        if not MODEL.fullmatch(model):
            return fail('Invalid model name: use lowercase dotted words such as sale.order.')
        if kind is not None and not VIEW_TYPE.fullmatch(kind):
            return fail('Invalid view type.')
        if module is not None and not MODULE.fullmatch(module):
            return fail('Module must use only letters, numbers, and underscores.')
    else:
        if len(arguments) != 1 or arguments[0].startswith('-'):
            return fail(XMLID_USAGE)
        if not XML_ID.fullmatch(arguments[0]):
            return fail('Invalid XML id: use <module>.<name>, such as sale.view_order_form.')
    values, error = load_values()
    if error:
        return fail(error)
    if command == 'view':
        return view_info(values, model, kind, module)
    return xmlid_info(values, arguments[0])


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
