"""model-info contracts on a committed synthetic source tree; no runtime, service or database."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/model_info'
PROJECT = FIXTURE / 'project'
HEADER = "model: coffee.order — Coffee Order (table coffee_order, order 'date desc, id')\n"
DEFINED = 'defined: coffee coffee/models/coffee_order.py:4 inherits mail.thread\n'
USAGE = ('ERROR: Usage: model-info <model> [--field <name>] [--module <technical>] '
         '[--methods] [--all-fields]\n')


def tree(root):
    return sorted(str(path.relative_to(root)) for path in root.rglob('*'))


class ModelInfoTests(unittest.TestCase):
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

    def invoke(self, *args, project=PROJECT):
        result = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'oasis'),
                                 '--project', str(project), 'model-info', *args],
                                cwd=self.temp, env=self.env, text=True, capture_output=True)
        self.assertFalse(self.effects.exists(), 'Unexpected external service/install command')
        self.assertEqual(tree(FIXTURE), self.before, 'model-info must not write in scanned trees')
        return result

    def assert_result(self, args, code, stdout, stderr='', **kwargs):
        result = self.invoke(*args, **kwargs)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (code, stdout, stderr))

    def test_definition_extensions_fields_overrides_and_methods_without_runtime(self):
        self.assertFalse((PROJECT / '.venv').exists())
        self.assertFalse((PROJECT / 'dev').exists())
        self.assert_result(('coffee.order',), 0, HEADER + DEFINED + (
            'extended by (2): coffee_loyalty, coffee_shop(+mail.activity.mixin)\n'
            'fields (9):\n'
            '  name Char "Reference" required readonly default\n'
            '  partner_id Many2one(res.partner) "Customer" required index\n'
            '  line_ids One2many(coffee.order.line:order_id) "Lines"\n'
            '  state Selection [draft, done] default tracking\n'
            '  amount Float store compute\n'
            '  total Float compute=_compute_amount\n'
            '  note Text "Internal note for the barista and the c…" readonly=False groups=base.group_user\n'
            '  points Integer [coffee_loyalty]\n'
            '  barista_id Many2one(res.users) [coffee_shop]\n'
            'overrides (2):\n'
            '  coffee_loyalty: state Selection +[loyal]\n'
            '  coffee_shop: amount Float groups=base.group_user\n'
            'methods (private: use --module or --methods):\n'
            '  coffee: create, action_done, +1 private\n'
            '  coffee_loyalty: action_done\n'
            '  coffee_shop: +3 private\n'))

    def test_methods_flag_adds_decorators_and_super_calls(self):
        result = self.invoke('coffee.order', '--methods')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.endswith(
            'methods:\n'
            '  coffee:\n'
            '    _compute_amount @api.depends(line_ids.price, line_ids.qty)\n'
            '    create @api.model_create_multi super\n'
            '    action_done\n'
            '  coffee_loyalty:\n'
            '    action_done super\n'
            '  coffee_shop:\n'
            '    _check_barista @api.constrains(barista_id)\n'
            '    _onchange_partner @api.onchange(partner_id)\n'
            '    _compute_amount super\n'), result.stdout)

    def test_field_shows_definition_and_overrides_with_locations(self):
        self.assert_result(('coffee.order', '--field', 'state'), 0, HEADER + (
            'field state:\n'
            '  coffee/models/coffee_order.py:13 Selection [draft, done] default tracking\n'
            '  coffee_loyalty/models/coffee_order.py:8 Selection +[loyal]\n'))
        self.assert_result(('coffee.order', '--field', 'state', '--module', 'coffee_loyalty'), 0,
                           HEADER + 'field state:\n'
                           '  coffee_loyalty/models/coffee_order.py:8 Selection +[loyal]\n')
        self.assert_result(('coffee.order', '--field', 'missing_field'), 1, '',
                           'field not found: coffee.order.missing_field\n')

    def test_module_restricts_extension_override_and_method_details(self):
        self.assert_result(('coffee.order', '--module', 'coffee_shop'), 0, HEADER + DEFINED + (
            'extended in coffee_shop: coffee_shop/models/coffee_order.py:4 (+mail.activity.mixin)\n'
            'fields (1):\n'
            '  barista_id Many2one(res.users)\n'
            'overrides (1):\n'
            '  coffee_shop: amount Float groups=base.group_user\n'
            'methods:\n'
            '  coffee_shop: _check_barista, _onchange_partner, _compute_amount\n'))
        self.assert_result(('coffee.order', '--module', 'base'), 1, '',
                           'module does not define or extend coffee.order: base\n')

    def test_field_cap_and_all_fields(self):
        source = self.temp / 'source/odoo/addons/wide'
        (source / 'models').mkdir(parents=True)
        (source / '__manifest__.py').write_text("{'name': 'Wide'}\n")
        (source / 'models/wide.py').write_text(
            "from odoo import fields, models\n\n\nclass Wide(models.Model):\n    _name = 'wide.model'\n"
            + ''.join(f'    f{index} = fields.Char()\n' for index in range(42)))
        project = self.temp / 'project'
        project.mkdir()
        (project / 'oasis-workspace.toml').write_text(
            (PROJECT / 'oasis-workspace.toml').read_text().replace("addons_paths = ['addons']",
                                                                 "addons_paths = ['.']"))
        result = self.invoke('wide.model', project=project)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        lines = result.stdout.splitlines()
        self.assertEqual(lines[:4], ['model: wide.model (table wide_model)',
                                     'defined: wide wide/models/wide.py:4', 'fields (42):', '  f0 Char'])
        self.assertEqual(lines[43:], ['  ... +2 more (use --all-fields or --field)'])
        result = self.invoke('wide.model', '--all-fields', project=project)
        self.assertEqual(result.stdout.splitlines()[43:], ['  f40 Char', '  f41 Char'])

    def test_unknown_model_exits_one(self):
        self.assert_result(('coffee.missing',), 1, '', 'model not found: coffee.missing\n')
        # A class with a different _name, a test_* source module, tests/ and a directory
        # without __manifest__.py never count as definitions or extensions.
        self.assert_result(('coffee.shop', '--field', 'test_only'), 1, '',
                           'field not found: coffee.shop.test_only\n')
        result = self.invoke('coffee.order', '--all-fields')
        for name in ('shop_only', 'test_only', 'skipped', 'ignored', 'test_coffee', 'not_a_module'):
            self.assertNotIn(name, result.stdout)

    def test_invalid_arguments_exit_two_before_reading_the_profile(self):
        project = self.temp / 'unconfigured'
        project.mkdir()
        (project / 'oasis-workspace.toml').write_text('[tooling]\n')
        name = 'ERROR: Invalid model name: use lowercase dotted words such as sale.order.\n'
        for args, stderr in (((), USAGE), (('a.b', 'c.d'), USAGE), (('a.b', '--unknown'), USAGE),
                             (('a.b', '--field'), USAGE), (('Coffee.Order',), name),
                             (('coffee..order',), name), (('../coffee',), name), (('coffee order',), name),
                             (('a.b', '--field', 'bad-name'), 'ERROR: Invalid field name.\n'),
                             (('a.b', '--module', '../x'),
                              'ERROR: Module must use only letters, numbers, and underscores.\n')):
            with self.subTest(args=args):
                self.assert_result(args, 2, '', stderr, project=project)

    def test_help_needs_no_profile_values(self):
        project = self.temp / 'unconfigured'
        project.mkdir()
        (project / 'oasis-workspace.toml').write_text('[tooling]\n')
        result = self.invoke('--help', project=project)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertTrue(result.stdout.startswith(
            'Usage: model-info <model> [--field <name>] [--module <technical>] [--methods] [--all-fields]\n'))
        self.assertIn('no project code is imported or executed', result.stdout)


if __name__ == '__main__':
    unittest.main()
