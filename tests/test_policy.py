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
        for operation in ('setup', 'setup --apply', 'bootstrap', 'start', 'stop', 'restart',
                          'setup-postgres',
                          'install-module', 'update-module', 'doctor', 'doctor --environment', 'gc', 'gc --apply',
                          'test-module', 'verify-module', 'worktree-init --dry-run'):
            self.assertEqual(table[operation], 'A', operation)
        for operation in ('worktree-init', 'drop-database', 'gc --apply --trash',
                          'recreate-postgres-volume', 'create a branch'):
            self.assertEqual(table[operation], 'B', operation)
        self.assertEqual(table['type a password'], 'C')

    def test_creating_a_database_is_tier_b_v0_20_0(self):
        # v0.20.0 S5, S12: create-database, the one command that creates a database, is Tier B; its plan and dry
        # run change nothing. install-module installs into an existing database only: one Tier A row, no --confirm
        # and no --dry-run. The disposable and the kept test databases of test-module/verify-module stay A.
        table, rows = tiers(), {row['operation']: row for row in policy.operations()}
        self.assertEqual((table['create-database'], rows['create-database']['confirm']), ('B', 'database name'))
        for operation in ('create-database --plan', 'create-database --dry-run', 'install-module',
                          'test-module', 'verify-module'):
            self.assertEqual((table[operation], rows[operation]['confirm']), ('A', None), operation)
        self.assertEqual(sorted(operation for operation in table if operation.split()[0] == 'install-module'),
                         ['install-module'])
        self.assertEqual(rows['install-module']['reason'],
                         'installs a module in an existing managed database; it never creates one (create-database '
                         'does)')
        self.assertEqual(rows['create-database --plan']['example'],
                         'oasis --project /p create-database --plan --json')
        self.assertIn('language and country', rows['create-database --plan']['reason'])
        self.assertIn('the one oasis command that creates a database', rows['create-database']['reason'])
        # v0.20.0 S12: init-dev-database is gone, no alias.
        self.assertEqual([operation for operation in table if operation.split()[0] == 'init-dev-database'], [])

    def test_the_deprecated_aliases_have_no_row(self):
        # v0.21.0 S7: check-environment, start-database and recreate-database-volume are gone; the commands they
        # named keep their rows, tiers and --confirm.
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/policy.py'), '--json'], text=True,
                                capture_output=True)
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        rows = {row['operation']: row for row in json.loads(result.stdout)['operations']}
        for name in ('check-environment', 'start-database', 'recreate-database-volume'):
            self.assertNotIn(name, rows)
            self.assertNotIn(name, result.stdout)
        self.assertNotIn('deprecated alias', result.stdout)
        self.assertEqual(rows['doctor --environment']['example'], 'oasis --project /p doctor --environment --quick')
        self.assertEqual((rows['recreate-postgres-volume']['tier'], rows['recreate-postgres-volume']['confirm']),
                         ('B', 'compose project'))
        self.assertEqual((rows['setup-postgres']['tier'], rows['setup-postgres']['confirm']), ('A', None))

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
