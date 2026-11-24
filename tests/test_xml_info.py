"""view-info and xmlid-info contracts on the committed synthetic source tree; no runtime, service or database."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/model_info'
PROJECT = FIXTURE / 'project'
CORE = 'coffee/views/coffee_order_views.xml'
LOYALTY = 'coffee_loyalty/views/coffee_order_views.xml'
SHOP = 'coffee_shop/views/order_views.xml'
VIEW_USAGE = 'ERROR: Usage: view-info <model> [--type <tag>] [--module <technical>]\n'
XMLID_USAGE = 'ERROR: Usage: xmlid-info <module>.<name>\n'
ORDER_VIEWS = f'''model: coffee.order — 3 views, 4 extensions
form coffee.view_coffee_order_form {CORE}:3
  + coffee_loyalty.view_coffee_order_form_loyalty {LOYALTY}:3 (2 changes)
    + coffee_loyalty.view_coffee_order_form_vip {LOYALTY}:16 (1 change, mode=primary)
  + coffee_shop.view_shop_order_form {SHOP}:4 (1 change)
list coffee.view_coffee_order_list {CORE}:12 priority=20
kanban coffee_shop.view_shop_order_kanban {SHOP}:11
unresolved: coffee_shop.view_shop_orphan {SHOP}:18 inherits missing_module.view_gone
  + coffee_shop.view_shop_orphan_child {SHOP}:33 (1 change)
skipped: coffee_shop/views/broken.xml (XML error at line 4)
'''


def tree(root):
    return sorted(str(path.relative_to(root)) for path in root.rglob('*'))


class XmlInfoTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.temp = Path(scratch.name)
        self.effects = self.temp / 'external.log'
        bindir = self.temp / 'fake bin'
        bindir.mkdir()
        for name in ('docker', 'psql', 'odoo', 'odoo-bin', 'uv', 'pip'):
            trap = bindir / name
            trap.write_text('#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$EXTERNAL_CALL"\nexit 99\n')
            trap.chmod(0o755)
        self.env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'EXTERNAL_CALL': str(self.effects),
                    'PATH': str(bindir) + os.pathsep + os.environ['PATH']}
        self.before = tree(FIXTURE)

    def invoke(self, command, *args, program='oasis'):
        result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / program),
                                 '--project', str(PROJECT), command, *args],
                                cwd=self.temp, env=self.env, text=True, capture_output=True)
        self.assertFalse(self.effects.exists(), 'Unexpected external service/install command')
        self.assertEqual(tree(FIXTURE), self.before, f'{command} must not write in scanned trees')
        return result

    def assert_result(self, command, args, code, stdout, stderr='', **kwargs):
        result = self.invoke(command, *args, **kwargs)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (code, stdout, stderr))

    # -- view-info ------------------------------------------------------------------------------

    def test_views_of_a_model_with_their_extension_tree(self):
        # Views in static/ and in source test_ modules are not listed; a view without a model
        # field takes the model of the view it inherits.
        for program in ('oasis', 'odoo19'):
            with self.subTest(program=program):
                self.assert_result('view-info', ('coffee.order',), 0, ORDER_VIEWS, program=program)

    def test_type_keeps_the_base_views_of_that_type_with_their_extensions(self):
        lines = ORDER_VIEWS.splitlines(keepends=True)
        self.assert_result('view-info', ('coffee.order', '--type', 'form'), 0,
                           'model: coffee.order — 1 view, 3 extensions\n' + ''.join(lines[1:5]) + lines[9])
        self.assert_result('view-info', ('coffee.order', '--type', 'kanban'), 0,
                           'model: coffee.order — 1 view, 0 extensions\n' + lines[6] + lines[9])
        self.assert_result('view-info', ('coffee.order', '--type', 'search'), 1, '',
                           'no views found for model: coffee.order (type search)\n')

    def test_module_lists_only_its_views_with_what_they_extend(self):
        self.assert_result('view-info', ('coffee.order', '--module', 'coffee_loyalty'), 0,
                           'model: coffee.order — module coffee_loyalty: 0 views, 2 extensions\n'
                           f'+ coffee_loyalty.view_coffee_order_form_loyalty {LOYALTY}:3 (2 changes)'
                           ' extends coffee.view_coffee_order_form\n'
                           f'+ coffee_loyalty.view_coffee_order_form_vip {LOYALTY}:16 (1 change, mode=primary)'
                           ' extends coffee_loyalty.view_coffee_order_form_loyalty\n')
        self.assert_result('view-info', ('coffee.order', '--module', 'coffee_shop'), 0,
                           'model: coffee.order — module coffee_shop: 1 view, 2 extensions\n'
                           f'kanban coffee_shop.view_shop_order_kanban {SHOP}:11\n'
                           f'+ coffee_shop.view_shop_order_form {SHOP}:4 (1 change)'
                           ' extends coffee.view_coffee_order_form\n'
                           f'+ coffee_shop.view_shop_orphan_child {SHOP}:33 (1 change)'
                           ' extends coffee_shop.view_shop_orphan\n'
                           f'unresolved: coffee_shop.view_shop_orphan {SHOP}:18 inherits missing_module.view_gone\n'
                           'skipped: coffee_shop/views/broken.xml (XML error at line 4)\n')

    def test_a_model_without_views_and_other_models_stay_apart(self):
        self.assert_result('view-info', ('coffee.bean',), 0,
                           f'model: coffee.bean — 1 view, 0 extensions\nform coffee.view_coffee_bean_form {CORE}:20\n')
        self.assert_result('view-info', ('res.partner',), 1, '', 'no views found for model: res.partner\n')

    def test_view_info_usage_and_validation(self):
        for args in ((), ('coffee.order', '--type'), ('coffee.order', '--bogus'), ('a', 'b'),
                     ('coffee.order', '--type', 'form', '--type', 'list')):
            with self.subTest(args=args):
                self.assert_result('view-info', args, 2, '', VIEW_USAGE)
        self.assert_result('view-info', ('Coffee Order',), 2, '',
                           'ERROR: Invalid model name: use lowercase dotted words such as sale.order.\n')
        self.assert_result('view-info', ('coffee.order', '--type', 'fo/rm'), 2, '', 'ERROR: Invalid view type.\n')
        self.assert_result('view-info', ('coffee.order', '--module', 'a-b'), 2, '',
                           'ERROR: Module must use only letters, numbers, and underscores.\n')
        result = self.invoke('view-info', '--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(VIEW_USAGE[len('ERROR: '):]))

    # -- xmlid-info -----------------------------------------------------------------------------

    def test_a_view_with_its_fields_extensions_and_references(self):
        self.assert_result('xmlid-info', ('coffee.view_coffee_order_form',), 0,
                           'xml id: coffee.view_coffee_order_form\n'
                           f'defined: {CORE}:3 record ir.ui.view\n'
                           '  name: coffee.order.form\n'
                           '  model: coffee.order\n'
                           '  type: form\n'
                           'also written in: a_coffee_theme/views/theme.xml:4\n'
                           'extended by (2):\n'
                           f'  coffee_loyalty.view_coffee_order_form_loyalty {LOYALTY}:3\n'
                           f'  coffee_shop.view_shop_order_form {SHOP}:4\n'
                           # Python that assigns inherit_id is a reference; the XML inherit_id lines are not repeated.
                           'referenced by (1):\n'
                           '  coffee_shop/controllers/main.py:6\n')

    def test_an_action_with_references_from_xml_and_python(self):
        # Inside its own module the id is referenced without the module name.
        self.assert_result('xmlid-info', ('coffee.action_coffee_order',), 0,
                           'xml id: coffee.action_coffee_order\n'
                           f'defined: {CORE}:25 record ir.actions.act_window\n'
                           '  name: Coffee Orders\n'
                           '  res_model: coffee.order\n'
                           '  view_mode: list,form\n'
                           '  view_id: coffee.view_coffee_order_list\n'
                           'referenced by (3):\n'
                           f'  {CORE}:32\n'
                           '  coffee_shop/controllers/main.py:2\n'
                           f'  {SHOP}:27\n')

    def test_menus_templates_and_an_inherited_template(self):
        self.assert_result('xmlid-info', ('coffee.menu_coffee_order',), 0,
                           'xml id: coffee.menu_coffee_order\n'
                           f'defined: {CORE}:32 menuitem\n'
                           '  name: Orders\n'
                           '  parent: coffee.menu_coffee_root\n'
                           '  action: coffee.action_coffee_order\n')
        self.assert_result('xmlid-info', ('coffee.menu_coffee_root',), 0,
                           'xml id: coffee.menu_coffee_root\n'
                           f'defined: {CORE}:31 menuitem\n'
                           '  name: Coffee\n'
                           'referenced by (2):\n'
                           f'  {CORE}:37\n'
                           f'  {SHOP}:26\n')
        self.assert_result('xmlid-info', ('coffee_loyalty.report_order',), 0,
                           'xml id: coffee_loyalty.report_order\n'
                           f'defined: {LOYALTY}:25 template\n'
                           '  name: Order report\n'
                           '  type: qweb\n'
                           'extended by (2):\n'
                           f'  coffee_loyalty.report_order_points {LOYALTY}:28\n'
                           f'  coffee_loyalty.report_order_manager {LOYALTY}:31\n')
        self.assert_result('xmlid-info', ('coffee_loyalty.view_coffee_order_form_vip',), 0,
                           'xml id: coffee_loyalty.view_coffee_order_form_vip\n'
                           f'defined: {LOYALTY}:16 record ir.ui.view\n'
                           '  name: coffee.order.form.vip\n'
                           '  model: coffee.order\n'
                           '  inherit_id: coffee_loyalty.view_coffee_order_form_loyalty\n'
                           '  mode: primary\n')

    def test_a_record_another_module_writes_on(self):
        # The first definition in scan order is the definition; view-info keeps its values.
        self.assert_result('xmlid-info', ('coffee.view_coffee_order_list',), 0,
                           'xml id: coffee.view_coffee_order_list\n'
                           f'defined: {CORE}:12 record ir.ui.view\n'
                           '  name: coffee.order.list\n'
                           '  model: coffee.order\n'
                           '  type: list\n'
                           '  priority: 20\n'
                           f'also written in: {SHOP}:29\n'
                           'referenced by (1):\n'
                           f'  {CORE}:29\n')

    def test_a_name_inside_a_groups_list_is_a_reference(self):
        self.assert_result('xmlid-info', ('coffee.group_coffee_manager',), 0,
                           'xml id: coffee.group_coffee_manager\n'
                           f'defined: {CORE}:34 record res.groups\n'
                           '  name: Coffee manager\n'
                           'referenced by (3):\n'
                           '  coffee/security/ir.model.access.csv:2\n'
                           f'  {CORE}:38\n'
                           # A line that also inherits another template still counts for its groups.
                           f'  {LOYALTY}:31\n')

    def test_long_lists_are_capped_with_the_count_of_the_rest(self):
        scratch = self.temp / 'capped'
        project = scratch / 'project'
        addons = scratch / 'source/odoo/addons'
        (scratch / 'source/odoo/odoo/addons').mkdir(parents=True)
        (project / 'addons').mkdir(parents=True)
        (project / 'oasis-workspace.toml').write_text((PROJECT / 'oasis-workspace.toml').read_text())

        def module(name, files):
            (addons / name).mkdir(parents=True)
            (addons / name / '__manifest__.py').write_text("{'name': 'x'}\n")
            for file, text in files.items():
                (addons / name / file).write_text(text)

        fields = ''.join(f'<field name="f{index:02d}">{"v" * 70}</field>' for index in range(14))
        module('core', {'data.xml': f'<odoo>\n<record id="thing" model="x.thing">{fields}</record>\n</odoo>\n',
                        **{f'use{index:02d}.py': "REF = 'core.thing'\n" for index in range(23)}})
        for index in range(12):
            module(f'writer{index:02d}', {'data.xml': '<odoo>\n<record id="core.thing" model="x.thing"/>\n</odoo>\n'})
        extension = ('<odoo><record id="e{0:02d}" model="ir.ui.view"><field name="inherit_id" ref="v"/>'
                     '<field name="arch" type="xml"><xpath expr="//form" position="inside"/></field></record></odoo>')
        module('views', {'base.xml': '<odoo><record id="v" model="ir.ui.view"><field name="model">x.thing</field>'
                                     '<field name="arch" type="xml"><form/></field></record></odoo>',
                         **{f'ext{index:02d}.xml': extension.format(index) for index in range(45)},
                         **{f'broken{index}.xml': '<odoo><!-- x.thing lost_id -->' for index in range(7)}})
        orphan = ('<odoo><record id="o{0:02d}" model="ir.ui.view"><field name="model">x.thing</field>'
                  '<field name="inherit_id" ref="gone.view"/><field name="arch" type="xml"><form/></field></record></odoo>')
        module('zorphans', {f'o{index:02d}.xml': orphan.format(index) for index in range(12)})
        env = {**self.env}

        def run(command, *args):
            return subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'oasis'), '--project', str(project),
                                   command, *args], cwd=self.temp, env=env, text=True, capture_output=True)

        result = run('xmlid-info', 'core.thing')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        lines = result.stdout.splitlines()
        self.assertEqual(lines[:2], ['xml id: core.thing', 'defined: core/data.xml:2 record x.thing'])
        self.assertEqual(lines[2], '  f00: ' + 'v' * 59 + '…')
        self.assertEqual(lines[13:15], ['  f11: ' + 'v' * 59 + '…', '  +2 more fields'])
        self.assertEqual(lines[15:26], [f'also written in: writer{index:02d}/data.xml:2' for index in range(10)]
                         + ['also written in: +2 more files'])
        self.assertEqual(lines[26], 'referenced by (23):')
        # The broken files mention the name, so they are named after the references.
        self.assertEqual(lines[27:], [f'  core/use{index:02d}.py:1' for index in range(20)] + ['  +3 more']
                         + [f'skipped: views/broken{index}.xml (XML error at line 1)' for index in range(5)]
                         + ['skipped: +2 more files'])
        result = run('view-info', 'x.thing')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        skipped = ([f'skipped: views/broken{index}.xml (XML error at line 1)' for index in range(5)]
                   + ['skipped: +2 more files'])
        self.assertEqual(result.stdout.splitlines(),
                         ['model: x.thing — 1 view, 45 extensions', 'form views.v views/base.xml:1']
                         + [f'  + views.e{index:02d} views/ext{index:02d}.xml:1 (1 change)' for index in range(40)]
                         + ['  +5 more extensions (narrow with --module)']
                         + [f'unresolved: zorphans.o{index:02d} zorphans/o{index:02d}.xml:1 inherits gone.view'
                            for index in range(10)]
                         + ['unresolved: +2 more'] + skipped)
        result = run('view-info', 'x.thing', '--module', 'views')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout.splitlines(),
                         ['model: x.thing — module views: 1 view, 45 extensions', 'form views.v views/base.xml:1']
                         + [f'+ views.e{index:02d} views/ext{index:02d}.xml:1 (1 change) extends views.v'
                            for index in range(40)]
                         + ['+5 more extensions'] + skipped)
        result = run('view-info', 'x.thing', '--module', 'zorphans')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout.splitlines(),
                         ['model: x.thing — module zorphans: 0 views, 0 extensions']
                         + [f'unresolved: zorphans.o{index:02d} zorphans/o{index:02d}.xml:1 inherits gone.view'
                            for index in range(10)]
                         + ['unresolved: +2 more'])
        result = run('xmlid-info', 'views.v')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout.splitlines()[4:],
                         ['extended by (45):']
                         + [f'  views.e{index:02d} views/ext{index:02d}.xml:1' for index in range(20)] + ['  +25 more'])
        # An id that may be defined in a file that could not be parsed: the files are named.
        result = run('xmlid-info', 'views.lost_id')
        self.assertEqual((result.returncode, result.stdout), (1, ''))
        self.assertEqual(result.stderr.splitlines(), ['xml id not found: views.lost_id'] + skipped)

    def test_an_inherit_id_field_is_not_a_reference_whatever_its_attribute_order(self):
        scratch = self.temp / 'order'
        project = scratch / 'project'
        module = scratch / 'source/odoo/addons/core'
        (scratch / 'source/odoo/odoo/addons').mkdir(parents=True)
        (project / 'addons').mkdir(parents=True)
        module.mkdir(parents=True)
        (project / 'oasis-workspace.toml').write_text((PROJECT / 'oasis-workspace.toml').read_text())
        (module / '__manifest__.py').write_text("{'name': 'x'}\n")
        (module / 'views.xml').write_text(
            '<odoo>\n'
            '<record id="base_view" model="ir.ui.view"><field name="model">x.thing</field></record>\n'
            '<record id="first" model="ir.ui.view"><field name="inherit_id" ref="base_view"/></record>\n'
            '<record id="second" model="ir.ui.view"><field ref="core.base_view" name="inherit_id"/></record>\n'
            '<record id="third" model="ir.ui.view"><field name="inherit_id" ref="base_view"/>'
            '<field name="view_id" ref="base_view"/></record>\n'
            '</odoo>\n')
        result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'oasis'), '--project', str(project),
                                 'xmlid-info', 'core.base_view'], cwd=self.temp, env=self.env, text=True,
                                capture_output=True)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout.splitlines()[2:],
                         ['  model: x.thing', '  type: unknown', 'extended by (3):',
                          '  core.first core/views.xml:3', '  core.second core/views.xml:4', '  core.third core/views.xml:5',
                          # Only the other field of the last record refers to it.
                          'referenced by (1):', '  core/views.xml:5'])

    def test_unknown_ids_and_usage(self):
        self.assert_result('xmlid-info', ('coffee.no_such_record',), 1, '', 'xml id not found: coffee.no_such_record\n')
        # Records in static/ and in source test_ modules are not scanned.
        self.assert_result('xmlid-info', ('coffee.view_static_order',), 1, '',
                           'xml id not found: coffee.view_static_order\n')
        self.assert_result('xmlid-info', ('test_coffee.view_test_order_form',), 1, '',
                           'xml id not found: test_coffee.view_test_order_form\n')
        for args in ((), ('a.b', 'c.d'), ('--bogus',)):
            with self.subTest(args=args):
                self.assert_result('xmlid-info', args, 2, '', XMLID_USAGE)
        for value in ('view_coffee_order_form', 'coffee.', 'coffee.a b', '../x.y'):
            with self.subTest(value=value):
                self.assert_result('xmlid-info', (value,), 2, '',
                                   'ERROR: Invalid XML id: use <module>.<name>, such as sale.view_order_form.\n')
        result = self.invoke('xmlid-info', '--help')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(XMLID_USAGE[len('ERROR: '):]))


if __name__ == '__main__':
    unittest.main()
