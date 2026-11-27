---
name: odoo-security
description: "Trigger: Odoo ACL, record rule, sudo, authentication, controller, company isolation. Protect permission boundaries."
license: Apache-2.0
metadata:
  author: openalliance
  version: "1.0"
---

## Activation Contract

Use when Odoo work touches access control, authentication, controllers, `sudo()`, company isolation, or sensitive records. Not for model logic without a permission change (`odoo-backend`) or for choosing the test layer (`odoo-testing`). Project-specific security restrictions still apply.

Common to every series: run `oasis doctor` and open `references/<series>/` for its `series=`, else `odoo_release=`.

## Hard Rules

- Inspect relevant access CSV, groups, implied groups, rules, controller routes, and privilege escalations before changing behavior.
- Test representative non-admin users for both allowed and denied paths; administrator success is insufficient.
- Preserve least privilege, ownership, active-company and allowed-company boundaries.
- Never weaken a rule to make a test pass. Minimize `sudo()` and prove its privilege boundary.
- Use the group fields, access-check methods and JSON route type of the checkout's series, as its recipes write them; a name from another series fails at install or silently checks nothing.
- Do not connect to production or disclose credentials, tokens, private data, or database contents.

## Decision Gates

| Situation | Action |
| --- | --- |
| New model or new group | State ACL intent explicitly, including intentionally denied access; follow `references/<series>/access.md` |
| Some records only, or cross-company access | Cover permitted and forbidden records and companies; follow `references/<series>/record-rules.md` |
| Public route | Verify authentication, CSRF, input, ownership, and response exposure |
| Security data change | Require focused tests and applicable fresh install/update evidence |

## Execution Steps

1. Map operations to users, groups, models, and company context; `oasis --project <root> model-info <model>` (Gentle Shell: `oasis_model_info`) lists a model's fields and extensions without opening source.
2. Add focused positive and negative public-behavior tests when deterministic.
3. Implement the narrowest change; verify with authorized project tooling only.

## Output Contract

Report permission matrix, changed files, positive/negative evidence, skipped checks, and residual exposure.

## References

- Recipes in `references/<series>/`: `access.md` (`ir.model.access.csv`, groups, implied groups, manifest order) and `record-rules.md` (`ir.rule`, global and group rules, multi-company rules, `sudo()`, access checks, controller routes).
- [Project capability contract](../odoo-environment/references/project-contract.md).
