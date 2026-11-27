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

Common to every series: the Changed in table of each recipe says what differs, per `oasis doctor` `series=`, else `odoo_release=`.

## Hard Rules

- Inspect relevant access CSV, groups, implied groups, rules, controller routes, and privilege escalations before changing behavior.
- Test representative non-admin users for both allowed and denied paths; administrator success is insufficient.
- Preserve least privilege, ownership, active-company and allowed-company boundaries.
- Never weaken a rule to make a test pass. Minimize `sudo()` and prove its privilege boundary.
- Use the field and method names of the checkout's series; a name from another series fails at install or silently checks nothing.
- JSON controller routes: `@route(type='jsonrpc')` on 19.0, where `type='json'` is a deprecated alias since 19.0 (`odoo/http.py:812`); `@route(type='json')` on 15.0 (`odoo/http.py:451`).
- Do not connect to production or disclose credentials, tokens, private data, or database contents.

## Decision Gates

| Situation | Action |
| --- | --- |
| New model or new group | State ACL intent explicitly, including intentionally denied access; follow [access](references/access.md) |
| Some records only, or cross-company access | Cover permitted and forbidden records and companies; follow [record rules](references/record-rules.md) |
| Public route | Verify authentication, CSRF, input, ownership, and response exposure |
| Security data change | Require focused tests and applicable fresh install/update evidence |

## Execution Steps

1. Map operations to users, groups, models, and company context; `oasis --project <root> model-info <model>` (Gentle Shell: `oasis_model_info`) lists a model's fields and extensions without opening source.
2. Add focused positive and negative public-behavior tests when deterministic.
3. Implement the narrowest change; verify with authorized project tooling only.

## Output Contract

Report permission matrix, changed files, positive/negative evidence, skipped checks, and residual exposure.

## References

- [Groups and model access](references/access.md): `ir.model.access.csv`, groups, privileges, implied groups, manifest order.
- [Record rules](references/record-rules.md): `ir.rule`, global and group rules, multi-company rules, `sudo()` and access checks.
- [Project capability contract](../odoo-environment/references/project-contract.md).
