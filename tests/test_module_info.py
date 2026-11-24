"""module-info contracts on the committed synthetic source tree; no runtime, service or database."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/model_info'
PROJECT = FIXTURE / 'project'
ADDONS = (PROJECT / 'addons').resolve()
SOURCE = (FIXTURE / 'source/odoo/addons').resolve()
USAGE = 'ERROR: Usage: module-info <module> [--section <name>]\n'
SECTION_ERROR = 'ERROR: Invalid section: use models, views, menus, actions, security, data or tests.\n'
MODULE_ERROR = 'ERROR: Module must use only letters, numbers, and underscores.\n'
HEADER = f'''module: coffee_planner 19.0.1.2.0 — Plan coffee subscriptions
depends: coffee, mail
root: {ADDONS}
'''
MODELS = '''models: 4 defined, 2 extended
  coffee.subscription "Coffee subscription" (+mail.thread): 4 fields, models/subscription.py:4
  coffee.subscription.line: 2 fields, models/subscription.py:18
  coffee.planner.mixin "Planner mixin" abstract: 0 fields, models/subscription.py:25
  coffee.subscription.renew "Renew subscriptions" transient: 1 field, wizard/renew_wizard.py:4
  extends account.move (+mail.activity.mixin): 2 fields, models/account_move.py:4
  extends res.partner: 1 field, models/res_partner.py:4
'''
VIEWS = '''views: 5 base, 3 extensions
  coffee.subscription: form view_subscription_form, list view_subscription_list, search view_subscription_search
  coffee.subscription.renew: form view_subscription_renew_form
  (no model): qweb report_subscription_document
  extends account.view_move_form (2): view_move_form_planner, view_move_form_planner_extra
  extends view_subscription_form (1): view_subscription_form_renew
'''
MENUS = '''menus: 5
  Planner (menu_planner_root)
    Subscriptions (menu_planner_subscriptions)
    Configuration (menu_planner_config)
      Renew (menu_planner_renew)
  Planner reports (menu_planner_reports) under base.menu_custom
'''
ACTIONS = '''actions: 3
  report action_report_subscription: coffee.subscription "Subscription" qweb-pdf
  window action_subscription: coffee.subscription "Subscriptions"
  server action_server_renew: coffee.subscription "Renew now" (written 2 times)
'''
SECURITY = '''security: 5 access rules, 2 record rules, 1 group
  group group_planner_manager "Planner manager"
  access coffee.subscription: base.group_user r---, group_planner_manager rwcu
  access coffee.subscription.line: everyone rw--
  access coffee.subscription.renew, res.partner: base.group_user rwc-
  rule rule_subscription_user: coffee.subscription, groups base.group_user, group_planner_manager
  rule rule_subscription_line_global: coffee.subscription.line, global
'''
DATA = '''data: 7 data files, 1 demo, 1 cron, 1 not in manifest, 1 missing
  data: security/security.xml, security/ir.model.access.csv, views/subscription_views.xml, \
views/account_move_views.xml, report/subscription_report.xml, data/cron.xml, views/missing.xml
  demo: demo/demo.xml
  cron ir_cron_renew "Renew subscriptions": every 1 days, coffee.subscription
  not in manifest: data/unused.xml
  missing on disk: views/missing.xml
'''
TESTS = '''tests: 2 files, 3 classes, 3 test methods
  tests/common.py: PlannerCommon
  tests/test_subscription.py: TestSubscription (2 tests), TestRenewWizard (1 test)
'''
SKIPPED = 'skipped: models/broken.py (Python error at line 2)\n'
PLANNER = HEADER + MODELS + VIEWS + MENUS + ACTIONS + SECURITY + DATA + TESTS + SKIPPED


def tree(root):
    return sorted(str(path.relative_to(root)) for path in root.rglob('*'))


class ModuleInfoTests(unittest.TestCase):
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

    def invoke(self, *args, program='oasis', project=PROJECT):
        result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / program),
                                 '--project', str(project), 'module-info', *args],
                                cwd=self.temp, env=self.env, text=True, capture_output=True)
        self.assertFalse(self.effects.exists(), 'Unexpected external service/install command')
        self.assertEqual(tree(FIXTURE), self.before, 'module-info must not write in scanned trees')
        return result

    def assert_result(self, args, code, stdout, stderr='', **kwargs):
        result = self.invoke(*args, **kwargs)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (code, stdout, stderr))

    def test_every_section_of_a_project_module_from_source_only(self):
        # Python with ast, XML with expat, CSV with csv: the venv, config and services do not exist.
        self.assertFalse((PROJECT / '.venv').exists())
        self.assertFalse((PROJECT / 'dev').exists())
        for program in ('oasis', 'odoo19'):
            with self.subTest(program=program):
                self.assert_result(('coffee_planner',), 0, PLANNER, program=program)

    def test_readme_example_is_the_fixture_output(self):
        readme = (ROOT / 'README.md').read_text()
        self.assertIn('```text\n' + PLANNER.replace(str(ADDONS), '/work/coffee/addons') + '```\n', readme)

    def test_the_first_module_with_a_name_wins(self):
        # The project also has a `coffee` module; the Odoo source is scanned first.
        self.assert_result(('coffee',), 0, f'''module: coffee — Coffee
depends: base
root: {SOURCE}
models: 2 defined, 0 extended
  coffee.order "Coffee Order" (+mail.thread): 7 fields, models/coffee_order.py:4
  coffee.order.line "Coffee Order Line": 2 fields, models/coffee_order.py:31
views: 3 base, 0 extensions
  coffee.bean: form view_coffee_bean_form
  coffee.order: form view_coffee_order_form, list view_coffee_order_list
menus: 3
  Coffee (menu_coffee_root)
    Orders (menu_coffee_order)
    Configuration (menu_coffee_config)
actions: 1
  window action_coffee_order: coffee.order "Coffee Orders"
security: 1 access rule, 0 record rules, 1 group
  group group_coffee_manager "Coffee manager"
  access coffee.order: group_coffee_manager rwcu
data: 0 data files, 0 demo, 0 crons, 2 not in manifest
  not in manifest: security/ir.model.access.csv, views/coffee_order_views.xml
tests: 1 file, 1 class, 0 test methods
  tests/test_coffee.py: SkippedTestExtension
''')

    def test_empty_sections_say_none(self):
        self.assert_result(('coffee_loyalty',), 0, f'''module: coffee_loyalty — Coffee Loyalty
depends: coffee
root: {SOURCE}
models: 0 defined, 1 extended
  extends coffee.order: 2 fields, models/coffee_order.py:4
views: 1 base, 4 extensions
  (no model): qweb report_order
  extends coffee.view_coffee_order_form (1): view_coffee_order_form_loyalty
  extends report_order (2): report_order_points, report_order_manager
  extends view_coffee_order_form_loyalty (1): view_coffee_order_form_vip
menus: none
actions: none
security: none
data: 0 data files, 0 demo, 0 crons, 1 not in manifest
  not in manifest: views/coffee_order_views.xml
tests: none
''')

    def test_section_prints_one_section(self):
        for name, text in (('models', MODELS), ('views', VIEWS), ('menus', MENUS), ('actions', ACTIONS),
                           ('security', SECURITY), ('data', DATA), ('tests', TESTS)):
            with self.subTest(section=name):
                self.assert_result(('coffee_planner', '--section', name), 0, text + SKIPPED)
        self.assert_result(('coffee_loyalty', '--section', 'menus'), 0, 'menus: none\n')

    def test_unknown_module_exits_one(self):
        self.assert_result(('coffee_missing',), 1, '', 'module not found: coffee_missing\n')
        # A directory without __manifest__.py and an Odoo source test_* module are not modules.
        self.assert_result(('not_a_module',), 1, '', 'module not found: not_a_module\n')
        self.assert_result(('test_coffee',), 1, '', 'module not found: test_coffee\n')

    def test_usage_errors_exit_two_before_reading_the_profile(self):
        project = self.temp / 'unconfigured'
        project.mkdir()
        (project / '.odoo19-agent.toml').write_text('[tooling]\n')
        for args in ((), ('a', 'b'), ('--bogus',), ('coffee', '--bogus'), ('coffee', '--section'),
                     ('coffee', '--section', 'models', '--section', 'views'), ('--section', 'models')):
            with self.subTest(args=args):
                self.assert_result(args, 2, '', USAGE, project=project)
        for value in ('../coffee', 'coffee-shop', 'coffee.shop', ''):
            with self.subTest(value=value):
                self.assert_result((value,), 2, '', MODULE_ERROR, project=project)
        for section in ('model', 'all', 'Views'):
            with self.subTest(section=section):
                self.assert_result(('coffee', '--section', section), 2, '', SECTION_ERROR, project=project)
        result = self.invoke('--help', project=project)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(USAGE[len('ERROR: '):]), result.stdout)
        self.assertIn('nothing is imported or executed', result.stdout)

    def test_long_sections_are_capped_with_the_count_of_the_rest(self):
        scratch = self.temp / 'capped'
        project = scratch / 'project'
        (scratch / 'source/odoo/odoo/addons').mkdir(parents=True)
        (project / 'addons').mkdir(parents=True)
        (project / '.odoo19-agent.toml').write_text((PROJECT / '.odoo19-agent.toml').read_text())
        module = scratch / 'source/odoo/addons/wide'
        for directory in ('models', 'views', 'data', 'security', 'tests'):
            (module / directory).mkdir(parents=True)
        count = 12  # two over the list cap
        files = [f'data/d{index:02d}.xml' for index in range(27)]
        for name in files:
            (module / name).write_text('<odoo/>\n')
        files += ['views/views.xml', 'security/ir.model.access.csv']  # four over the file cap
        (module / '__manifest__.py').write_text(repr({'name': 'Wide', 'data': files}) + '\n')
        (module / 'models/models.py').write_text('from odoo import fields, models\n' + ''.join(
            f"\n\nclass M{index:02d}(models.Model):\n    _name = 'wide.m{index:02d}'\n\n    f = fields.Char()\n"
            for index in range(count)))
        (module / 'views/views.xml').write_text('<odoo>\n' + ''.join(
            f'<record id="v{index:02d}" model="ir.ui.view"><field name="model">wide.m{index:02d}</field>'
            f'<field name="arch" type="xml"><form/></field></record>\n'
            f'<record id="a{index:02d}" model="ir.actions.act_window"><field name="res_model">wide.m{index:02d}</field>'
            '</record>\n'
            f'<menuitem id="menu{index:02d}" name="Menu {index:02d}"/>\n' for index in range(count)) + '</odoo>\n')
        (module / 'security/ir.model.access.csv').write_text(
            'id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n' + ''.join(
                f'access_{index:02d},m{index:02d},model_wide_m{index:02d},base.group_{index:02d},1,0,0,0\n'
                for index in range(count)))
        for index in range(count):
            (module / f'tests/test_t{index:02d}.py').write_text(f'class TestT{index:02d}:\n    def test_x(self):\n        pass\n')

        def run(*args):
            result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'oasis'), '--project', str(project),
                                     'module-info', 'wide', *args], cwd=self.temp, env=self.env, text=True,
                                    capture_output=True)
            self.assertEqual((result.returncode, result.stderr), (0, ''))
            return result.stdout.splitlines()

        models = [f'  wide.m{index:02d}: 1 field, models/models.py:{4 + 6 * index}' for index in range(count)]
        bases = [f'  wide.m{index:02d}: form v{index:02d}' for index in range(count)]
        menus = [f'  Menu {index:02d} (menu{index:02d})' for index in range(count)]
        actions = [f'  window a{index:02d}: wide.m{index:02d}' for index in range(count)]
        access = [f'  access wide.m{index:02d}: base.group_{index:02d} r---' for index in range(count)]
        tests = [f'  tests/test_t{index:02d}.py: TestT{index:02d} (1 test)' for index in range(count)]
        lines = run()
        expected = (['module: wide — Wide', 'depends: none', f'root: {(scratch / "source/odoo/addons").resolve()}',
                     f'models: {count} defined, 0 extended'] + models[:10] + ['  +2 more (--section models)']
                    + [f'views: {count} base, 0 extensions'] + bases[:10] + ['  +2 more (--section views)']
                    + [f'menus: {count}'] + menus[:10] + ['  +2 more (--section menus)']
                    + [f'actions: {count}'] + actions[:10] + ['  +2 more (--section actions)']
                    + [f'security: {count} access rules, 0 record rules, 0 groups'] + access[:10]
                    + ['  +2 more (--section security)']
                    + ['data: 29 data files, 0 demo, 0 crons',
                       '  data: ' + ', '.join(files[:25]) + ', +4 more (--section data)']
                    + [f'tests: {count} files, {count} classes, {count} test methods'] + tests[:10]
                    + ['  +2 more (--section tests)'])
        self.assertEqual(lines, expected)
        # --section lifts the caps.
        self.assertEqual(run('--section', 'models'), [f'models: {count} defined, 0 extended'] + models)
        self.assertEqual(run('--section', 'views'), [f'views: {count} base, 0 extensions'] + bases)
        self.assertEqual(run('--section', 'menus'), [f'menus: {count}'] + menus)
        self.assertEqual(run('--section', 'actions'), [f'actions: {count}'] + actions)
        self.assertEqual(run('--section', 'security'),
                         [f'security: {count} access rules, 0 record rules, 0 groups'] + access)
        self.assertEqual(run('--section', 'data'), ['data: 29 data files, 0 demo, 0 crons',
                                                    '  data: ' + ', '.join(files)])
        self.assertEqual(run('--section', 'tests'),
                         [f'tests: {count} files, {count} classes, {count} test methods'] + tests)


if __name__ == '__main__':
    unittest.main()
