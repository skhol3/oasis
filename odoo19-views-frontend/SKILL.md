---
name: odoo19-views-frontend
description: "Trigger: Odoo 19 XML view, XPath, QWeb, Owl, JavaScript, asset, registry, service. Validate frontend changes."
license: Apache-2.0
metadata:
  author: openalliance
  version: "1.0"
---

## Activation Contract

Use for Odoo 19 views, actions, menus, templates, reports, Owl components, and asset bundles. Not for Python model logic (`odoo19-backend`) or groups and record rules (`odoo19-security`). Obey project-specific boundaries first.

## Hard Rules

- Locate every referenced field and XML ID in the matching Odoo 19 implementation; never invent IDs.
- Inspect the parent architecture before inherited XPath changes.
- Preserve manifest ordering, asset bundle registration, groups, visibility, translations, and accessibility.
- Check JavaScript, Owl templates, services, registries, and assets as one behavior unit.
- XML parsing alone cannot prove inherited views work; use actual installation/update when available and authorized.
- While writing code, apply concise validated project/Odoo criteria; do not query SonarQube per edit. At verification, follow the [bounded SonarQube workflow](../odoo19-testing/references/evidence-policy.md); static analysis does not replace functional checks.

## Decision Gates

| Situation | Action |
| --- | --- |
| Inherited view | Confirm the XPath target against the Odoo 19 parent |
| New asset | Verify bundle membership and loading |
| Service or state change | Trace registry dependencies and affected flows |
| Report or template change | Render affected output when feasible |

## Execution Steps

1. Search exact IDs, field names, templates, and asset keys in permitted source; confirm field names with `oasis --project <root> model-info <model> --field <name>` (Gentle Shell: `oasis_model_info`).
2. Make the smallest coherent change and add applicable behavior-level checks.
3. Verify module installation/update and affected UI using authorized project tooling; report unavailable checks.

## Output Contract

Report changed files, verified parent IDs, installation/update and UI evidence, skipped checks, and compatibility risks.

## References

- [Project capability contract](../odoo19-environment/references/project-contract.md).
- [Verification evidence policy](../odoo19-testing/references/evidence-policy.md).
