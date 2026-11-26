"""The agent policy table (tools/policy.py, v0.16.0 S1) and what follows it: its JSON export, the
Gentle Shell guard's generated module, the docs and the skills."""
import oasis_test_env  # noqa: F401  first: XDG_CONFIG_HOME is scratch (tests/oasis_test_env.py)
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('oasis_policy', ROOT / 'tools/policy.py')
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)


def tiers():
    return {row['operation']: row['tier'] for row in policy.operations()}


class PolicyTableTests(unittest.TestCase):
    def test_tiers_follow_s1(self):
        table = tiers()
        for operation in ('setup', 'setup --apply', 'bootstrap', 'create-database', 'start', 'stop', 'restart',
                          'start-database',
                          'install-module', 'update-module', 'doctor', 'check-environment', 'gc', 'gc --apply',
                          'test-module', 'verify-module', 'migrate --plan', 'worktree-init --dry-run'):
            self.assertEqual(table[operation], 'A', operation)
        for operation in ('worktree-init', 'migrate --apply', 'drop-database', 'gc --apply --trash',
                          'recreate-database-volume', 'create a branch'):
            self.assertEqual(table[operation], 'B', operation)
        self.assertEqual(table['type a password'], 'C')

    def test_a_deprecated_alias_has_the_tier_of_its_target(self):
        # v0.16.0 S5: check-environment runs doctor --environment; both keep a row of the same tier, and the
        # alias's reason says what it is.
        self.assertEqual(policy.ALIASES, {'check-environment': 'doctor --environment'})
        rows = {row['operation']: row for row in policy.operations()}
        for alias, target in policy.ALIASES.items():
            self.assertEqual(rows[alias]['tier'], rows[target]['tier'], alias)
            self.assertEqual(rows[alias]['kind'], rows[target]['kind'], alias)
            self.assertTrue(rows[alias]['reason'].startswith(f'deprecated alias of {target}; '), rows[alias])
        self.assertEqual(rows['doctor --environment']['example'], 'oasis --project /p doctor --environment --quick')
        # The entry point lists the same aliases in its help.
        tree = ast.parse((ROOT / 'oasis').read_text(encoding='utf-8'))
        [listed] = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                    and [target.id for target in node.targets if isinstance(target, ast.Name)] == ['DEPRECATED_ALIASES']]
        self.assertEqual(listed, policy.ALIASES)

    def test_every_row_is_complete_and_unique(self):
        rows = policy.operations()
        self.assertEqual(len({row['operation'] for row in rows}), len(rows))
        for row in rows:
            self.assertIn(row['tier'], policy.TIERS, row)
            self.assertIn(row['kind'], ('oasis', 'program', 'action'), row)
            self.assertTrue(row['reason'] and not row['reason'].endswith('.'), row)
            self.assertEqual(row['example'] is None, row['kind'] == 'action', row)
        self.assertEqual(policy.HARNESS, {'A': 'allow', 'B': 'ask', 'C': 'deny'})
        # Every Tier B oasis command takes --confirm <exact name>, except stop --database (a decision).
        self.assertEqual({row['operation'] for row in rows if row['confirm']},
                         {row['operation'] for row in rows if row['tier'] == 'B' and row['kind'] == 'oasis'}
                         - {'stop --database'})

    def test_every_entry_point_command_has_a_row(self):
        # The guard and the docs read the table: a command the entry point runs without a row would
        # have no tier, so each one has at least its own row, and no row names another command.
        tree = ast.parse((ROOT / 'oasis').read_text(encoding='utf-8'))
        [commands] = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                      and [target.id for target in node.targets if isinstance(target, ast.Name)] == ['COMMANDS']]
        rows = {row['operation'].split()[0] for row in policy.operations() if row['kind'] == 'oasis'}
        self.assertEqual(sorted(set(commands) - rows), [], 'oasis COMMANDS without a policy row')
        self.assertEqual(sorted(rows - set(commands)), [], 'policy rows for no oasis command')
        self.assertEqual(tiers()['policy'], 'A')

    def test_json_export_is_the_table(self):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/policy.py'), '--json'],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        data = json.loads(result.stdout)
        self.assertEqual(data, {'version': 1, 'tiers': policy.TIERS, 'harness': policy.HARNESS,
                                'operations': policy.operations()})

    def test_oasis_policy_json_through_both_entry_points(self):
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'GIT_CEILING_DIRECTORIES': tempfile.gettempdir()}
        with tempfile.TemporaryDirectory() as scratch:
            for program in ('oasis',):
                with self.subTest(program=program):
                    result = subprocess.run([sys.executable, '-B', str(ROOT / program), '--project', scratch,
                                             'policy', '--json'], capture_output=True, text=True, env=env, timeout=30)
                    self.assertEqual((result.returncode, result.stderr), (0, ''))
                    self.assertEqual(result.stdout, policy.as_json())
                    usage = subprocess.run([sys.executable, '-B', str(ROOT / program), '--project', scratch, 'policy'],
                                           capture_output=True, text=True, env=env, timeout=30)
                    self.assertEqual((usage.returncode, usage.stdout), (2, ''))
                    self.assertEqual(usage.stderr, f'Usage: {(ROOT / program).resolve()} policy --json\n')

    def test_stop_database_stays_tier_b_as_a_recorded_decision(self):
        self.assertEqual(tiers()['stop --database'], 'B')
        contract = (ROOT / 'docs/agent-contract.md').read_text(encoding='utf-8')
        self.assertIn('Decision (v0.16.0): `stop --database` stays Tier B', contract)

    def test_usage_error(self):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/policy.py')],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual((result.returncode, result.stdout),
                         (2, ''))
        self.assertEqual(result.stderr, 'Usage: policy.py --json | --typescript | --markdown | --guard\n')

    def test_guard_module_is_generated_from_the_table(self):
        generated = (ROOT / 'pi/lib/policy.generated.ts').read_text(encoding='utf-8')
        self.assertEqual(generated, policy.as_typescript(),
                         'pi/lib/policy.generated.ts drifted: python3 -B tools/policy.py --typescript '
                         '> pi/lib/policy.generated.ts')

    def test_docs_hold_the_generated_tables(self):
        contract = (ROOT / 'docs/agent-contract.md').read_text(encoding='utf-8')
        self.assertIn(policy.as_markdown(), contract, 'docs/agent-contract.md: python3 -B tools/policy.py --markdown')
        guard = (ROOT / 'docs/bash-guard.md').read_text(encoding='utf-8')
        self.assertIn(policy.as_guard(), guard, 'docs/bash-guard.md: python3 -B tools/policy.py --guard')

    def test_skills_follow_the_table_for_gc_apply(self):
        for path in ('odoo-environment/references/project-contract.md', 'odoo-testing/references/test-targets.md',
                     'odoo-module-lifecycle/SKILL.md'):
            text = (ROOT / path).read_text(encoding='utf-8')
            for phrase in ('only the user runs `gc --apply`', 'user-run `gc --apply`'):
                self.assertNotIn(phrase, text, path)
            self.assertIn('docs/agent-contract.md', text, path)


if __name__ == '__main__':
    unittest.main()
