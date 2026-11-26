---
name: odoo-views-frontend
description: "Trigger: Odoo 15.0 or 19.0 XML view, XPath, QWeb, Owl, JavaScript, asset, registry, service, tour. Validate frontend changes."
license: Apache-2.0
metadata:
  author: openalliance
  version: "1.0"
---

## Activation Contract

Use for Odoo views, actions, menus, templates, reports, Owl components, and asset bundles. Not for Python model logic (`odoo-backend`) or groups and record rules (`odoo-security`). Obey project-specific boundaries first.

Common to every series. Also read [15.0](references/15.0.md) or [19.0](references/19.0.md), per `oasis doctor` `series=`, else `odoo_release=`.

## Hard Rules

- Locate every referenced field and XML ID in the Odoo implementation of the checkout's series; never invent IDs.
- Inspect the parent architecture before inherited XPath changes.
- Write the view syntax of the checkout's series; never port a view, modifier or widget from another series unchecked.
- Preserve manifest ordering, asset bundle registration, groups, visibility, translations, and accessibility.
- Check JavaScript, Owl templates, services, registries, and assets as one behavior unit.
- XML parsing alone cannot prove inherited views work; use actual installation/update when available and authorized.
- While writing code, apply concise validated project/Odoo criteria; do not query SonarQube per edit. At verification, follow the [bounded SonarQube workflow](../odoo-testing/references/evidence-policy.md); static analysis does not replace functional checks.

## Decision Gates

| Situation | Action |
| --- | --- |
| Inherited view | Confirm the XPath target against the parent of the checkout's series |
| New asset | Verify bundle membership and loading |
| Service or state change | Trace registry dependencies and affected flows |
| Report or template change | Render affected output when feasible |

## Execution Steps

1. Locate views and XML ids with `oasis --project <root> view-info <model>` and `xmlid-info <module>.<name>` (Gentle Shell: `oasis_view_info`, `oasis_xmlid_info`) before searching XML. Search field names, templates, and asset keys in permitted source; confirm field names with `oasis --project <root> model-info <model> --field <name>` (Gentle Shell: `oasis_model_info`).
2. Make the smallest coherent change and add applicable behavior-level checks.
3. Verify module installation/update and affected UI using authorized project tooling; report unavailable checks.

## Output Contract

Report changed files, verified parent IDs, installation/update and UI evidence, skipped checks, and compatibility risks.

## References

- [Odoo 15.0 differences](references/15.0.md) and [Odoo 19.0 differences](references/19.0.md).
- [Project capability contract](../odoo-environment/references/project-contract.md).
- [Verification evidence policy](../odoo-testing/references/evidence-policy.md).
