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
# The installed entry point and its compatibility alias.
ENTRY_POINTS = ('~/.agents/skills/odoo19/oasis', '~/.agents/skills/odoo19/odoo19')
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
            if (key == 'entrypoint' and value not in ENTRY_POINTS) or (key != 'entrypoint' and value != operations[key]):
                raise ValueError('command path')
        elif (key == 'odoo_shell' or not re.fullmatch(r'[A-Za-z0-9_./-]+', value)
              or value.startswith('/') or '..' in Path(value).parts):
            raise ValueError('command path')
    if re.search(r'corpus.cafe|cc_(?:test|dev)_|password|secret|token|credential', repr(data), re.I):
        raise ValueError('customer path or credential')
    return data


# Repository-only paths: install.sh does not install them, so no installed document may link to them.
NOT_INSTALLED = ('AGENTS.md', '.gitignore', 'install.sh', 'odd')


def documents(root):
    """The landing README and every topic file under docs/."""
    return [root / 'README.md', *sorted((root / 'docs').glob('*.md'))]


def skill_documents(root):
    """Every Markdown file of the skills: each SKILL.md and its references."""
    return sorted(root.glob('odoo19-*/**/*.md'))


def headings(text):
    """Markdown headings outside fenced code blocks, as (level, title)."""
    found, fence = [], False
    for line in text.splitlines():
        if line.startswith('```'):
            fence = not fence
        elif not fence and (match := re.match(r'(#{1,6}) (.+)$', line)):
            found.append((len(match[1]), match[2].strip()))
    return found


def anchor(title):
    """The anchor GitHub gives a heading: lowercase, punctuation dropped, spaces as hyphens."""
    return re.sub(r'[^\w\- ]', '', title.lower()).replace(' ', '-')


def broken_links(files, root):
    """Relative links that do not resolve from their own file inside the installed bundle."""
    broken = []
    for path in files:
        here = path.relative_to(root).as_posix()
        for link in re.findall(r'\]\(([^)\s]+)\)', path.read_text(encoding='utf-8')):
            if re.match(r'[a-z]+:', link):
                continue
            name, _, fragment = link.partition('#')
            target = (path.parent / name).resolve() if name else path.resolve()
            try:
                relative = target.relative_to(root.resolve())
            except ValueError:
                broken.append(f'{here}: {link} (outside the bundle)')
                continue
            if relative.parts and relative.parts[0] in NOT_INSTALLED:
                broken.append(f'{here}: {link} (not installed)')
            elif not target.is_file():
                broken.append(f'{here}: {link} (missing)')
            elif fragment and target.suffix == '.md' and fragment not in {
                    anchor(title) for _, title in headings(target.read_text(encoding='utf-8'))}:
                broken.append(f'{here}: {link} (no such heading)')
    return broken


WORKSPACE = ROOT / 'odoo19-environment/assets/oasis-workspace.example.toml'
WORKSPACE_TOOLING = {key: kind for key, kind in TOOLING.items()
                     if key not in ('version', 'python_version')}


def check_workspace_example(raw):
    """Static roles of the shipped workspace example: versions on top, [tooling] without derived keys."""
    data = tomllib.loads(raw)
    if set(data) != {'workspace_version', 'odoo_version', 'tooling'}:
        raise ValueError('sections')
    if (type(data['workspace_version']) is not int or data['workspace_version'] != 1
            or data['odoo_version'] != '19.0'):
        raise ValueError('versions')
    tooling = data['tooling']
    if set(tooling) != set(WORKSPACE_TOOLING) or any(
        not isinstance(tooling[key], kind) or not tooling[key] for key, kind in WORKSPACE_TOOLING.items()
    ):
        raise ValueError('tooling')
    if (not tooling['dev_prefix'].endswith('_dev_')
            or tooling['test_prefix'] != tooling['dev_prefix'][:-4] + 'test_'):
        raise ValueError('tooling agreement')
    paths = [tooling[key] for key in WORKSPACE_TOOLING if isinstance(tooling[key], str)
             and key not in ('db_service', 'dev_prefix', 'test_prefix')]
    if any(path.startswith(('/', '~')) or '..' in Path(path).parts for path in paths):
        raise ValueError('workspace path')
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
        for entrypoint in ENTRY_POINTS:
            valid = raw + f"\n[commands]\nentrypoint = '{entrypoint}'\ntest = 'test-module'\n"
            self.assertEqual(check_example(valid)['commands']['test'], 'test-module')
        with self.assertRaisesRegex(ValueError, '^command path$'):
            check_example(raw + "\n[commands]\nentrypoint = '~/.agents/skills/odoo19/other'\n")
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
        for phrase in ('`logs`', '`LOGS_DIR`', '`<logs>/<slug, or main for the main checkout>/run-*`'):
            self.assertIn(phrase, contract)

    def test_workspace_example_schema_and_negative_examples(self):
        raw = WORKSPACE.read_text(encoding='utf-8')
        data = check_workspace_example(raw)
        self.assertEqual(data['tooling']['addons_paths'][0], '.')
        self.assertTrue(data['tooling']['dev_prefix'].startswith('acme_'))
        for broken in (raw.replace('workspace_version = 1', 'workspace_version = 2'),
                       raw.replace("odoo_version = '19.0'", "odoo_version = '18.0'"),
                       raw.replace("[tooling]", "[tooling]\nversion = '19.0'"),
                       raw.replace("[tooling]", "[tooling]\ncheckout_slug = 'acme_07_1'"),
                       raw.replace("config = 'config/odoo.conf'", "config = '/etc/odoo.conf'"),
                       raw.replace("environment = 'environments/acme'", ''),
                       raw + "\n[database_extra]\npassword = 'example'\n"):
            with self.assertRaises(ValueError):
                check_workspace_example(broken)
        # Documented but not set: logs and optional keys; the slug lives in oasis-checkout.toml.
        self.assertEqual(re.findall(r"^# logs = '([^']*)'$", raw, re.MULTILINE), ['logs'])
        self.assertEqual(re.findall(r"^#\s+checkout_slug = '([^']*)'$", raw, re.MULTILINE), ['acme_07_1'])
        for phrase in ('oasis-checkout.toml', 'addons_paths', '.odoo19-agent.toml'):
            self.assertIn(phrase, raw)
        contract = (ROOT / 'odoo19-environment/references/project-contract.md').read_text(encoding='utf-8')
        for phrase in ('`oasis-workspace.toml`', '`oasis-checkout.toml`', '`WORKSPACE_ROOT`'):
            self.assertIn(phrase, contract)
        skill = (ROOT / 'odoo19-environment/SKILL.md').read_text(encoding='utf-8')
        self.assertIn('assets/oasis-workspace.example.toml', skill)

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

    def test_documentation_links_resolve_from_their_own_file(self):
        files = documents(ROOT)
        self.assertGreater(len(files), 2)
        self.assertEqual(broken_links(files, ROOT), [])

    def test_skill_links_resolve_from_their_own_file(self):
        files = skill_documents(ROOT)
        self.assertEqual({path.parent.name for path in files if path.name == 'SKILL.md'}, NAMES)
        self.assertIn(ROOT / 'odoo19-environment/references/project-contract.md', files)
        self.assertEqual(broken_links(files, ROOT), [])

    def test_each_topic_file_has_one_h1_and_is_indexed(self):
        index = (ROOT / 'docs/README.md').read_text(encoding='utf-8')
        for path in documents(ROOT):
            with self.subTest(path=path.name):
                self.assertEqual([level for level, _ in headings(path.read_text(encoding='utf-8'))].count(1), 1)
                if path.parent.name == 'docs' and path.name != 'README.md':
                    self.assertIn(f']({path.name})', index)


if __name__ == '__main__':
    unittest.main()
