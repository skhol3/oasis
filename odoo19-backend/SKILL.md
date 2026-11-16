---
name: odoo19-backend
description: "Trigger: Odoo 19 model, ORM, field, compute, constraint, create, write, cron, controller, backend. Implement batch-safe server behavior."
license: Apache-2.0
metadata:
  author: openalliance
  version: "1.0"
---

## Activation Contract

Use for Odoo 19 Python backend changes. Follow the project's own instructions and permissions; this skill does not authorize file or environment access.

## Hard Rules

- While writing code, apply concise validated project/Odoo criteria; do not query SonarQube per edit. At verification, follow the [bounded SonarQube workflow](../odoo19-testing/references/evidence-policy.md); static analysis does not replace functional checks.

- Inspect the module manifest, dependencies, inherited models, security, and nearby tests before editing.
- Confirm uncertain APIs against matching Odoo 19 source only when access is permitted. Keep upstream read-only.
- Preserve expected recordset cardinality and batch behavior in `create`, `write`, computes, and jobs.
- Declare accurate `@api.depends` inputs; consider stored recomputation cost.
- Enforce invariants server-side, never with `onchange` alone. Prefer ORM; justify raw SQL with parameterization and cache/flush handling.
- Minimize and justify `sudo()`; respect permissions, company context, transactions, and side effects.

## Decision Gates

- For behavior changes with meaningful deterministic tests, observe failure first, then verify the fix.
- For stored fields, plan both fresh installation and separate module update using authorized local tooling.
- For cron or external calls, address idempotency, timeout, failure visibility, and retries.

## Execution Steps

1. Trace relevant callers, exact field names, and existing tests in the permitted scope.
2. Implement the smallest Odoo-native change consistent with project conventions.
3. Run supported focused tests and applicable installation/update checks; do not invent a runner.

## Output Contract

Report changed files, database and command evidence when used, skipped checks, and security or recomputation risks.

## References

- [Project capability contract](../odoo19-environment/references/project-contract.md).
- [Verification evidence policy](../odoo19-testing/references/evidence-policy.md).
