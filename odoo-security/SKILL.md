---
name: odoo-security
description: "Trigger: Odoo 15.0 or 19.0 ACL, record rule, sudo, authentication, controller, company isolation. Protect permission boundaries."
license: Apache-2.0
metadata:
  author: openalliance
  version: "1.0"
---

## Activation Contract

Use when Odoo work touches access control, authentication, controllers, `sudo()`, company isolation, or sensitive records. Not for model logic without a permission change (`odoo-backend`) or for choosing the test layer (`odoo-testing`). Project-specific security restrictions still apply.

Common to every series. Also read [15.0](references/15.0.md) or [19.0](references/19.0.md), per `oasis doctor` `series=`, else `odoo_release=`.

## Hard Rules

- Inspect relevant access CSV, groups, implied groups, rules, controller routes, and privilege escalations before changing behavior.
- Test representative non-admin users for both allowed and denied paths; administrator success is insufficient.
- Preserve least privilege, ownership, active-company and allowed-company boundaries.
- Never weaken a rule to make a test pass. Minimize `sudo()` and prove its privilege boundary.
- Use the field and method names of the checkout's series; a name from another series fails at install or silently checks nothing.
- Do not connect to production or disclose credentials, tokens, private data, or database contents.

## Decision Gates

| Situation | Action |
| --- | --- |
| New model | State ACL intent explicitly, including intentionally denied access |
| Cross-company access | Cover permitted and forbidden companies |
| Public route | Verify authentication, CSRF, input, ownership, and response exposure |
| Security data change | Require focused tests and applicable fresh install/update evidence |

## Execution Steps

1. Map operations to users, groups, models, and company context; `oasis --project <root> model-info <model>` (Gentle Shell: `oasis_model_info`) lists a model's fields and extensions without opening source.
2. Add focused positive and negative public-behavior tests when deterministic.
3. Implement the narrowest change; verify with authorized project tooling only.

## Output Contract

Report permission matrix, changed files, positive/negative evidence, skipped checks, and residual exposure.

## References

- [Odoo 15.0 differences](references/15.0.md) and [Odoo 19.0 differences](references/19.0.md).
- [Project capability contract](../odoo-environment/references/project-contract.md).
