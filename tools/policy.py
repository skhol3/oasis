#!/usr/bin/env python3
"""The oasis agent policy: every operation, its tier and why (one table, for any agent or harness).

Tiers:
  A  the agent does it alone: reversible or rebuildable;
  B  the agent proposes it and a person confirms it explicitly: data loss or hard to undo;
  C  only a person does it.

The table is the contract. Docs (docs/agent-contract.md, docs/bash-guard.md), skills, messages and
any harness guard follow it; changing a tier is a contract change (README, CHANGELOG). The Gentle
Shell guard reads it from pi/lib/policy.generated.ts, which `--typescript` prints; tests fail when
either drifts from this table.

Usage (`oasis policy --json` through the entry point):
  policy.py --json         the table as JSON (version, tiers, harness, operations)
  policy.py --typescript   pi/lib/policy.generated.ts
  policy.py --markdown     the table of docs/agent-contract.md
  policy.py --guard        the tier table of docs/bash-guard.md
"""
import json
import os
import sys

VERSION = 1
TIERS = {
    'A': 'The agent does it alone: reversible or rebuildable.',
    'B': 'The agent proposes it and a person confirms it explicitly: data loss or hard to undo.',
    'C': 'Only a person does it.',
}
# What a harness does with each tier for its agent: run it, confirm it with the person, refuse it.
HARNESS = {'A': 'allow', 'B': 'ask', 'C': 'deny'}
# kind: `oasis` an oasis command (through the entry points or their tool scripts); `program` a
# program outside oasis; `action` something that is not one command. example: a command line the
# Gentle Shell guard classifies as this operation (pi/tests/policy.test.ts runs every one).
OPERATIONS = (
    ('setup', 'A', 'oasis', 'prints the plan of the configuration; changes nothing',
     'oasis --project /p setup'),
    ('setup --apply', 'A', 'oasis', 'creates only the missing configuration and environment; rebuildable',
     'oasis --project /p setup --apply'),
    ('bootstrap', 'A', 'oasis', 'creates the virtual environment from the lock; rebuildable',
     'oasis --project /p bootstrap'),
    ('create-database', 'A', 'oasis', 'creates a managed database; drop-database moves it to the trash',
     'oasis --project /p create-database cc_dev_x'),
    ('init-dev-database', 'A', 'oasis', 'creates a development database with role accounts; rebuildable',
     'oasis --project /p init-dev-database coffee cc_dev_x'),
    ('start', 'A', 'oasis', "starts this checkout's Odoo server", 'oasis --project /p start'),
    ('restart', 'A', 'oasis', "restarts this checkout's Odoo server", 'oasis --project /p restart'),
    ('stop', 'A', 'oasis', "stops this checkout's Odoo server; start runs it again", 'oasis --project /p stop'),
    ('status', 'A', 'oasis', 'reads and reports; changes nothing', 'oasis --project /p status'),
    ('stop --database', 'B', 'oasis',
     'stops the database service every checkout shares, ending the sessions of a server on it',
     'oasis --project /p stop --database'),
    ('install-module', 'A', 'oasis', 'installs a module in a managed database',
     'oasis --project /p install-module coffee cc_dev_x'),
    ('update-module', 'A', 'oasis', 'updates a module in a managed database',
     'oasis --project /p update-module coffee cc_dev_x'),
    ('test-module', 'A', 'oasis', 'runs tests on a disposable database dropped afterwards',
     'oasis --project /p test-module coffee'),
    ('verify-module', 'A', 'oasis', 'lints, updates and tests a module on disposable databases',
     'oasis --project /p verify-module coffee'),
    ('lint-module', 'A', 'oasis', 'reads and reports; changes nothing', 'oasis --project /p lint-module coffee'),
    ('odoo-shell', 'A', 'oasis', 'an Odoo shell on a managed database', 'oasis --project /p odoo-shell cc_dev_x'),
    ('list-databases', 'A', 'oasis', 'reads and reports; changes nothing', 'oasis --project /p list-databases'),
    ('module-status', 'A', 'oasis', 'reads and reports; changes nothing',
     'oasis --project /p module-status coffee cc_dev_x'),
    ('model-info', 'A', 'oasis', 'reads source; changes nothing', 'oasis --project /p model-info sale.order'),
    ('module-info', 'A', 'oasis', 'reads source; changes nothing', 'oasis --project /p module-info coffee'),
    ('view-info', 'A', 'oasis', 'reads source; changes nothing', 'oasis --project /p view-info sale.order'),
    ('xmlid-info', 'A', 'oasis', 'reads source; changes nothing', 'oasis --project /p xmlid-info sale.view_order_form'),
    ('audit-dependencies', 'A', 'oasis', 'reads and reports; changes nothing',
     'oasis --project /p audit-dependencies'),
    ('doctor', 'A', 'oasis', 'reads and reports; changes nothing', 'oasis --project /p doctor'),
    ('check-environment', 'A', 'oasis', 'reads and reports; changes nothing',
     'oasis --project /p check-environment --quick'),
    ('policy', 'A', 'oasis', 'prints this policy table; changes nothing', 'oasis --project /p policy --json'),
    ('gc', 'A', 'oasis', 'lists leftover disposable test databases; changes nothing', 'oasis --project /p gc'),
    ('gc --apply', 'A', 'oasis', 'drops disposable test databases no live run holds; rebuildable',
     'oasis --project /p gc --apply'),
    ('gc --trash', 'A', 'oasis', 'lists the expired trash entries; changes nothing',
     'oasis --project /p gc --trash'),
    ('gc --apply --trash', 'B', 'oasis', 'drops the expired trash entries for good',
     'oasis --project /p gc --apply --trash'),
    ('drop-database', 'B', 'oasis', 'takes a database (and its filestore) out of use; only trash restore brings it back',
     'oasis --project /p drop-database cc_dev_x'),
    ('recreate-database-volume', 'B', 'oasis',
     'deletes the PostgreSQL volume of the compose project and every database in it, then starts the service '
     'again', 'oasis --project /p recreate-database-volume'),
    ('trash', 'A', 'oasis', 'lists the trash; trash restore brings an entry back', 'oasis --project /p trash'),
    ('migrate', 'A', 'oasis', 'without --apply it prints the migration plan; changes nothing',
     'oasis --project /p migrate'),
    ('migrate --plan', 'A', 'oasis', 'prints the migration plan; changes nothing',
     'oasis --project /p migrate --plan'),
    ('migrate --apply', 'B', 'oasis', "rewrites the project's configuration files",
     'oasis --project /p migrate --apply'),
    ('worktree-init --dry-run', 'A', 'oasis', 'prints the worktree plan; changes nothing',
     'oasis --project /p worktree-init feat feature/x --dry-run'),
    ('worktree-init', 'B', 'oasis', 'adds a git worktree and, when it does not exist, a new branch',
     'oasis --project /p worktree-init feat feature/x'),
    ('menu', 'C', 'oasis', 'the interactive menu for a person at a terminal; agents run the commands it lists',
     'oasis --project /p menu'),
    ('odoo-bin', 'C', 'program', 'in an Odoo project it bypasses the database prefix guards: use the oasis commands',
     'odoo-bin -d x'),
    ('dropdb', 'C', 'program', 'in an Odoo project it bypasses the database prefix guards: use drop-database',
     'dropdb x'),
    ('psql', 'C', 'program', 'in an Odoo project it bypasses the database prefix guards: use the oasis commands',
     'psql -l'),
    ('create a branch', 'B', 'action', "adds a branch to the person's repository", None),
    ('edit a setting file', 'B', 'action',
     'the files that hold [tooling].agent_destructive, a checkout\'s oasis-checkout.toml and the machine file '
     "change the agent's own permission, a database namespace or the Odoo source",
     None),
    ('type a password', 'C', 'action', 'only when the person wants their own; no oasis workflow needs one', None),
)
KEYS = ('operation', 'tier', 'kind', 'reason', 'example')
# What `--confirm` takes for a Tier B oasis command (its refusal names the exact command); a Tier B
# operation without one is confirmed only by a person or a harness dialog (stop --database).
CONFIRM = {'drop-database': 'database name', 'gc --apply --trash': 'project root',
           'migrate --apply': 'workspace file', 'worktree-init': 'worktree path',
           'recreate-database-volume': 'compose project'}


def operations() -> list[dict]:
    return [{**dict(zip(KEYS, row)), 'confirm': CONFIRM.get(row[0])} for row in OPERATIONS]


def tier(operation: str) -> str:
    """The tier of an operation of the table; KeyError for any other."""
    return {row[0]: row[1] for row in OPERATIONS}[operation]


def as_json() -> str:
    return json.dumps({'version': VERSION, 'tiers': TIERS, 'harness': HARNESS, 'operations': operations()},
                      indent=2) + '\n'


def as_typescript() -> str:
    data = ''.join(f'  {json.dumps(row)},\n' for row in operations())
    return ('// Generated by `python3 -B tools/policy.py --typescript` from tools/policy.py: do not edit.\n'
            '// tests/test_policy.py fails when it drifts from the table.\n'
            'export type Tier = "A" | "B" | "C";\n'
            'export interface PolicyEntry {\n'
            '  operation: string;\n'
            '  tier: Tier;\n'
            '  kind: "oasis" | "program" | "action";\n'
            '  reason: string;\n'
            '  example: string | null;\n'
            '  confirm: string | null;\n'
            '}\n'
            f'export const POLICY_VERSION = {VERSION};\n'
            f'export const POLICY: readonly PolicyEntry[] = [\n{data}];\n')


def as_markdown() -> str:
    lines = ['| Operation | Tier | Why | `--confirm` |', '| --- | --- | --- | --- |']
    for row in operations():
        name = f'`{row["operation"]}`' if row['kind'] != 'action' else row['operation']
        lines.append(f'| {name} | {row["tier"]} | {row["reason"]} | {row["confirm"] or ""} |')
    return '\n'.join(lines) + '\n'


def as_guard() -> str:
    lines = ['| Tier | Agent bash command | What happens |', '| --- | --- | --- |']
    happens = {'A': 'Runs',
               'B': 'Runs after the user confirms it in a dialog (see [The dialog](#the-dialog)), unless '
                    '`[tooling].agent_destructive` says `deny` or `allow`; so do changes to the setting files '
                    '(see [The setting files](#the-setting-files)), which `allow` never skips',
               'C': 'Blocked; only the user runs it (`odoo-bin`, `dropdb` and `psql` only in Odoo projects)'}
    for key in TIERS:
        names = ', '.join(f'`{row["operation"]}`' for row in operations()
                          if row['tier'] == key and row['kind'] != 'action')
        lines.append(f'| {key} ({HARNESS[key]}) | {names} | {happens[key]} |')
    return '\n'.join(lines) + '\n'


def main(argv: list[str]) -> int:
    outputs = {'--json': as_json, '--typescript': as_typescript, '--markdown': as_markdown, '--guard': as_guard}
    # Through the entry point (`oasis policy`) the agent contract is its JSON; the other outputs are
    # this repository's generators.
    entrypoint = os.environ.get('OASIS_ENTRYPOINT') or os.environ.get('ODOO19_ENTRYPOINT')
    usage = f'Usage: {entrypoint} policy --json' if entrypoint else \
        'Usage: policy.py --json | --typescript | --markdown | --guard'
    if argv in (['--help'], ['-h']):
        print(usage)
        print('Prints the oasis agent policy as JSON: every operation, its tier (A: the agent alone; '
              'B: the agent proposes, a person confirms; C: a person only), its kind, reason and an example.')
        return 0
    if len(argv) != 1 or argv[0] not in outputs:
        print(usage, file=sys.stderr)
        return 2
    sys.stdout.write(outputs[argv[0]]())
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
