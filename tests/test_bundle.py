"""Structural checks for shipped guidance, not a runtime config validator."""
import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMES = {
    'odoo19-backend', 'odoo19-security', 'odoo19-views-frontend',
    'odoo19-testing', 'odoo19-environment', 'odoo19-module-lifecycle',
}
SECTIONS = ('Activation Contract', 'Hard Rules', 'Decision Gates',
            'Execution Steps', 'Output Contract', 'References')
CONFIG = ROOT / 'odoo19-environment/assets/odoo19-agent.example.toml'
TOOLING = {
    'version': str, 'python_version': str, 'community': str,
    'environment': str, 'config': str, 'env_file': str, 'compose': str,
    'requirements': str, 'addons_paths': list, 'db_service': str,
    'dev_prefix': str, 'test_prefix': str,
}
COMMANDS = {'entrypoint', 'check_environment', 'bootstrap', 'install', 'update',
            'test', 'module_status', 'odoo_shell'}


def check_example(raw):
    """Check static roles of the shipped example, not production config resolution."""
    data = tomllib.loads(raw)
    if not {'odoo', 'environment', 'tooling'} <= set(data) or set(data) - {'odoo', 'environment', 'tooling', 'commands'}:
        raise ValueError('sections')
    if set(data['odoo']) != {'addons_paths'} or set(data['environment']) != {'dependency_inputs', 'lock_files'}:
        raise ValueError('metadata')
    for section, fields in (('odoo', ('addons_paths',)),
                            ('environment', ('dependency_inputs', 'lock_files'))):
        for key in fields:
            value = data[section][key]
            if not isinstance(value, list) or not value or not all(isinstance(p, str) and p for p in value):
                raise ValueError(key)
    tooling = data['tooling']
    if set(tooling) != set(TOOLING) or any(
        not isinstance(tooling[key], kind) or not tooling[key] for key, kind in TOOLING.items()
    ):
        raise ValueError('tooling')
    if (tooling['version'] != '19.0' or tooling['python_version'] != '3.12'
            or not tooling['dev_prefix'].endswith('_dev_')
            or tooling['test_prefix'] != tooling['dev_prefix'][:-4] + 'test_'):
        raise ValueError('tooling agreement')
    commands = data.get('commands', {})
    if not isinstance(commands, dict):
        raise ValueError('command path')
    operations = {'check_environment': 'check-environment', 'bootstrap': 'bootstrap',
                  'install': 'install-module', 'update': 'update-module',
                  'test': 'test-module', 'module_status': 'module-status',
                  'odoo_shell': 'odoo-shell'}
    for key, value in commands.items():
        if key not in COMMANDS or not isinstance(value, str):
            raise ValueError('command path')
        if 'entrypoint' in commands:
            if (key == 'entrypoint' and value != '~/.agents/skills/odoo19/odoo19') or (key != 'entrypoint' and value != operations[key]):
                raise ValueError('command path')
        elif (key == 'odoo_shell' or not re.fullmatch(r'[A-Za-z0-9_./-]+', value)
              or value.startswith('/') or '..' in Path(value).parts):
            raise ValueError('command path')
    if re.search(r'corpus.cafe|cc_(?:test|dev)_|password|secret|token|credential', repr(data), re.I):
        raise ValueError('customer path or credential')
    return data


class BundleTests(unittest.TestCase):
    def test_six_unique_skill_contracts(self):
        skills = sorted(ROOT.glob('*/SKILL.md'))
        self.assertEqual({path.parent.name for path in skills}, NAMES)
        names = []
        for path in skills:
            with self.subTest(path=path):
                text = path.read_text(encoding='utf-8')
                parts = text.split('---\n', 2)
                self.assertEqual(len(parts), 3)
                front = parts[1].strip().splitlines()
                self.assertEqual(len(front), 6)
                self.assertEqual(front[0], f'name: {path.parent.name}')
                self.assertRegex(front[1], r'^description: "Trigger: [^"\n]+"$')
                self.assertEqual(front[2:], ['license: Apache-2.0', 'metadata:',
                                             '  author: openalliance', '  version: "1.0"'])
                names.append(front[0])
                self.assertEqual(re.findall(r'^## (.+)$', parts[2], re.M), list(SECTIONS))
                self.assertLessEqual(len(text.split()), 450)
                self.assertGreaterEqual(len(text.split()), 180)
                for link in re.findall(r'\]\(([^)]+)\)', parts[2]):
                    self.assertTrue((path.parent / link).is_file(), link)
                self.assertNotRegex(text.lower(), r'corpus.cafe|cc_(?:test|dev)_')
        self.assertEqual(len(names), len(set(names)))
        self.assertFalse((ROOT / 'SKILL.md').exists())

    def test_example_schema_and_negative_examples(self):
        raw = CONFIG.read_text(encoding='utf-8')
        data = check_example(raw)
        self.assertEqual(data['odoo']['addons_paths'][0], data['tooling']['addons_paths'][0])
        self.assertNotEqual(data['odoo']['addons_paths'], data['tooling']['addons_paths'])
        self.assertNotIn('commands', data)
        valid = raw + "\n[commands]\nentrypoint = '~/.agents/skills/odoo19/odoo19'\ntest = 'test-module'\n"
        self.assertEqual(check_example(valid)['commands']['test'], 'test-module')
        with self.assertRaises(ValueError):
            check_example(raw.replace("version = '19.0'", "version = '18.0'"))
        with self.assertRaises(ValueError):
            check_example(raw.replace("environment = '.venv'", ''))
        with self.assertRaisesRegex(ValueError, '^command path$'):
            check_example(raw + "\n[commands]\ntest = 'bash -c unsafe'\n")
        with self.assertRaisesRegex(ValueError, '^command path$'):
            check_example(raw + "\n[commands]\ntest = '../outside'\n")
        with self.assertRaises(ValueError):
            check_example(raw + "\n[database_extra]\npassword = 'example'\n")

    def test_checkout_slug_is_documented_but_not_set_in_the_example(self):
        raw = CONFIG.read_text(encoding='utf-8')
        self.assertNotIn('checkout_slug', tomllib.loads(raw)['tooling'])
        documented = re.findall(r"^# checkout_slug = '([^']*)'$", raw, re.MULTILINE)
        self.assertEqual(len(documented), 1)
        self.assertRegex(documented[0], r'^[a-z0-9][a-z0-9_]{0,19}$')
        contract = (ROOT / 'odoo19-environment/references/project-contract.md').read_text(encoding='utf-8')
        for phrase in ('`checkout_slug`', '`CHECKOUT_KIND`', '`CHECKOUT_SLUG`'):
            self.assertIn(phrase, contract)

    def test_logs_is_documented_but_not_set_in_the_example(self):
        raw = CONFIG.read_text(encoding='utf-8')
        self.assertNotIn('logs', tomllib.loads(raw)['tooling'])
        self.assertEqual(re.findall(r"^# logs = '([^']*)'$", raw, re.MULTILINE), ['../logs'])
        contract = (ROOT / 'odoo19-environment/references/project-contract.md').read_text(encoding='utf-8')
        for phrase in ('`logs`', '`LOGS_DIR`', '<logs>/odoo19/'):
            self.assertIn(phrase, contract)

    def test_reference_and_package_docs(self):
        reference = ROOT / 'odoo19-environment/references/project-contract.md'
        self.assertTrue(reference.is_file())
        text = reference.read_text(encoding='utf-8')
        for phrase in ('optional advisory duplicates', 'rejects conflicts', '[tooling].addons_paths',
                       'exact per-target human consent'):
            self.assertIn(phrase, text)
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('not a seventh skill', readme)
        self.assertIn('/reload', readme)
        for link in re.findall(r'\]\(([^)]+)\)', readme):
            self.assertTrue((ROOT / link).is_file(), link)


if __name__ == '__main__':
    unittest.main()
