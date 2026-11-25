"""Structural checks for shipped guidance, not a runtime config validator."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import ast
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
# The legacy per-checkout profile: no longer read; only docs/migrating.md describes it (how to
# convert one), the README notes the contract change and the bash guard keeps it in its setting files.
LEGACY_PROFILE = '.odoo19-agent.toml'
LEGACY_MENTIONS = {'README.md', 'docs/migrating.md', 'docs/bash-guard.md'}


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
# The Odoo source is the machine file's (v0.14.0 S10): the example sets no community or enterprise.
WORKSPACE_TOOLING = {
    'environment': str, 'config': str, 'env_file': str, 'compose': str,
    'requirements': str, 'addons_paths': list, 'db_service': str, 'dev_prefix': str, 'test_prefix': str,
}


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

    def test_the_legacy_profile_example_is_gone_and_only_migrating_describes_the_format(self):
        self.assertFalse((ROOT / 'odoo19-environment/assets/odoo19-agent.example.toml').exists())
        shipped = [*documents(ROOT), *skill_documents(ROOT), *sorted(ROOT.glob('odoo19-*/assets/*'))]
        mentions = {path.relative_to(ROOT).as_posix() for path in shipped
                    if LEGACY_PROFILE in path.read_text(encoding='utf-8')}
        self.assertEqual(mentions, LEGACY_MENTIONS)

    def test_checkout_slug_is_documented_but_not_set_in_the_workspace_example(self):
        raw = WORKSPACE.read_text(encoding='utf-8')
        self.assertNotIn('checkout_slug', tomllib.loads(raw)['tooling'])
        documented = re.findall(r"^#\s+checkout_slug = '([^']*)'$", raw, re.MULTILINE)
        self.assertEqual(len(documented), 1)
        self.assertRegex(documented[0], r'^[a-z0-9][a-z0-9_]{0,19}$')
        contract = (ROOT / 'odoo19-environment/references/project-contract.md').read_text(encoding='utf-8')
        for phrase in ('`checkout_slug`', '`CHECKOUT_KIND`', '`CHECKOUT_SLUG`'):
            self.assertIn(phrase, contract)

    def test_logs_is_documented_but_not_set_in_the_workspace_example(self):
        raw = WORKSPACE.read_text(encoding='utf-8')
        self.assertNotIn('logs', tomllib.loads(raw)['tooling'])
        self.assertEqual(re.findall(r"^# logs = '([^']*)'$", raw, re.MULTILINE), ['logs'])
        contract = (ROOT / 'odoo19-environment/references/project-contract.md').read_text(encoding='utf-8')
        for phrase in ('`logs`', '`LOGS_DIR`', '`<logs>/<slug, or main for the main checkout>/run-*`'):
            self.assertIn(phrase, contract)

    def test_agent_destructive_is_documented_but_not_set_in_the_workspace_example(self):
        raw = WORKSPACE.read_text(encoding='utf-8')
        self.assertNotIn('agent_destructive', tomllib.loads(raw)['tooling'])
        self.assertEqual(re.findall(r"^# agent_destructive = '([^']*)'$", raw, re.MULTILINE), ['ask'])
        comment = raw[:raw.index("# agent_destructive = 'ask'")].rsplit('\n\n', 1)[-1]
        for value in ("'ask'", "'deny'", "'allow'"):
            self.assertIn(value, comment)

    def test_the_workspace_example_leaves_the_source_to_the_machine_file(self):
        # S10: the machine file is the default place for the source; a project sets it only to override.
        raw = WORKSPACE.read_text(encoding='utf-8')
        tooling = tomllib.loads(raw)['tooling']
        self.assertNotIn('community', tooling)
        self.assertNotIn('enterprise', tooling)
        self.assertEqual(re.findall(r"^# (community|enterprise) = ", raw, re.MULTILINE), ['community', 'enterprise'])
        for phrase in ('~/.config/oasis/config.toml', '$XDG_CONFIG_HOME', '[series."19.0"]', 'override'):
            self.assertIn(phrase, raw)

    def test_every_test_module_isolates_the_machine_file_first(self):
        # AGENTS.md: tests never read the real configuration. oasis_test_env points XDG_CONFIG_HOME
        # at scratch; each test module imports it before anything else, so that holds for the whole
        # suite and for one module run alone.
        missing = []
        for path in sorted((ROOT / 'tests').glob('test_*.py')):
            imports = [node for node in ast.parse(path.read_text(encoding='utf-8')).body
                       if isinstance(node, (ast.Import, ast.ImportFrom))]
            first = imports[0] if imports else None
            if not (isinstance(first, ast.Import) and [alias.name for alias in first.names] == ['oasis_test_env']):
                missing.append(path.name)
        self.assertEqual(missing, [])

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
        # Documented but not set: the slug lives in oasis-checkout.toml.
        self.assertEqual(re.findall(r"^#\s+checkout_slug = '([^']*)'$", raw, re.MULTILINE), ['acme_07_1'])
        for phrase in ('oasis-checkout.toml', 'addons_paths'):
            self.assertIn(phrase, raw)
        contract = (ROOT / 'odoo19-environment/references/project-contract.md').read_text(encoding='utf-8')
        for phrase in ('`oasis-workspace.toml`', '`oasis-checkout.toml`', '`WORKSPACE_ROOT`'):
            self.assertIn(phrase, contract)
        skill = (ROOT / 'odoo19-environment/SKILL.md').read_text(encoding='utf-8')
        self.assertIn('assets/oasis-workspace.example.toml', skill)
        # v0.14.0 S4: a linked worktree outside the workspace reads its main checkout's file through
        # git, and worktree-init takes --path.
        for phrase in ('through git', '`git rev-parse --git-common-dir`', 'worktree-init <feature> <branch> [--path <dir>]'):
            self.assertIn(phrase, contract)
        self.assertIn("its main checkout's through git", skill)

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
