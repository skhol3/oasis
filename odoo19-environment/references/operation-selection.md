# Operation selection rules

The full rules behind the decision gates of the `odoo19-environment` skill.

- Separate requested outcomes: resource creation, module install/update, demo data, accounts/credentials, and server startup; none implies another.
- Consult current installed help and applicable declarative profiles before selecting an operation. Prefer supported end-to-end capabilities over ad-hoc substitutes; configuration alone does not prove execution.
- Respect target/namespace, new/existing-resource, and human-interaction preconditions. Never delete or replace resources to satisfy them without explicit authorization. If unsupported, explain the gap before proposing alternatives.
- Before module lifecycle work, confirm Odoo 19 using matching `release.py` and permitted runtime checks; report unavailable evidence.
- Missing project wrapper is not a blocker when the installed global `~/.agents/skills/odoo19/oasis` entry point (`odoo19` beside it is an alias), its tools, an authorized explicit project root, and a project-local profile are available. If neither guarded interface is available, report unavailable; never guess substitutes. A template does not install capabilities.
- Environment mutation: preview first, then seek explicit authorization for the exact isolated target and operation.
