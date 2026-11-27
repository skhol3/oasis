"""v0.18.0 S1, S7, S8 and v0.19.0 S2, S3, S4: the task recipes of the code skills, one source each under
`recipes/`, rendered per series by tools/render_recipes.py and checked as the files an agent reads."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import ast
import csv
import importlib.util
import io
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / 'tools/render_recipes.py'


def load(name):
    spec = importlib.util.spec_from_file_location(f'recipes_test_{name}', ROOT / 'tools' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


odoo_versions = load('odoo_versions')

# odd/tasks/v0.18.0.md L5: the recipe files of each code skill.
RECIPES = {
    'odoo-backend': ('module.md', 'model.md', 'compute-constraint.md', 'inheritance.md'),
    'odoo-views-frontend': ('views.md', 'actions-menus.md', 'view-inheritance.md', 'owl-component.md'),
    'odoo-security': ('access.md', 'record-rules.md'),
    'odoo-testing': ('model-tests.md', 'tours.md'),
}
# v0.19.0 S2: the last section is the one the renderer writes, `## Changed from <previous series>`.
SECTIONS = ('When to use', 'Files', 'Example', 'Mistakes', 'Verify')
CHANGED = re.compile(r'Changed from (earlier series|\d+\.0)')
OLDEST = 'Oldest supported series.'
FENCE = re.compile(r'^```([a-z]*)\n(.*?)^```$', re.M | re.S)


def series_key(series):
    return tuple(int(part) for part in series.split('.'))


def ascending():
    return sorted(odoo_versions.supported(), key=series_key)


def sections(text):
    """`## ` sections outside fenced blocks in order, as {title: body}; bodies keep their code."""
    found, title, fence = {}, None, False
    for line in text.splitlines(keepends=True):
        if line.startswith('```'):
            fence = not fence
        elif not fence and (match := re.match(r'## (.+)$', line)):
            title = match[1].strip()
            found[title] = ''
            continue
        if title is not None:
            found[title] += line
    return found


def snippet_problems(language, code):
    try:
        if language == 'python':
            ast.parse(code)
        elif language == 'xml':
            ElementTree.fromstring(code)
        elif language == 'csv':
            rows = list(csv.reader(io.StringIO(code)))
            if not rows or len({len(row) for row in rows}) != 1:
                return ['csv rows differ in length']
    except (SyntaxError, ElementTree.ParseError) as error:
        return [f'{language}: {error}']
    return []


def rule_problems(mistakes):
    """S3: the Mistakes section holds rules, each a `### <rule>` heading with `Why:` and `Exceptions:`
    lines and at least two fenced blocks (the bad form, then the good one)."""
    rules, fence = {}, False
    for line in mistakes.splitlines(keepends=True):
        if line.startswith('```'):
            fence = not fence
        elif not fence and (match := re.match(r'### (.+)$', line)):
            rules[match[1].strip()] = ''
            continue
        if rules:
            rules[next(reversed(rules))] += line
    if not rules:
        return ['no mistake rule']
    problems = []
    for title, body in rules.items():
        outside = FENCE.sub('', body)
        if not re.search(r'^Why: \S', outside, re.M):
            problems.append(f'rule {title}: no Why')
        if not re.search(r'^Exceptions: \S', outside, re.M):
            problems.append(f'rule {title}: no Exceptions')
        if len(FENCE.findall(body)) < 2:
            problems.append(f'rule {title}: no bad and good blocks')
    return problems


def changed_problems(title, body, listed):
    """S2: the generated last section: the oldest series says so, a later one names its previous series
    and lists what differs from it, or says nothing does."""
    previous = CHANGED.fullmatch(title)[1]
    if previous == 'earlier series':
        return [] if body.strip() == OLDEST else ['changed-from body']
    if not listed or any(series_key(previous) >= series_key(series) for series in listed):
        return [f'changed from {previous}']
    lines = [line for line in body.strip().splitlines() if line.strip()]
    if lines == [f'No change from {previous}.'] or (lines and all(line.startswith('- ') for line in lines)):
        return []
    return ['changed-from body']


def recipe_problems(text, supported):
    """What a rendered recipe misses: its sections (S2), parsable snippets (v0.18.0 S7), its series'
    `Checked against:` and official page (v0.18.0 S8) and the rules of its Mistakes (S3)."""
    problems = []
    found = sections(text)
    titles = tuple(found)
    if titles[:-1] != SECTIONS or not titles or not CHANGED.fullmatch(titles[-1]):
        problems.append(f'sections {list(found)}')
    checked = re.search(r'^Checked against: (.+)\.$', text, re.M)
    listed = [item.strip() for item in checked[1].split(',')] if checked else []
    problems += [f'not checked against {series}' for series in supported if series not in listed]
    docs = re.search(r'^Official docs: (.+)$', text, re.M)
    pages = re.findall(r'https://www\.odoo\.com/documentation/(\d+\.0)/\S+', docs[1]) if docs else []
    problems += [f'no official {series} page' for series in supported if series not in pages]
    blocks = FENCE.findall(text)
    if not any(language in ('python', 'xml', 'csv', 'javascript') for language, _ in blocks):
        problems.append('no example block')
    for language, code in blocks:
        problems += snippet_problems(language, code)
    if 'Mistakes' in found:
        problems += rule_problems(found['Mistakes'])
    if titles and CHANGED.fullmatch(titles[-1]):
        problems += changed_problems(titles[-1], found[titles[-1]], listed)
    return problems


LABEL = re.compile(r'^`(library/[\w./-]+)`')


def shared_copy_problems(texts):
    """S1: a file several recipes show (labelled `library/<path>` on the line before its block) is the
    same copy everywhere, so following one recipe never leaves another's manifest or CSV stale."""
    copies = {}
    for name, text in texts.items():
        for match in FENCE.finditer(text):
            before = [line for line in text[:match.start()].splitlines() if line.strip()]
            label = LABEL.match(before[-1]) if before else None
            if label:
                copies.setdefault(label[1], {}).setdefault(match[2], []).append(name)
    return sorted(path for path, versions in copies.items() if len(versions) > 1)


recipe_module = load('recipe_module')
# Files that list the entries of every piece (module.md gives them final): an agent building one piece keeps
# that piece's entries, so the references in them are not the recipe's own.
INDEX = re.compile(r'library/(?:__manifest__\.py|(?:[\w/]+/)?__init__\.py|security/ir\.model\.access\.csv)$')
BASE = ('odoo-backend/module.md', 'odoo-backend/model.md')
TOKEN = re.compile(r'\blibrary\.(\w+)')
XML_REFS = re.compile(r'''\b(?:ref|parent|action)="([\w.]+)"|\bref\(\s*['"]([\w.]+)['"]|\bgroups="([\w.,!-]+)"''')


def labelled_files(text):
    """{library/<path>: content} of the blocks a rendered recipe labels (tools/recipe_module.py label_of)."""
    files = {}
    for match in FENCE.finditer(text):
        label = recipe_module.label_of(text, match.start())
        if label:
            files.setdefault(label, match[2])
    return files


def defined_names(files):
    """What labelled files define: `library.<model>` and `model_<model>` per `_name`, the fields of the Python
    classes, the XML ids (`library.<id>`), Owl template names and odoo.define module names."""
    names = set()
    for path, content in files.items():
        if path.endswith('.py'):
            for model in re.findall(r'''^\s+_name = ['"]([\w.]+)['"]''', content, re.M):
                names |= {model, 'library.model_' + model.replace('.', '_')}
            names |= {'field ' + field for field in re.findall(r'^\s+(\w+) = fields\.\w+\(', content, re.M)}
        elif path.endswith('.xml'):
            names |= {'library.' + xml_id for xml_id in re.findall(r'\bid="(\w+)"', content)}
            names |= set(re.findall(r'\bt-name="([\w.]+)"', content))
        names |= set(re.findall(r'''\bodoo\.define\(\s*['"]([\w.]+)['"]''', content))
    return names


def used_names(path, content):
    """What a labelled file uses of the module: `library.<name>` tokens, the unprefixed or `library.` XML ids
    of its refs, parents, actions and groups, and the fields its view archs name."""
    used = {match[0] for match in TOKEN.finditer(content)}
    if path.endswith('.xml'):
        for groups in XML_REFS.findall(content):
            for item in ','.join(groups).split(','):
                item = item.strip().lstrip('!-')
                if item and '.' not in item:
                    used.add('library.' + item)
                elif item.startswith('library.'):
                    used.add(item)
        root = ElementTree.fromstring(content)
        for arch in root.iter('field'):
            if arch.get('name') == 'arch':
                used |= {'field ' + node.get('name') for node in arch.iter('field') if node is not arch and node.get('name')}
    return used


def self_containment_problems(texts):
    """S1: a recipe can be built from itself plus module.md and model.md of its series. texts maps
    `<skill>/<recipe>.md` to the rendered recipes of one series. Rule, per recipe:

    - every name a labelled file uses that some recipe of the series defines (a model, a field of a view arch,
      an XML id, an Owl template, an odoo.define module) is defined by a file the recipe, module.md or model.md
      labels; a `library.` name or an unprefixed XML id that no recipe defines is an error too (a typo);
    - every `library/<path>` its `## Files` names is labelled there (module.md, the index, names them all).

    The files INDEX matches (manifest, `__init__.py`, access CSV) list every piece's entries, so the names they
    use are not checked; a name no recipe defines and that is not `library.` (`base.group_user`, `vat`) is
    Odoo's."""
    files = {name: labelled_files(text) for name, text in texts.items()}
    everywhere = defined_names({f'{name}:{path}': content for name, labelled in files.items()
                                for path, content in labelled.items()})
    problems = []
    for name, labelled in files.items():
        available = {**{path: content for base in BASE for path, content in files.get(base, {}).items()}, **labelled}
        defined = defined_names(available)
        for path, content in labelled.items():
            if INDEX.match(path):
                continue
            for used in sorted(used_names(path, content) - defined):
                if used in everywhere:
                    problems.append(f'{name}: {path} uses {used}, which another recipe defines')
                elif not used.startswith('field '):
                    problems.append(f'{name}: {path} uses {used}, which no recipe defines')
        if name not in BASE[:1]:
            listed = re.findall(r'`(library/[\w./-]+)`', sections(texts[name]).get('Files', ''))
            problems += [f'{name}: Files names {path}, which it does not show'
                         for path in dict.fromkeys(listed) if path not in available]
    return problems


GOOD = '''# Recipe: a model

Checked against: 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html)

## When to use

A new model.

## Files

1. `models/thing.py`

## Example

```python
from odoo import fields, models


class Thing(models.Model):
    _name = 'x.thing'
    name = fields.Char()
```

```xml
<odoo><record id="a" model="ir.ui.view"><field name="arch" type="xml"><list/></field></record></odoo>
```

```csv
id,name,model_id:id
access_x_thing,x.thing,model_x_thing
```

## Mistakes

### Give every model a description

Why: without one the log warns and users see the technical name.

Exceptions: none.

```python
class Thing(models.Model):
    _name = 'x.thing'
```

```python
class Thing(models.Model):
    _name = 'x.thing'
    _description = 'Thing'
```

## Verify

`oasis test-module --compact x_thing`

## Changed from 15.0

- `list`: `<list>`
'''


class RecipeCheckTests(unittest.TestCase):
    """The checker itself, on synthetic rendered recipes: it passes a good one and names each defect."""

    def test_a_complete_recipe_has_no_problem(self):
        self.assertEqual(recipe_problems(GOOD, ['19.0']), [])

    def test_no_change_and_the_oldest_series_are_said_in_the_changed_from_section(self):
        unchanged = GOOD.replace('- `list`: `<list>`', 'No change from 15.0.')
        self.assertEqual(recipe_problems(unchanged, ['19.0']), [])
        oldest = GOOD.replace('## Changed from 15.0\n\n- `list`: `<list>`', f'## Changed from earlier series\n\n{OLDEST}')
        self.assertEqual(recipe_problems(oldest, ['19.0']), [])
        self.assertEqual(recipe_problems(GOOD.replace('- `list`', 'Some text'), ['19.0']), ['changed-from body'])
        self.assertEqual(recipe_problems(GOOD.replace('Changed from 15.0', 'Changed from 19.0'), ['19.0']),
                         ['changed from 19.0'])

    def test_a_file_rendered_for_another_series_is_flagged(self):
        self.assertEqual(recipe_problems(GOOD, ['17.0']), ['not checked against 17.0', 'no official 17.0 page'])

    def test_broken_snippets_are_named(self):
        broken = GOOD.replace('class Thing(models.Model):\n    _name = \'x.thing\'\n    name', 'class Thing(:\n    name')
        broken = broken.replace('<list/>', '<list>').replace('access_x_thing,x.thing,model_x_thing', 'access_x_thing,x.thing')
        problems = recipe_problems(broken, ['19.0'])
        self.assertEqual([problem.split(':')[0] for problem in problems], ['python', 'xml', 'csv rows differ in length'])

    def test_missing_sections_are_named(self):
        text = GOOD.replace('## Verify\n\n`oasis test-module --compact x_thing`\n\n', '')
        self.assertEqual(recipe_problems(text, ['19.0']),
                         ["sections ['When to use', 'Files', 'Example', 'Mistakes', 'Changed from 15.0']"])
        text = GOOD.replace('## Changed from 15.0\n\n- `list`: `<list>`\n', '')
        self.assertEqual(recipe_problems(text, ['19.0']),
                         ["sections ['When to use', 'Files', 'Example', 'Mistakes', 'Verify']"])

    def test_a_mistake_needs_a_rule_with_why_exceptions_and_a_bad_and_a_good_block(self):
        rule = GOOD[GOOD.index('### Give'):GOOD.index('## Verify')]
        self.assertEqual(recipe_problems(GOOD.replace(rule, '- Forgetting the description.\n\n'), ['19.0']),
                         ['no mistake rule'])
        broken = rule.replace('Why: without', 'Because without').replace('Exceptions: none.', '')
        broken = broken[:broken.index('```python\nclass Thing(models.Model):\n    _name = \'x.thing\'\n    _desc')]
        self.assertEqual(recipe_problems(GOOD.replace(rule, broken), ['19.0']), [
            'rule Give every model a description: no Why',
            'rule Give every model a description: no Exceptions',
            'rule Give every model a description: no bad and good blocks'])


class SelfContainmentTests(unittest.TestCase):
    """The S1 check on synthetic rendered recipes: what a piece uses must be shown beside module and model."""

    BOOK = "`library/models/library_book.py`:\n\n```python\nclass Book:\n    _name = 'library.book'\n\n    name = fields.Char()\n```\n"
    GROUPS = '`library/security/library_groups.xml`:\n\n```xml\n<odoo><record id="group_library_user" model="res.groups"/></odoo>\n```\n'
    MENU = ('## Files\n\n1. `library/views/library_menus.xml`\n\n## Example\n\n`library/views/library_menus.xml`:\n\n'
            '```xml\n<odoo><menuitem id="library_menu_root" groups="group_library_user"/></odoo>\n```\n')
    TEST = ("`library/tests/test_ui.py`:\n\n```python\nURL = '/web#action=library.library_book_action'\n```\n")

    def problems(self, **recipes):
        texts = {'odoo-backend/module.md': '# Module\n', 'odoo-backend/model.md': self.BOOK}
        texts.update({name.replace('__', '/') + '.md': text for name, text in recipes.items()})
        return self_containment_problems(texts)

    def test_a_piece_that_shows_what_it_uses_has_no_problem(self):
        self.assertEqual(self.problems(security__access=self.GROUPS, views__menus=self.MENU + self.GROUPS), [])

    def test_an_id_another_recipe_defines_and_an_undefined_one_are_named(self):
        self.assertEqual(self.problems(security__access=self.GROUPS, views__menus=self.MENU, testing__tours=self.TEST), [
            'views/menus.md: library/views/library_menus.xml uses library.group_library_user, which another recipe defines',
            'testing/tours.md: library/tests/test_ui.py uses library.library_book_action, which no recipe defines'])

    def test_a_view_field_or_a_model_of_another_recipe_and_a_file_the_files_section_names_are_named(self):
        partner = "`library/models/res_partner.py`:\n\n```python\nclass Partner:\n    library_card = fields.Char()\n```\n"
        view = ('## Files\n\n1. `library/models/res_partner.py`\n\n## Example\n\n`library/views/res_partner_views.xml`:\n\n'
                '```xml\n<odoo><record id="view" model="ir.ui.view"><field name="name">library.author.form</field>'
                '<field name="arch" type="xml"><field name="vat" position="after"><field name="library_card"/>'
                '</field></field></record></odoo>\n```\n')
        author = "`library/models/library_author.py`:\n\n```python\nclass Author:\n    _name = 'library.author'\n```\n"
        self.assertEqual(self.problems(backend__inheritance=partner + author, views__inheritance=view), [
            'views/inheritance.md: library/views/res_partner_views.xml uses field library_card, which another recipe defines',
            'views/inheritance.md: library/views/res_partner_views.xml uses library.author, which another recipe defines',
            'views/inheritance.md: Files names library/models/res_partner.py, which it does not show'])

    def test_the_index_files_list_every_piece_and_are_not_checked(self):
        manifest = "`library/__init__.py`:\n\n```python\nfrom . import controllers\nX = 'library.anything'\n```\n"
        self.assertEqual(self.problems(backend__extra=manifest), [])


class SharedCopyTests(unittest.TestCase):
    def test_a_stale_copy_of_a_shared_file_is_named(self):
        same = '`library/__init__.py`:\n\n```python\nfrom . import models\n```\n'
        stale = '`library/__init__.py`:\n\n```python\nfrom . import models, wizard\n```\n'
        self.assertEqual(shared_copy_problems({'a.md': same, 'b.md': same}), [])
        self.assertEqual(shared_copy_problems({'a.md': same, 'b.md': stale}), ['library/__init__.py'])


# A synthetic source (recipes/README.md): {docs} is the Official docs map of the series a test renders.
SOURCE = '''# Recipe: a thing

Checked against: every series.

Official docs: {docs}

## When to use

A thing.

<!-- since=19.0 id=intro -->
Only from 19.0.
<!-- end -->

## Files

1. `x.py`

## Example

```python id=model since=15.0
class Old:
    pass
```

```python since=19.0 id=model
class New:
    pass
```

```python id=helper since=17.0
HELPER = 1
```

```xml
<odoo><!-- since=19.0 id=kept --></odoo>
```

## Mistakes

### Name the class

Why: a name says what it is.

Exceptions: none.

```python
class X:
    pass
```

```python
class Thing:
    pass
```

## Verify

`oasis test-module --compact x`
'''


def docs_map(series):
    return ', '.join(f'{item}=https://www.odoo.com/documentation/{item}/a.html' for item in series)


THREE = ['15.0', '17.0', '19.0']
RENDERED_19 = '''# Recipe: a thing

Checked against: 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/a.html)

## When to use

A thing.

Only from 19.0.

## Files

1. `x.py`

## Example

```python
class New:
    pass
```

```python
HELPER = 1
```

```xml
<odoo><!-- since=19.0 id=kept --></odoo>
```

## Mistakes

### Name the class

Why: a name says what it is.

Exceptions: none.

```python
class X:
    pass
```

```python
class Thing:
    pass
```

## Verify

`oasis test-module --compact x`

## Changed from 17.0

- `intro`: Only from 19.0.
- `model`: `class New:`
'''


# A synthetic source whose 19.0 blocks start with lines that say nothing (render_recipes.Variant.label).
LABELS = '''# Recipe: labels

Checked against: every series.

Official docs: {docs}

## Example

```python id=manifest since=15.0
{
    'name': 'Thing',
    'version': '15.0.1.0.0',
}
```

```python id=manifest since=19.0
{
    'name': 'Thing',
    'version': '19.0.1.0.0',
}
```

```xml id=view since=19.0
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <list/>
</odoo>
```

```python id=imports since=19.0
from datetime import timedelta

import json
```

```xml id=template since=19.0
<templates xml:space="preserve">
    <t t-name="x.Thing"/>
</templates>
```
'''


class RenderTests(unittest.TestCase):
    """tools/render_recipes.py on synthetic sources (S2)."""

    @classmethod
    def setUpClass(cls):
        cls.renderer = load('render_recipes')

    def render(self, series, text=None, supported=THREE):
        return self.renderer.render(text or SOURCE.format(docs=docs_map(supported)), series, supported)

    def test_a_series_renders_its_blocks_its_lines_and_what_changed(self):
        self.assertEqual(self.render('19.0'), RENDERED_19)

    def test_a_since_block_applies_until_a_later_block_of_its_id_replaces_it(self):
        old, middle, new = (self.render(series) for series in THREE)
        self.assertIn('class Old:', old)
        self.assertIn('class Old:', middle)
        self.assertNotIn('class Old:', new)
        self.assertIn('class New:', new)
        self.assertNotIn('class New:', middle)
        # Another id is independent: added on 17.0, kept on 19.0, absent before.
        self.assertNotIn('HELPER', old)
        self.assertIn('HELPER = 1', middle)
        self.assertIn('HELPER = 1', new)
        # Without the middle series, 19.0 changes from 15.0 and lists the helper too.
        self.assertTrue(self.render('19.0', supported=['15.0', '19.0']).endswith(
            '## Changed from 15.0\n\n- `intro`: Only from 19.0.\n- `model`: `class New:`\n- `helper`: `HELPER = 1`\n'))

    def test_shared_text_and_blocks_render_unchanged_in_every_series(self):
        for series in THREE:
            with self.subTest(series=series):
                text = self.render(series)
                self.assertIn('```xml\n<odoo><!-- since=19.0 id=kept --></odoo>\n```', text)
                self.assertIn('## Files\n\n1. `x.py`\n', text)
                self.assertNotRegex(text, r'```\w+ ')
                self.assertNotIn('\n\n\n', text)
                self.assertEqual(recipe_problems(text, [series]), [])

    def test_a_prose_block_applies_from_its_series_and_an_empty_one_removes_its_id(self):
        self.assertNotIn('Only from 19.0.', self.render('17.0'))
        removed = SOURCE.replace('```xml', '<!-- since=19.0 id=helper -->\n<!-- end -->\n\n```xml')
        text = self.render('19.0', removed.format(docs=docs_map(THREE)))
        self.assertNotIn('HELPER', text)
        self.assertNotIn('<!--', text.replace('<odoo><!-- since=19.0 id=kept --></odoo>', ''))
        self.assertTrue(text.endswith('- `model`: `class New:`\n- `helper`: removed\n'))

    def test_a_changed_block_is_labelled_by_its_first_informative_line(self):
        # A blank or punctuation-only line, an XML declaration, a root <odoo> or <templates> tag and an import say
        # nothing; a line the previous series' block lacks comes first; without any other line the id stands alone.
        source = LABELS.replace('{docs}', docs_map(['15.0', '19.0']))
        text = self.render('19.0', source, ['15.0', '19.0'])
        self.assertEqual(text[text.index('## Changed from'):], (
            '## Changed from 15.0\n\n'
            "- `manifest`: `'version': '19.0.1.0.0',`\n"
            '- `view`: `<list/>`\n'
            '- `imports`\n'
            '- `template`: `<t t-name="x.Thing"/>`\n'))

    def test_checked_and_official_lines_name_the_rendered_series(self):
        text = self.render('17.0')
        self.assertIn('\nChecked against: 17.0.\n', text)
        self.assertIn('\nOfficial docs: [17.0](https://www.odoo.com/documentation/17.0/a.html)\n', text)

    def test_the_oldest_series_and_an_unchanged_series_say_so(self):
        self.assertTrue(self.render('15.0').endswith(f'## Changed from earlier series\n\n{OLDEST}\n'))
        unchanged = re.sub(r'<!-- since=19.0 id=intro -->.*?<!-- end -->\n|```python since=19.0 id=model.*?```\n',
                           '', SOURCE, flags=re.S)
        text = self.render('19.0', unchanged.format(docs=docs_map(THREE)))
        self.assertTrue(text.endswith('## Changed from 17.0\n\nNo change from 17.0.\n'))

    def test_source_errors_name_their_line(self):
        source = SOURCE.format(docs=docs_map(THREE))
        cases = {
            source.replace('```python id=helper since=17.0', '```python since=17.0'): 'x.md:31: since= needs id=',
            source.replace('```python id=helper', '```python id=helper title=x'): 'x.md:31: unknown attribute title',
            source.replace('since=17.0', 'since=17'): 'x.md:31: since=17 is not a series',
            source.replace('since=19.0 id=model', 'since=15.0 id=model'): 'x.md:26: id=model since=15.0 twice',
            source.replace(docs_map(THREE), docs_map(['15.0', '19.0'])): 'x.md:5: no Official docs page for 17.0',
            source.replace('<!-- end -->\n', ''):
                'x.md:20: a fence inside the prose block of line 11 takes no attributes (is its <!-- end --> missing?)',
            source + '<!-- since=19.0 id=tail -->\nTail.\n': 'x.md:60: unclosed block',
            source + '\n## Changed from 15.0\n': 'x.md:61: the renderer writes the Changed from section',
        }
        for text, message in cases.items():
            with self.subTest(message=message), self.assertRaises(self.renderer.RecipeError) as raised:
                self.renderer.render(text, '17.0', THREE, source='x.md')
            self.assertEqual(str(raised.exception), message)


class RenderCommandTests(unittest.TestCase):
    """The command on a synthetic repository: it writes every series, and --check names stale files."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='oasis-render-recipes-'))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        source = self.root / 'recipes/odoo-backend/thing.md'
        source.parent.mkdir(parents=True)
        source.write_text(SOURCE.format(docs=docs_map(THREE)), encoding='utf-8')
        (self.root / 'recipes/README.md').write_text('# Recipe sources\n', encoding='utf-8')

    def run_tool(self, *arguments):
        return subprocess.run([sys.executable, '-I', '-B', str(RENDERER), '--root', str(self.root), *arguments],
                              capture_output=True, text=True, timeout=60)

    def test_it_writes_every_supported_series_and_check_tells_fresh_from_stale(self):
        first = self.run_tool()
        rendered = [f'odoo-backend/references/{series}/thing.md' for series in ascending()]
        self.assertEqual((first.returncode, first.stderr), (0, ''))
        self.assertEqual(first.stdout, ''.join(f'render_recipes: wrote {path}\n' for path in rendered)
                         + f'render_recipes: {len(rendered)} files, {len(rendered)} written.\n')
        for path in rendered:
            self.assertTrue((self.root / path).is_file(), path)
        self.assertFalse((self.root / 'odoo-backend/references/README.md').exists())
        again = self.run_tool()
        self.assertEqual((again.returncode, again.stdout), (0, f'render_recipes: {len(rendered)} files, 0 written.\n'))
        fresh = self.run_tool('--check')
        self.assertEqual((fresh.returncode, fresh.stdout, fresh.stderr),
                         (0, f'render_recipes: {len(rendered)} files fresh.\n', ''))
        stale = self.root / rendered[-1]
        stale.write_text(stale.read_text(encoding='utf-8') + 'edited by hand\n', encoding='utf-8')
        extra = self.root / 'odoo-backend/references' / ascending()[0] / 'gone.md'
        extra.write_text('# A recipe without a source\n', encoding='utf-8')
        checked = self.run_tool('--check')
        self.assertEqual((checked.returncode, checked.stderr), (1, ''))
        self.assertEqual(checked.stdout, ''.join(sorted(
            f'render_recipes: stale {path}\n' for path in (rendered[-1], extra.relative_to(self.root).as_posix())))
            + f'render_recipes: 2 stale files; run python3 tools/render_recipes.py.\n')
        self.assertIn('edited by hand', stale.read_text(encoding='utf-8'))

    def test_a_source_error_exits_2_and_writes_nothing(self):
        source = self.root / 'recipes/odoo-backend/thing.md'
        source.write_text(source.read_text(encoding='utf-8').replace('id=helper ', ''), encoding='utf-8')
        for arguments in ((), ('--check',)):
            with self.subTest(arguments=arguments):
                result = self.run_tool(*arguments)
                self.assertEqual((result.returncode, result.stdout),
                                 (2, ''))
                self.assertEqual(result.stderr, 'render_recipes: recipes/odoo-backend/thing.md:31: since= needs id=\n')
                self.assertFalse((self.root / 'odoo-backend').exists())


class SkillRecipeTests(unittest.TestCase):
    """The shipped recipes: one source each, rendered fresh, complete on every supported series, routed."""

    def test_every_recipe_has_one_source_and_its_rendered_files_are_fresh(self):
        sources = {(path.parent.name, path.name) for path in (ROOT / 'recipes').glob('*/*.md')}
        self.assertEqual(sources, {(skill, name) for skill, names in RECIPES.items() for name in names})
        result = subprocess.run([sys.executable, '-I', '-B', str(RENDERER), '--check'],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout)

    def test_every_rendered_recipe_is_complete_and_checked_against_its_series(self):
        for series in ascending():
            for skill, names in RECIPES.items():
                for name in names:
                    path = ROOT / skill / 'references' / series / name
                    with self.subTest(recipe=f'{skill}/references/{series}/{name}'):
                        self.assertTrue(path.is_file())
                        self.assertEqual(recipe_problems(path.read_text(encoding='utf-8'), [series]), [])

    def test_every_recipe_shows_the_files_it_uses_beside_module_and_model(self):
        for series in ascending():
            with self.subTest(series=series):
                texts = {f'{skill}/{name}': (ROOT / skill / 'references' / series / name).read_text(encoding='utf-8')
                         for skill, names in RECIPES.items() for name in names}
                self.assertEqual(self_containment_problems(texts), [])

    def test_every_shared_file_is_the_same_copy_in_every_recipe_of_a_series(self):
        for series in ascending():
            with self.subTest(series=series):
                paths = {f'{skill}/{name}': ROOT / skill / 'references' / series / name
                         for skill, names in RECIPES.items() for name in names}
                self.assertEqual([name for name, path in paths.items() if not path.is_file()], [])
                texts = {name: path.read_text(encoding='utf-8') for name, path in paths.items()}
                self.assertEqual(shared_copy_problems(texts), [])

    def test_the_decision_gates_of_each_skill_send_the_agent_to_the_recipes_of_its_series(self):
        # S4: a SKILL.md names no series, so each gate names its recipe as `references/<series>/<recipe>.md`.
        for skill, names in RECIPES.items():
            gates = sections((ROOT / skill / 'SKILL.md').read_text(encoding='utf-8')).get('Decision Gates', '')
            for name in names:
                with self.subTest(recipe=f'{skill}/references/<series>/{name}'):
                    self.assertIn(f'`references/<series>/{name}`', gates)


if __name__ == '__main__':
    unittest.main()
