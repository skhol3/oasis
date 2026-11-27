---
name: odoo-backend
description: "Trigger: Odoo model, ORM, field, compute, constraint, create, write, cron, controller, backend. Implement batch-safe server behavior."
license: Apache-2.0
metadata:
  author: openalliance
  version: "1.0"
---

## Activation Contract

Use for Odoo Python backend changes: modules, models, fields, computes, constraints, `create`/`write`, inheritance, crons, controllers. Not for ACL or record rules (`odoo-security`), views or assets (`odoo-views-frontend`), or test design (`odoo-testing`). Follow the project's own instructions and permissions; this skill does not authorize file or environment access.

Common to every series: run `oasis doctor` and open `references/<series>/` for its `series=`, else `odoo_release=`.

## Hard Rules

- Inspect the manifest, dependencies, inherited models, security and nearby tests before editing.
- Confirm uncertain APIs against the Odoo source of the checkout's series only when permitted; keep upstream read-only; never copy an API from another series.
- Preserve recordset cardinality and batch behavior in `create`, `write`, computes and jobs.
- Declare accurate `@api.depends`; weigh stored recomputation cost.
- Enforce invariants server-side, never with `onchange` alone. Prefer ORM; justify raw SQL with parameterization and cache/flush handling.
- Minimize and justify `sudo()`; respect permissions, company context, transactions and side effects.
- Take controller route types and access checks from the series' `module.md` and `model.md`.
- While writing code, apply validated project/Odoo criteria; do not query SonarQube per edit. At verification, follow the [bounded SonarQube workflow](../odoo-testing/references/evidence-policy.md); static analysis does not replace functional checks.

## Decision Gates

| Situation | Action |
| --- | --- |
| New module, manifest, `__init__`, hook or controller | `references/<series>/module.md` |
| New model, fields, display name, access check | `references/<series>/model.md` |
| Compute, constraint, index, `create`/`write` override | `references/<series>/compute-constraint.md` |
| `_inherit`, `_inherits` or a mixin | `references/<series>/inheritance.md` |
| Behavior change with a deterministic test | Observe the failure first, then verify the fix |
| Stored field added or changed | Plan a fresh installation and a separate module update |
| Cron or external call | Address idempotency, timeout, failure visibility and retries |
| Only a functional module name is known | Gentle Shell: `oasis_find_module`; otherwise search manifests in scope |

## Execution Steps

1. Trace callers, exact field names and tests in scope. Before opening Odoo source to learn a model, run `oasis --project <root> model-info <model>` (Gentle Shell: `oasis_model_info`); add `--field`, `--module` or `--methods`.
2. Implement the smallest Odoo-native change following the gate's recipe in the checkout's series form.
3. Run supported focused tests and applicable install/update checks; do not invent a runner.

## Output Contract

Report changed files, database and command evidence when used, skipped checks, and security or recomputation risks.

## References

- Recipes in `references/<series>/`: `module.md`, `model.md`, `compute-constraint.md`, `inheritance.md`.
- [Project capability contract](../odoo-environment/references/project-contract.md).
- [Verification evidence policy](../odoo-testing/references/evidence-policy.md).
