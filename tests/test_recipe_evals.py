"""v0.19.0 S7: tools/recipe_evals.py flags the forms that are wrong on a module's series."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import contextlib
import importlib.util
import io
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/recipe_evals.py'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


odoo_versions = load('odoo_versions', ROOT / 'tools/odoo_versions.py')
recipe_evals = load('recipe_evals', SCRIPT)
SUPPORTED = odoo_versions.supported()
USAGE = 'ERROR: Usage: recipe_evals.py <series> <module-dir>\n'

VIEWS_19_WRONG = '''<odoo>
    <record id="library_member_view_list" model="ir.ui.view">
        <field name="model">library.member</field>
        <field name="arch" type="xml">
            <tree>
                <field name="name" attrs="{'invisible': [('active', '=', False)]}"/>
            </tree>
        </field>
    </record>
</odoo>
'''
VIEWS_19_CLEAN = '''<odoo>
    <record id="library_member_view_list" model="ir.ui.view">
        <field name="model">library.member</field>
        <field name="arch" type="xml">
            <list>
                <field name="name" invisible="not active"/>
            </list>
        </field>
    </record>
</odoo>
'''
MODEL_19_CLEAN = '''from odoo import fields, models


class LibraryMember(models.Model):
    _name = 'library.member'
    _description = 'Library Member'

    name = fields.Char(required=True)
    email = fields.Char()
    active = fields.Boolean(default=True)

    _email_unique = models.Constraint('UNIQUE(email)', 'The email must be unique.')
'''
VIEWS_15_WRONG = '''<odoo>
    <record id="library_member_view_form" model="ir.ui.view">
        <field name="model">library.member</field>
        <field name="arch" type="xml">
            <form>
                <field name="state"/>
                <field name="name" invisible="state != 'draft'"/>
            </form>
        </field>
    </record>
    <record id="library_member_view_list" model="ir.ui.view">
        <field name="model">library.member</field>
        <field name="arch" type="xml">
            <list>
                <field name="name"/>
            </list>
        </field>
    </record>
</odoo>
'''
VIEWS_15_CLEAN = '''<odoo>
    <record id="library_member_view_list" model="ir.ui.view">
        <field name="model">library.member</field>
        <field name="arch" type="xml">
            <tree>
                <field name="name"/>
                <field name="active" invisible="1"/>
            </tree>
        </field>
    </record>
</odoo>
'''
MODEL_15_WRONG = MODEL_19_CLEAN
MODEL_15_CLEAN = '''from odoo import fields, models


class LibraryMember(models.Model):
    _name = 'library.member'
    _description = 'Library Member'

    name = fields.Char(required=True)
    email = fields.Char()

    _sql_constraints = [('email_unique', 'UNIQUE(email)', 'The email must be unique.')]
'''


def run(*arguments):
    return subprocess.run([sys.executable, '-B', str(SCRIPT), *arguments],
                          capture_output=True, text=True, check=False)


class RecipeEvalsTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix='oasis-recipe-evals-')
        self.addCleanup(scratch.cleanup)
        self.module = Path(scratch.name) / 'library'

    def write(self, files):
        for name, content in files.items():
            path = self.module / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')

    @unittest.skipUnless('19.0' in SUPPORTED, 'the 19.0 forms need 19.0 supported')
    def test_tree_and_attrs_are_wrong_on_19(self):
        self.write({'__init__.py': 'from . import models\n',
                    'views/library_member_views.xml': VIEWS_19_WRONG})
        result = run('19.0', str(self.module))
        self.assertEqual(result.stdout,
                         'wrong=views/library_member_views.xml:5: <tree> '
                         '(list views are <list>: tree is not a view type)\n'
                         'wrong=views/library_member_views.xml:6: attrs '
                         '(refused since 17.0: write invisible, readonly or required as a Python expression)\n'
                         'hits=2\n')
        self.assertEqual(result.stderr, '')
        self.assertEqual(result.returncode, 1)

    @unittest.skipUnless('19.0' in SUPPORTED, 'the 19.0 forms need 19.0 supported')
    def test_a_clean_19_module_passes(self):
        self.write({'__init__.py': 'from . import models\n',
                    'models/library_member.py': MODEL_19_CLEAN,
                    'views/library_member_views.xml': VIEWS_19_CLEAN})
        result = run('19.0', str(self.module))
        self.assertEqual(result.stdout, 'hits=0\n')
        self.assertEqual(result.stderr, '')
        self.assertEqual(result.returncode, 0)

    @unittest.skipUnless('15.0' in SUPPORTED, 'the 15.0 forms need 15.0 supported')
    def test_list_expression_and_constraint_are_wrong_on_15(self):
        self.write({'models/library_member.py': MODEL_15_WRONG,
                    'views/library_member_views.xml': VIEWS_15_WRONG})
        result = run('15.0', str(self.module))
        self.assertEqual(result.stdout,
                         'wrong=models/library_member.py:12: models.Constraint '
                         '(does not exist: declare _sql_constraints)\n'
                         'wrong=views/library_member_views.xml:7: invisible/readonly/required expression '
                         '(evaluated with only context: a condition on record values goes in attrs)\n'
                         'wrong=views/library_member_views.xml:14: <list> '
                         '(list views are <tree>: list is not a view type)\n'
                         'hits=3\n')
        self.assertEqual(result.stderr, '')
        self.assertEqual(result.returncode, 1)

    @unittest.skipUnless('15.0' in SUPPORTED, 'the 15.0 forms need 15.0 supported')
    def test_a_constant_modifier_is_right_on_15(self):
        self.write({'models/library_member.py': MODEL_15_CLEAN,
                    'views/library_member_views.xml': VIEWS_15_CLEAN})
        result = run('15.0', str(self.module))
        self.assertEqual(result.stdout, 'hits=0\n')
        self.assertEqual(result.stderr, '')
        self.assertEqual(result.returncode, 0)

    def test_an_unknown_series_is_a_usage_error(self):
        self.write({'__init__.py': ''})
        result = run('18.5', str(self.module))
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr,
                         f'ERROR: Unknown series 18.5; supported: {", ".join(SUPPORTED)}.\n')
        self.assertEqual(result.returncode, 2)

    def test_a_missing_directory_is_a_usage_error(self):
        result = run(SUPPORTED[0], str(self.module))
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, f'ERROR: Not a module directory: {self.module}\n')
        self.assertEqual(result.returncode, 2)

    def test_a_wrong_argument_count_is_a_usage_error(self):
        result = run(SUPPORTED[0])
        self.assertEqual((result.stdout, result.stderr, result.returncode), ('', USAGE, 2))

    def test_a_supported_series_without_forms_is_a_usage_error_naming_it(self):
        self.write({'__init__.py': ''})
        series = SUPPORTED[0]
        forms = {key: value for key, value in recipe_evals.FORMS.items() if key != series}
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(recipe_evals, 'FORMS', forms), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = recipe_evals.main([series, str(self.module)])
        self.assertEqual(stdout.getvalue(), '')
        self.assertEqual(stderr.getvalue(),
                         f'ERROR: No forms for series {series} in tools/recipe_evals.py: '
                         f'add the forms that are wrong on it to FORMS.\n')
        self.assertEqual(code, 2)

    def test_every_supported_series_has_forms_with_a_source(self):
        for series in SUPPORTED:
            with self.subTest(series=series):
                forms = recipe_evals.FORMS.get(series)
                self.assertTrue(forms)
                for form in forms:
                    self.assertTrue(form.kinds)
                    self.assertLessEqual(set(form.kinds), {'py', 'xml', 'js', 'csv'})
                    self.assertRegex(form.source, r'^[\w./-]+:\d+$')
                    self.assertTrue(form.form and form.reason)
                    self.assertIsInstance(form.pattern, re.Pattern)


if __name__ == '__main__':
    unittest.main()
