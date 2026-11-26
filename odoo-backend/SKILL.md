---
name: odoo-backend
description: "Trigger: Odoo 15.0 or 19.0 model, ORM, field, compute, constraint, create, write, cron, controller, backend. Implement batch-safe server behavior."
license: Apache-2.0
metadata:
  author: openalliance
  version: "1.0"
---

## Activation Contract

Use for Odoo Python backend changes: models, fields, computes, constraints, `create`/`write`, crons, controllers. Not for ACL or record rules (`odoo-security`), views or assets (`odoo-views-frontend`), or test design (`odoo-testing`). Follow the project's own instructions and permissions; this skill does not authorize file or environment access.

Common to every series. Also read [15.0](references/15.0.md) or [19.0](references/19.0.md), per `oasis doctor` `series=`, else `odoo_release=`.

## Hard Rules

- Inspect the module manifest, dependencies, inherited models, security, and nearby tests before editing.
- Confirm uncertain APIs against the Odoo source of the checkout's series only when access is permitted. Keep upstream read-only. Never copy an API from another series.
- Preserve expected recordset cardinality and batch behavior in `create`, `write`, computes, and jobs.
- Declare accurate `@api.depends` inputs; consider stored recomputation cost.
- Enforce invariants server-side, never with `onchange` alone. Prefer ORM; justify raw SQL with parameterization and cache/flush handling.
- Minimize and justify `sudo()`; respect permissions, company context, transactions, and side effects.
- While writing code, apply concise validated project/Odoo criteria; do not query SonarQube per edit. At verification, follow the [bounded SonarQube workflow](../odoo-testing/references/evidence-policy.md); static analysis does not replace functional checks.

## Decision Gates

| Situation | Action |
| --- | --- |
| Behavior change with a meaningful deterministic test | Observe the failure first, then verify the fix |
| Stored field added or changed | Plan a fresh installation and a separate module update with authorized local tooling |
| Cron or external call | Address idempotency, timeout, failure visibility, and retries |
| Only a functional module name is known | In Gentle Shell use `oasis_find_module`; otherwise search manifests in the permitted scope |

## Execution Steps

1. Trace relevant callers, exact field names, and existing tests in the permitted scope. Before opening Odoo source to learn a model, run `oasis --project <root> model-info <model>` (Gentle Shell: `oasis_model_info`); add `--field`, `--module` or `--methods` for detail.
2. Implement the smallest Odoo-native change consistent with project conventions and the series reference.
3. Run supported focused tests and applicable installation/update checks; do not invent a runner.

## Output Contract

Report changed files, database and command evidence when used, skipped checks, and security or recomputation risks.

## References

- [Odoo 15.0 differences](references/15.0.md) and [Odoo 19.0 differences](references/19.0.md).
- [Project capability contract](../odoo-environment/references/project-contract.md).
- [Verification evidence policy](../odoo-testing/references/evidence-policy.md).
