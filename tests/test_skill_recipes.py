"""v0.18.0 S1, S7, S8: the task recipes of the code skills, checked as files an agent reads."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import ast
import csv
import importlib.util
import io
import re
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('odoo_versions', ROOT / 'tools/odoo_versions.py')
odoo_versions = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(odoo_versions)

# odd/tasks/v0.18.0.md L5: the recipe files of each code skill.
RECIPES = {
    'odoo-backend': ('module.md', 'model.md', 'compute-constraint.md', 'inheritance.md'),
    'odoo-views-frontend': ('views.md', 'actions-menus.md', 'view-inheritance.md', 'owl-component.md'),
    'odoo-security': ('access.md', 'record-rules.md'),
    'odoo-testing': ('model-tests.md', 'tours.md'),
}
SECTIONS = ('When to use', 'Files', 'Example', 'Changed in', 'Mistakes', 'Verify')
CHANGED_HEADER = '| Point | Since | Before | Source |'
NO_CHANGE = 'No change across the checked series.'
FENCE = re.compile(r'^```([a-z]*)\n(.*?)^```$', re.M | re.S)


def series_key(series):
    return tuple(int(part) for part in series.split('.'))


def sections(text):
    """`## ` sections in order, as {title: body}."""
    parts = re.split(r'^## (.+)$', FENCE.sub('', text), flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


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


def recipe_problems(text, supported):
    """What a recipe misses: S1 sections, S7 parsable snippets, S8 `Checked against:` and changes."""
    problems = []
    found = sections(text)
    if tuple(found) != SECTIONS:
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
    changed = found.get('Changed in', '')
    rows = [line for line in changed.splitlines() if line.startswith('|')]
    if NO_CHANGE in changed and not rows:
        return problems
    if not rows or rows[0] != CHANGED_HEADER:
        return problems + ['no changed-in table']
    oldest, newest = min(listed, key=series_key, default='0.0'), max(listed, key=series_key, default='0.0')
    for row in rows[2:]:
        cells = [cell.strip() for cell in row.strip('|').split('|')]
        if len(cells) != 4:
            problems.append(f'row {row}')
            continue
        since, source = cells[1], cells[3]
        if not re.fullmatch(r'\d+\.0', since) or not (
                series_key(oldest) < series_key(since) <= series_key(newest)):
            problems.append(f'since {since}')
        if not re.search(r'`[\w./-]+:\d+', source):
            problems.append(f'source {source}')
    return problems


GOOD = '''# Recipe: a model

Checked against: 15.0, 19.0.

Official docs: [19.0](https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html), [15.0](https://www.odoo.com/documentation/15.0/developer/reference/backend/orm.html)

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

## Changed in

| Point | Since | Before | Source |
|---|---|---|---|
| `<list>` | 17.0 | `<tree>` | `odoo/addons/base/models/ir_ui_view.py:149` |

## Mistakes

- None.

## Verify

`oasis test-module --compact x_thing`
'''


class RecipeCheckTests(unittest.TestCase):
    """The checker itself, on synthetic recipes: it passes a good one and names each defect."""

    def test_a_complete_recipe_has_no_problem(self):
        self.assertEqual(recipe_problems(GOOD, ['15.0', '19.0']), [])

    def test_a_recipe_with_no_change_needs_no_table(self):
        text = re.sub(r'(## Changed in\n\n).*?(\n## Mistakes)', rf'\g<1>{NO_CHANGE}\n\g<2>', GOOD, flags=re.S)
        self.assertEqual(recipe_problems(text, ['15.0', '19.0']), [])

    def test_a_series_added_to_oasis_flags_the_recipe(self):
        self.assertEqual(recipe_problems(GOOD, ['15.0', '17.0', '19.0']),
                         ['not checked against 17.0', 'no official 17.0 page'])

    def test_broken_snippets_are_named(self):
        broken = GOOD.replace('class Thing', 'class Thing(').replace('<list/>', '<list>')
        broken = broken.replace('access_x_thing,x.thing,model_x_thing', 'access_x_thing,x.thing')
        problems = recipe_problems(broken, ['15.0', '19.0'])
        self.assertEqual([problem.split(':')[0] for problem in problems], ['python', 'xml', 'csv rows differ in length'])

    def test_missing_section_and_bad_rows_are_named(self):
        text = GOOD.replace('## Mistakes\n\n- None.\n\n', '')
        text = text.replace('| 17.0 |', '| 14.0 |').replace('`odoo/addons/base/models/ir_ui_view.py:149`', 'somewhere')
        self.assertEqual(recipe_problems(text, ['15.0', '19.0']), [
            "sections ['When to use', 'Files', 'Example', 'Changed in', 'Verify']",
            'since 14.0', 'source somewhere'])


class SkillRecipeTests(unittest.TestCase):
    """The shipped recipes: every one complete, checked against every series oasis supports, routed."""

    def test_every_recipe_is_complete_and_checked_against_every_supported_series(self):
        supported = odoo_versions.supported()
        for skill, names in RECIPES.items():
            for name in names:
                path = ROOT / skill / 'references' / name
                with self.subTest(recipe=f'{skill}/references/{name}'):
                    self.assertTrue(path.is_file())
                    self.assertEqual(recipe_problems(path.read_text(encoding='utf-8'), supported), [])

    def test_the_decision_gates_of_each_skill_send_the_agent_to_its_recipes(self):
        for skill, names in RECIPES.items():
            gates = sections((ROOT / skill / 'SKILL.md').read_text(encoding='utf-8')).get('Decision Gates', '')
            for name in names:
                with self.subTest(recipe=f'{skill}/references/{name}'):
                    self.assertIn(f'(references/{name})', gates)


if __name__ == '__main__':
    unittest.main()
