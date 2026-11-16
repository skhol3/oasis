---
name: odoo19-module-lifecycle
description: "Trigger: Odoo 19 install module, update module, module status, database lifecycle. Operate guarded local tooling only."
license: Apache-2.0
metadata:
  author: openalliance
  version: "1.0"
---

## Activation Contract

Use for authorized local Odoo 19 module installation, updates, test runs, and state inspection. Never operate on production or unknown databases.

## Hard Rules

- Confirm Odoo 19 with matching `release.py` and permitted runtime evidence before lifecycle commands.
- Require an explicitly named local database; never guess a default or derive authorization from a template prefix.
- Use documented project wrappers and their guards, or the installed `~/.agents/skills/odoo19/odoo19 --project /absolute/project <command>` entry point with its packaged tools and project-local profile. Missing project wrappers alone are not a blocker for an authorized global entry point; if neither guarded interface is available, report unavailable. Never bypass guards with raw SQL or guessed commands.
- Destructive reset requires an exact named disposable test database, a guarded installed interface enforcing the project's namespace, explicit authorization, and an active-session check. Never auto-stop or terminate sessions.
- Treat fresh install, current-code update, historical migration, tests, and UI checks as distinct evidence.

## Decision Gates

- Missing version proof, guard, installed interface, database name, or consent: stop that operation and report unavailable or request focused authorization.
- Metadata/security/data/view changes: check project's fresh-install/update requirements.
- Historical migration: prepare the required older baseline only with separately authorized tooling; current-code update is not equivalent.

## Execution Steps

1. Read project instructions and discover permitted runtime, database, and guarded wrapper or global-entry-point capabilities.
2. Check version, target name, interface guards, and active sessions where destructive work is explicitly authorized.
3. Run only the authorized narrow operation; retain failed databases for inspection unless cleanup is separately approved.

## Output Contract

Report module, exact database, commands and exit codes, phase/baseline evidence, skipped checks, and remaining risks.

## References

- [Project capability contract](../odoo19-environment/references/project-contract.md).
