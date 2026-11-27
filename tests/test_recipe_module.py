"""v0.19.0 S6: tools/recipe_module.py builds the recipes' module of a series and checks it is complete."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/recipe_module.py'
_spec = importlib.util.spec_from_file_location('odoo_versions', ROOT / 'tools/odoo_versions.py')
odoo_versions = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(odoo_versions)

SERIES = odoo_versions.supported()[0]
NEXT = 'next=oasis --project <root> test-module --compact library\n'
USAGE = 'ERROR: Usage: recipe_module.py <series> <destination> [--root <dir>]\n'
FENCE = '```'

MANIFEST = '''{
    'name': 'Library',
    'version': '1.0',
    'depends': ['web'],
    'data': [
        'security/ir.model.access.csv',
        'views/library_book_views.xml',
    ],
    'assets': {
        'web.assets_tests': [
            'library/static/tests/tours/**/*',
        ],
    },
    'license': 'LGPL-3',
}
'''
INIT = 'from . import models\n'
MODELS_INIT = 'from . import library_book\n'
BOOK = '''from odoo import fields, models


class LibraryBook(models.Model):
    _name = 'library.book'
    _description = 'Library Book'

    name = fields.Char(required=True)
'''
CSV = '''id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_library_book_user,library.book.user,model_library_book,base.group_user,1,1,1,1
'''
VIEWS = '''<odoo>
    <record id="library_book_view_list" model="ir.ui.view">
        <field name="model">library.book</field>
        <field name="arch" type="xml"><list><field name="name"/></list></field>
    </record>
</odoo>
'''
TESTS_INIT = 'from . import test_library_book\n'
TEST = '''from odoo.tests import TransactionCase


class TestLibraryBook(TransactionCase):
    def test_name(self):
        self.assertTrue(self.env['library.book'].create({'name': 'A'}).name)
'''
TOUR = 'import { registry } from "@web/core/registry";\n'


def block(label, language, content):
    return f'{label}\n\n{FENCE}{language}\n{content}{FENCE}\n'


def recipes(manifest=MANIFEST, models_init=MODELS_INIT, book=BOOK, second_manifest=None):
    """{skill/recipe.md: text}: four synthetic rendered recipes that build one module."""
    return {
        'odoo-backend/module.md': '# Recipe: a module\n\n## Example\n\n' + '\n'.join((
            block('`library/__manifest__.py`, final: it lists every file.', 'python', manifest),
            block('`library/__init__.py`:', 'python', INIT),
            block('`library/models/__init__.py`:', 'python', models_init),
            # A block without a label (a rule's bad example) is not a file.
            block('Bad:', 'python', 'from . import nothing\n'),
        )),
        'odoo-backend/model.md': '# Recipe: a model\n\n## Example\n\n' + block(
            '`library/models/library_book.py`, final: it holds every field\nthe later recipes use:',
            'python', book),
        'odoo-security/access.md': '# Recipe: access\n\n## Example\n\n' + '\n'.join((
            block('`library/__manifest__.py` (the final manifest of the module recipe):', 'python',
                  second_manifest or manifest),
            block('`library/security/ir.model.access.csv`:', 'csv', CSV),
        )),
        'odoo-views-frontend/views.md': '# Recipe: views\n\n## Example\n\n' + block(
            '`library/views/library_book_views.xml`:', 'xml', VIEWS),
        'odoo-testing/model-tests.md': '# Recipe: tests\n\n## Example\n\n' + '\n'.join((
            block('`library/tests/__init__.py`:', 'python', TESTS_INIT),
            block('`library/tests/test_library_book.py`:', 'python', TEST),
            block('`library/static/tests/tours/library_book_tour.js`:', 'javascript', TOUR),
        )),
    }


def tree(root):
    return sorted(path.relative_to(root).as_posix() for path in root.rglob('*'))


class RecipeModuleTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix='oasis-test-recipe-module-')
        self.addCleanup(scratch.cleanup)
        self.temp = Path(scratch.name)
        self.root = self.temp / 'bundle'
        self.destination = self.temp / 'out'

    def write_recipes(self, texts, series=SERIES):
        for name, text in texts.items():
            skill, recipe = name.split('/')
            path = self.root / skill / 'references' / series / recipe
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')

    def run_tool(self, *arguments, root=True):
        extra = ['--root', str(self.root)] if root else []
        return subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), *arguments, *extra],
                              capture_output=True, text=True, timeout=120)

    def test_builds_the_module_of_the_series(self):
        self.write_recipes(recipes())
        result = self.run_tool(SERIES, str(self.destination))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, 'files=9\nok\n' + NEXT, ''))
        module = self.destination / 'library'
        self.assertEqual(tree(module), [
            '__init__.py', '__manifest__.py', 'models', 'models/__init__.py', 'models/library_book.py',
            'security', 'security/ir.model.access.csv', 'static', 'static/tests', 'static/tests/tours',
            'static/tests/tours/library_book_tour.js', 'tests', 'tests/__init__.py',
            'tests/test_library_book.py', 'views', 'views/library_book_views.xml'])
        self.assertEqual((module / '__manifest__.py').read_text(encoding='utf-8'), MANIFEST)
        self.assertEqual((module / 'models/library_book.py').read_text(encoding='utf-8'), BOOK)
        self.assertEqual((module / 'security/ir.model.access.csv').read_text(encoding='utf-8'), CSV)

    def test_refuses_a_destination_that_already_has_the_module(self):
        self.write_recipes(recipes())
        existing = self.destination / 'library'
        existing.mkdir(parents=True)
        (existing / 'keep.txt').write_text('mine\n', encoding='utf-8')
        result = self.run_tool(SERIES, str(self.destination))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            2, '', f'ERROR: {existing} already exists: give a destination without library/.\n'))
        self.assertEqual(tree(self.destination), ['library', 'library/keep.txt'])
        self.assertEqual((existing / 'keep.txt').read_text(encoding='utf-8'), 'mine\n')

    def test_refuses_two_recipes_that_give_different_copies_of_one_file(self):
        stale = MANIFEST.replace("'version': '1.0'", "'version': '1.1'")
        self.write_recipes(recipes(second_manifest=stale))
        result = self.run_tool(SERIES, str(self.destination))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            2, '', f'ERROR: library/__manifest__.py differs between odoo-backend/references/{SERIES}/module.md '
                   f'and odoo-security/references/{SERIES}/access.md.\n'))
        self.assertFalse(self.destination.exists())

    def test_refuses_a_label_that_leaves_the_module(self):
        for label in ('library/../x.py', 'library/.'):
            with self.subTest(label=label):
                texts = recipes()
                texts['odoo-backend/module.md'] += '\n' + block(f'`{label}`:', 'python', 'x = 1\n')
                self.write_recipes(texts)
                self.destination.mkdir(exist_ok=True)
                (self.destination / 'keep.txt').write_text('mine\n', encoding='utf-8')
                result = self.run_tool(SERIES, str(self.destination))
                self.assertEqual((result.returncode, result.stdout, result.stderr), (
                    2, '', f'ERROR: odoo-backend/references/{SERIES}/module.md: '
                           f'the label {label} leaves library/.\n'))
                self.assertEqual(tree(self.destination), ['keep.txt'])
                self.assertEqual((self.destination / 'keep.txt').read_text(encoding='utf-8'), 'mine\n')
                self.assertEqual(tree(self.temp), ['bundle', *(f'bundle/{path}' for path in tree(self.root)),
                                                   'out', 'out/keep.txt'])

    def test_refuses_a_series_without_rendered_recipes(self):
        self.write_recipes(recipes(), series='1.0')
        result = self.run_tool(SERIES, str(self.destination))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            2, '', f'ERROR: No rendered recipes for {SERIES} under {self.root} (<skill>/references/{SERIES}/*.md '
                   'of odoo-backend, odoo-views-frontend, odoo-security, odoo-testing).\n'))
        self.assertFalse(self.destination.exists())

    def test_usage_errors_write_nothing(self):
        self.write_recipes(recipes())
        for arguments, error in (((SERIES,), USAGE), ((SERIES, str(self.destination), '--force'), USAGE),
                                 (('../x', str(self.destination)),
                                  "ERROR: Invalid series '../x': expected <major>.0.\n")):
            with self.subTest(arguments=arguments):
                result = self.run_tool(*arguments)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (2, '', error))
                self.assertFalse(self.destination.exists())

    def test_reports_a_missing_data_file_imported_module_and_asset(self):
        manifest = MANIFEST.replace("'views/library_book_views.xml',",
                                    "'views/library_book_views.xml',\n        'views/library_menus.xml',")
        manifest = manifest.replace('static/tests/tours/**/*', 'static/src/**/*')
        self.write_recipes(recipes(manifest=manifest, models_init=MODELS_INIT + 'from . import library_loan\n'))
        result = self.run_tool(SERIES, str(self.destination))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            1, 'files=9\nmissing=library/views/library_menus.xml,library/models/library_loan.py,'
               'library/static/src/**/*\n', ''))
        self.assertTrue((self.destination / 'library/models/library_book.py').is_file())

    def test_rejects_a_python_file_that_does_not_compile(self):
        broken = BOOK.replace('class LibraryBook(models.Model):', 'class LibraryBook(models.Model)')
        try:
            compile(broken, 'library_book.py', 'exec')
        except SyntaxError as error:
            reason = f'{error.msg} (line {error.lineno})'
        else:
            self.fail('the broken book compiles')
        self.write_recipes(recipes(book=broken))
        result = self.run_tool(SERIES, str(self.destination))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (
            1, f'files=9\ninvalid=library/models/library_book.py: {reason}\n', ''))
        self.assertEqual(tree(self.destination / 'library/models'), ['__init__.py', 'library_book.py'])

    def test_the_shipped_recipes_build_a_complete_module_for_every_supported_series(self):
        for series in odoo_versions.supported():
            with self.subTest(series=series):
                destination = self.temp / series
                result = self.run_tool(series, str(destination), root=False)
                self.assertEqual((result.returncode, result.stderr), (0, ''), result.stdout + result.stderr)
                lines = result.stdout.splitlines()
                self.assertRegex(lines[0], r'^files=[1-9]\d*$')
                self.assertEqual(lines[1:], ['ok', NEXT.rstrip('\n')])
                self.assertTrue((destination / 'library/__manifest__.py').is_file())


if __name__ == '__main__':
    unittest.main()
