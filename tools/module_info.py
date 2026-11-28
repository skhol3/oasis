#!/usr/bin/env python3
"""A one-screen static map of one Odoo module from source, without starting Odoo.

Python files are parsed with ast, XML files with expat and CSV files with csv: nothing is
imported or executed, and no environment, service or database is used. The module scan and the
parsers are model_info.py's and xml_info.py's.
"""
import ast
import csv
import importlib.util
import io
from pathlib import Path
import posixpath
import re
import sys

USAGE = 'Usage: module-info <module> [--section <name>]'
SECTIONS = ('models', 'views', 'menus', 'actions', 'security', 'data', 'tests')
HELP = USAGE + '''

Map one Odoo module from source without starting Odoo: its manifest (version, summary or name,
depends, the addons root it was found in), then one section each for
  models    models defined (_name, "_description", transient or abstract, (+_inherit mixins))
            and extended (_inherit without a new _name), with the number of fields each class
            adds or overrides and its file:line
  views     base views per model and type, and the extensions per inherited view (the
            module's own views only)
  menus     the menu tree (name and XML id; `under <id>` for a parent of another module)
  actions   window actions (res_model), server actions, reports, client and URL actions
  security  groups, ir.model.access.csv lines per model (groups with read, write, create,
            unlink flags: rwcu, `-` when not granted; `everyone` without a group; models with
            the same access share a line) and record rules (model and groups, or global); a
            model the module does not name elsewhere is shown as its model XML id
  data      the manifest data and demo files in order, crons (interval and model), XML and CSV
            files on disk that the manifest does not list, and listed files that do not exist
  tests     the files of tests/ with their classes and number of test methods
Paths are relative to the module directory; XML ids of the module itself are shown without the
module prefix. Lists stop at 10 lines (25 names in a comma-separated list) and end with the
count of the rest; --section <name> prints only that section, uncapped.
An XML id written more than once is shown once, with the fields of its writes applied in load
order (the manifest data and demo files in order; document order within a file) and
`(written <n> times)` on actions and crons. Odoo never loads files the manifest does not list:
their writes are ignored for an id written in a listed file, and an id written only in such
files is shown from them (path order) with `(not loaded: file not in manifest)`. With an
unreadable manifest every write counts, in path order, unmarked.
The manifest is the first dict literal of __manifest__.py; without one the header says
`manifest: unreadable (<reason>)` (so does the first line of --section data). `skipped:` names
Python or XML files that could not be parsed.
Scans the same roots as model-info (Odoo source, optional Enterprise source, the workspace's
tooling addon roots; the first module with a name wins; Odoo/Enterprise source test_* modules
are not modules). static/, i18n/, migrations/ and upgrades/ are skipped, and tests/ is read only
for the tests section. Python is parsed with ast, XML with expat and CSV with csv:
nothing is imported or executed, and no environment, service or database is used.
'''
LIST_CAP = 10
NAME_CAP = 25
DESCRIPTION_CHARS = 40
SECTION_ERROR = 'Invalid section: use models, views, menus, actions, security, data or tests.'
ACTION_KINDS = {'ir.actions.act_window': 'window', 'ir.actions.server': 'server', 'ir.actions.report': 'report',
                'ir.actions.client': 'client', 'ir.actions.act_url': 'url'}
GROUP_REF = re.compile(r'''\bref\(\s*["']([^"']+)["']\s*\)''')


def fail(message):
    print('ERROR: ' + message, file=sys.stderr)
    return 2


_spec = importlib.util.spec_from_file_location('oasis_siblings', Path(__file__).with_name('siblings.py'))
_spec.loader.exec_module(siblings := importlib.util.module_from_spec(_spec))
sibling = siblings.loader('oasis_module_info_')


def parse_arguments(arguments):
    """(module, section or None), or None for a usage error."""
    if not arguments or arguments[0].startswith('-'):
        return None
    module, section, index = arguments[0], None, 1
    while index < len(arguments):
        if arguments[index] != '--section' or section is not None or index + 1 >= len(arguments):
            return None
        section = arguments[index + 1]
        index += 2
    return module, section


class Module:
    """Everything module-info reads from one module directory."""

    def __init__(self, name, root, directory, model_info, xml_info):
        self.name, self.root, self.directory = name, root, directory
        self.model_info, self.xml_info = model_info, xml_info
        self.skipped = []
        self.manifest, self.manifest_error = self.read_manifest()
        self.classes = self.read_classes()
        self.records = self.read_records()
        self.known = {entry['model'] for entry in self.classes}
        self.known.update(record['fields'][key] for record in self.records
                          for key in ('model', 'res_model') if record['fields'].get(key))

    def relative(self, path):
        return path.relative_to(self.directory).as_posix()

    def read_manifest(self):
        """(the first top-level dict literal, None) or ({}, why it cannot be read)."""
        try:
            tree = ast.parse((self.directory / '__manifest__.py').read_bytes())
        except SyntaxError as exc:
            return {}, f'Python error at line {exc.lineno}'
        except (OSError, ValueError):
            return {}, 'cannot be read'
        # A leading docstring or another expression comes before the dict in some manifests.
        found = next((node.value for node in tree.body
                      if isinstance(node, ast.Expr) and isinstance(node.value, ast.Dict)), None)
        if found is None:
            return {}, 'no dict literal'
        value = self.model_info.literal(found)
        return (value, None) if isinstance(value, dict) else ({}, 'the dict is not a literal')

    def parse_python(self, path):
        try:
            return ast.parse(path.read_bytes(), filename=str(path))
        except SyntaxError as exc:
            self.skipped.append((self.name, f'{self.relative(path)} (Python error at line {exc.lineno})'))
        except (OSError, ValueError):
            self.skipped.append((self.name, f'{self.relative(path)} (cannot be read)'))
        return None

    def read_classes(self):
        """Model classes in file order: model, kind (definition/extension), flavor, mixins, fields."""
        found = []
        for path in self.model_info.python_files(self.directory):
            tree = self.parse_python(path)
            if tree is None:
                continue
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    entry = self.model_class(node)
                    if entry:
                        entry.update(path=self.relative(path), line=node.lineno)
                        found.append(entry)
        return found

    def model_class(self, node):
        attributes, fields = {}, 0
        for statement in node.body:
            if not (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)):
                continue
            target = statement.targets[0].id
            if target in ('_name', '_inherit', '_description', '_transient'):
                attributes[target] = self.model_info.literal(statement.value)
            elif self.model_info.field_call(statement.value):
                fields += 1
        name = attributes.get('_name') if isinstance(attributes.get('_name'), str) else None
        inherit = self.model_info.as_list(attributes.get('_inherit'))
        if name is None and not inherit:
            return None
        bases = {ast.unparse(base).rsplit('.', 1)[-1] for base in node.bases}
        flavor = ('transient' if 'TransientModel' in bases or attributes.get('_transient') is True
                  else 'abstract' if 'AbstractModel' in bases else '')
        description = attributes.get('_description')
        if name is not None and name not in inherit:
            return {'model': name, 'kind': 'definition', 'flavor': flavor, 'mixins': inherit, 'fields': fields,
                    'description': description if isinstance(description, str) else None}
        model = name or inherit[0]
        return {'model': model, 'kind': 'extension', 'flavor': flavor, 'fields': fields, 'description': None,
                'mixins': [item for item in inherit if item != model]}

    def read_records(self):
        records = []
        for path in self.xml_info.files_of(self.directory, '.xml'):
            try:
                found = self.xml_info.parse_records(path.read_bytes(), self.name)
            except OSError:
                continue
            except self.xml_info.ParseError as exc:
                self.skipped.append((self.name, f'{self.relative(path)} (XML error at line {exc.line})'))
                continue
            for record in found:
                record['module'], record['path'] = self.name, self.relative(path)
                records.append(record)
        return self.merge(records)

    def merge(self, records):
        """One record per XML id, listed where its first loaded write stands in file-path order,
        with the fields of its writes applied in load order and `writes` their count.

        Load order: the manifest data and demo files in their order; within a file, document
        order. Odoo never loads a file the manifest does not list, so such writes are ignored when
        the id has a write in a listed file. An id written only in unlisted files is kept (its
        writes in path order) with `unloaded` set. With an unreadable manifest nothing is known to
        be listed or unlisted: every write counts, in path order, and none is marked.
        """
        listed = self.manifest_files('data') + self.manifest_files('demo')
        rank = {path: index for index, path in reversed(list(enumerate(listed)))}
        writes = {}
        for record in records:
            writes.setdefault(record['id'], []).append(record)
        loaded = {}
        for key, group in writes.items():
            kept = [item for item in group if item['path'] in rank]
            loaded[key] = sorted(kept, key=lambda item: rank[item['path']]) if kept else group  # stable
        merged = []
        for record in records:
            ordered = loaded[record['id']]
            if ordered[0] is not record:
                continue
            result = dict(record, fields={}, writes=len(ordered),
                          unloaded=self.manifest_error is None and record['path'] not in rank)
            for write in ordered:
                result['fields'].update(write['fields'])
                for key in ('model', 'arch_root'):
                    if write[key]:
                        result[key] = write[key]
            merged.append(result)
        return merged

    # -- helpers -------------------------------------------------------------------------------

    def short(self, xml_id):
        """An XML id as the module's own files write it: without the prefix when it is its own."""
        prefix = self.name + '.'
        return xml_id[len(prefix):] if xml_id.startswith(prefix) else xml_id

    def model_of_ref(self, value):
        """The model a model_id reference names (model_<model with _>), when the module knows it."""
        name = value.split('.', 1)[-1]
        if name.startswith('model_'):
            for model in sorted(self.known):
                if model.replace('.', '_') == name[len('model_'):]:
                    return model
        return self.short(value) if value else '?'

    def of_model(self, model):
        return [record for record in self.records if record['tag'] == 'record' and record['model'] == model]

    def manifest_files(self, key):
        listed = self.manifest.get(key)
        if not isinstance(listed, (list, tuple)):
            return []
        return [posixpath.normpath(item) for item in listed if isinstance(item, str)]


def plural(count, noun, many=None):
    return f'{count} {noun if count == 1 else many or noun + "s"}'


def capped(lines, section, cap):
    if cap is None or len(lines) <= cap:
        return lines
    return lines[:cap] + [f'  +{len(lines) - cap} more (--section {section})']


def joined(names, section, cap):
    if cap is not None and len(names) > cap:
        return ', '.join(names[:cap]) + f', +{len(names) - cap} more (--section {section})'
    return ', '.join(names)


def written(record):
    return f' (written {record["writes"]} times)' if record['writes'] > 1 else ''


def unloaded(record):
    """The mark of an id that only files the manifest does not list write."""
    return ' (not loaded: file not in manifest)' if record['unloaded'] else ''


def quoted(text):
    if not isinstance(text, str) or not text:
        return ''
    text = ' '.join(text.split())
    return ' "' + (text if len(text) <= DESCRIPTION_CHARS else text[:DESCRIPTION_CHARS - 1] + '…') + '"'


def models_section(module, cap):
    defined = [entry for entry in module.classes if entry['kind'] == 'definition']
    extended = [entry for entry in module.classes if entry['kind'] == 'extension']
    if not defined and not extended:
        return ['models: none']

    def line(entry, prefix):
        text = f'  {prefix}{entry["model"]}{quoted(entry["description"])}'
        if entry['flavor']:
            text += ' ' + entry['flavor']
        if entry['mixins']:
            text += f' (+{", ".join(entry["mixins"])})'
        return f'{text}: {plural(entry["fields"], "field")}, {entry["path"]}:{entry["line"]}'

    return ([f'models: {len(defined)} defined, {len(extended)} extended']
            + capped([line(entry, '') for entry in defined], 'models', cap)
            + capped([line(entry, 'extends ') for entry in extended], 'models', cap))


def views_section(module, cap):
    xml_info = module.xml_info
    views = [record for record in module.records if xml_info.is_view(record) and xml_info.owns(record)]
    bases, extensions = {}, {}
    for record in views:
        parent = record['fields'].get('inherit_id')
        if parent:
            extensions.setdefault(parent, []).append(record)
        else:
            bases.setdefault(record['fields'].get('model', ''), []).append(record)
    if not bases and not extensions:
        return ['views: none']
    base_lines = []
    for model in sorted(bases, key=lambda name: (name == '', name)):
        listed = [f'{xml_info.view_type(record)} {module.short(record["id"])}{unloaded(record)}'
                  for record in sorted(bases[model], key=xml_info.base_order)]
        base_lines.append(f'  {model or "(no model)"}: {joined(listed, "views", NAME_CAP if cap else None)}')
    extension_lines = []
    for parent in sorted(extensions):
        listed = [module.short(record['id']) + unloaded(record) for record in extensions[parent]]
        extension_lines.append(f'  extends {module.short(parent)} ({len(listed)}): '
                               f'{joined(listed, "views", NAME_CAP if cap else None)}')
    total = sum(len(items) for items in bases.values())
    count = sum(len(items) for items in extensions.values())
    return ([f'views: {total} base, {plural(count, "extension")}']
            + capped(base_lines, 'views', cap) + capped(extension_lines, 'views', cap))


def menus_section(module, cap):
    menus = [record for record in module.records if record['tag'] == 'menuitem']
    if not menus:
        return ['menus: none']
    ids = {record['id'] for record in menus}
    children = {}
    for record in menus:
        children.setdefault(record['fields'].get('parent'), []).append(record)
    lines = []

    def walk(record, depth):
        name = record['fields'].get('name')
        text = f'{"  " * depth}{name} ({module.short(record["id"])})' if name else f'{"  " * depth}{module.short(record["id"])}'
        parent = record['fields'].get('parent')
        if depth == 1 and parent:
            text += f' under {module.short(parent)}'
        lines.append(text + unloaded(record))
        for child in children.get(record['id'], []):
            walk(child, depth + 1)

    for record in menus:
        if record['fields'].get('parent') not in ids:
            walk(record, 1)
    return [f'menus: {len(menus)}'] + capped(lines, 'menus', cap)


def actions_section(module, cap):
    lines = []
    for record in module.records:
        kind = ACTION_KINDS.get(record['model']) if record['tag'] == 'record' else None
        if not kind:
            continue
        fields = record['fields']
        if kind == 'window':
            model = fields.get('res_model', '?')
        elif kind == 'server':
            model = module.model_of_ref(fields.get('model_id', ''))
        elif kind == 'report':
            model = fields.get('model', '?')
        else:
            model = fields.get('tag', '') if kind == 'client' else fields.get('url', '')
        text = f'  {kind} {module.short(record["id"])}: {model}{quoted(fields.get("name"))}'
        if kind == 'report' and fields.get('report_type'):
            text += ' ' + fields['report_type']
        lines.append(text + written(record) + unloaded(record))
    if not lines:
        return ['actions: none']
    return [f'actions: {len(lines)}'] + capped(lines, 'actions', cap)


def access_lines(module):
    """(model, group, flags) per ir.model.access.csv line, in file order."""
    rows = []
    for path in module.xml_info.files_of(module.directory, '.csv'):
        if path.name != 'ir.model.access.csv':
            continue
        try:
            reader = csv.DictReader(io.StringIO(path.read_text(encoding='utf-8', errors='replace')))
            for row in reader:
                row = {key.replace('/', ':').strip(): (value or '').strip() for key, value in row.items() if key}
                model = module.model_of_ref(module.xml_info.qualify(module.name, row.get('model_id:id', '')))
                group = row.get('group_id:id', '')
                flags = ''.join(letter if row.get(f'perm_{name}', '') in ('1', 'True', 'true') else '-'
                                for letter, name in (('r', 'read'), ('w', 'write'), ('c', 'create'), ('u', 'unlink')))
                rows.append((model, module.short(module.xml_info.qualify(module.name, group)) if group else 'everyone',
                             flags))
        except (OSError, csv.Error):
            module.skipped.append((module.name, f'{module.relative(path)} (CSV error)'))
    return rows


def security_section(module, cap):
    groups = [f'  group {module.short(record["id"])}{quoted(record["fields"].get("name"))}{unloaded(record)}'
              for record in module.of_model('res.groups')]
    rows = access_lines(module)
    per_model = {}
    for model, group, flags in rows:
        per_model.setdefault(model, []).append(f'{group} {flags}')
    # Models with the same groups and flags share one line.
    shared = {}
    for model, items in per_model.items():
        shared.setdefault(', '.join(items), []).append(model)
    names = None if cap is None else NAME_CAP
    access = [f'  access {joined(models, "security", names)}: {grants}' for grants, models in shared.items()]
    rules = []
    for record in module.of_model('ir.rule'):
        model = module.model_of_ref(record['fields'].get('model_id', ''))
        names = [module.short(module.xml_info.qualify(module.name, item))
                 for item in GROUP_REF.findall(record['fields'].get('groups', ''))]
        rules.append(f'  rule {module.short(record["id"])}: {model}, '
                     + (f'groups {", ".join(names)}' if names else 'global') + unloaded(record))
    if not groups and not rows and not rules:
        return ['security: none']
    return ([f'security: {plural(len(rows), "access rule")}, {plural(len(rules), "record rule")}, '
             f'{plural(len(groups), "group")}']
            + capped(groups, 'security', cap) + capped(access, 'security', cap) + capped(rules, 'security', cap))


def data_section(module, cap):
    data, demo = module.manifest_files('data'), module.manifest_files('demo')
    names = None if cap is None else NAME_CAP
    crons = []
    for record in module.of_model('ir.cron'):
        fields = record['fields']
        text = f'  cron {module.short(record["id"])}{quoted(fields.get("name"))}:'
        if fields.get('interval_number') or fields.get('interval_type'):
            text += f' every {fields.get("interval_number", "1")} {fields.get("interval_type", "?")},'
        crons.append(f'{text} {module.model_of_ref(fields.get("model_id", ""))}{written(record)}{unloaded(record)}')
    listed = set(data) | set(demo)
    on_disk = [module.relative(path) for path in module.xml_info.files_of(module.directory, ('.xml', '.csv'))]
    unlisted = [path for path in on_disk if path not in listed]
    present = set(on_disk)
    missing = [path for path in data + demo if path not in present and not (module.directory / path).is_file()]
    if not data and not demo and not crons and not unlisted and not missing:
        return ['data: none']
    header = f'data: {plural(len(data), "data file")}, {len(demo)} demo, {plural(len(crons), "cron")}'
    if unlisted:
        header += f', {len(unlisted)} not in manifest'
    if missing:
        header += f', {len(missing)} missing'
    lines = [header]
    if data:
        lines.append('  data: ' + joined(data, 'data', names))
    if demo:
        lines.append('  demo: ' + joined(demo, 'data', names))
    lines += capped(crons, 'data', cap)
    if unlisted:
        lines.append('  not in manifest: ' + joined(unlisted, 'data', names))
    if missing:
        lines.append('  missing on disk: ' + joined(missing, 'data', names))
    return lines


def tests_section(module, cap):
    directory = module.directory / 'tests'
    lines, classes, methods = [], 0, 0
    paths = sorted(module.xml_info.files_of(directory, '.py')) if directory.is_dir() else []
    for path in paths:
        if path.name == '__init__.py':
            continue
        tree = module.parse_python(path)
        if tree is None:
            continue
        described = []
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            count = sum(1 for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name.startswith('test'))
            classes += 1
            methods += count
            described.append(f'{node.name} ({plural(count, "test")})' if count else node.name)
        if described or path.name.startswith('test_'):
            lines.append(f'  {module.relative(path)}: ' + (', '.join(described) or 'no classes'))
    if not lines:
        return ['tests: none']
    return ([f'tests: {plural(len(lines), "file")}, {plural(classes, "class", "classes")}, '
             f'{plural(methods, "test method")}'] + capped(lines, 'tests', cap))


RENDER = {'models': models_section, 'views': views_section, 'menus': menus_section, 'actions': actions_section,
          'security': security_section, 'data': data_section, 'tests': tests_section}


def header(module):
    manifest = module.manifest
    text = f'module: {module.name}'
    if isinstance(manifest.get('version'), str):
        text += ' ' + manifest['version']
    title = next((manifest[key] for key in ('summary', 'name')
                  if isinstance(manifest.get(key), str) and manifest[key].strip()), None)
    if title:
        text += ' — ' + ' '.join(title.split())
    if module.manifest_error:
        # Not an empty manifest: say why there is no version, title or depends to show.
        return [text, f'manifest: unreadable ({module.manifest_error})', f'root: {module.root}']
    depends = [item for item in manifest.get('depends', []) if isinstance(item, str)] \
        if isinstance(manifest.get('depends'), (list, tuple)) else []
    return [text, 'depends: ' + (', '.join(depends) or 'none'), f'root: {module.root}']


def main(arguments):
    if arguments in (['--help'], ['-h']):
        print(HELP, end='')
        return 0
    parsed = parse_arguments(arguments)
    if parsed is None:
        return fail(USAGE)
    name, section = parsed
    model_info, xml_info = sibling('model_info'), sibling('xml_info')
    if not model_info.MODULE.fullmatch(name):
        return fail('Module must use only letters, numbers, and underscores.')
    if section is not None and section not in SECTIONS:
        return fail(SECTION_ERROR)
    values, error = xml_info.load_values()
    if error:
        return fail(error)
    found = next(((root, directory) for module, root, directory in model_info.modules(values)
                  if module == name), None)
    if found is None:
        print(f'module not found: {name}', file=sys.stderr)
        return 1
    module = Module(name, *found, model_info, xml_info)
    if section:
        lines = RENDER[section](module, None)
        if section == 'data' and module.manifest_error:
            # Without the header, say why every file shows as not in the manifest.
            lines.insert(0, f'manifest: unreadable ({module.manifest_error})')
    else:
        lines = header(module)
        for key in SECTIONS:
            lines += RENDER[key](module, LIST_CAP)
    print('\n'.join(lines + module.xml_info.skipped_lines(module.skipped)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
