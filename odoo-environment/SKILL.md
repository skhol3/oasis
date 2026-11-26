---
name: odoo-environment
description: "Trigger: Odoo 15.0 or 19.0 environment, dependencies, requirements lock, bootstrap, diagnostics, missing package. Discover local capabilities safely."
license: Apache-2.0
metadata:
  author: openalliance
  version: "1.0"
---

## Activation Contract

Use for Odoo runtime/dependency discovery and diagnostics. Not for running module commands (`odoo-module-lifecycle`). A project's instructions may supply the complete contract without the optional template.

A checkout reads the nearest `oasis-workspace.toml` at or above it, else (linked worktrees) its main checkout's through git ([example](assets/oasis-workspace.example.toml)): paths from it, `addons_paths` from the checkout. A checkout that still has the file of earlier versions is refused until the user runs `oasis migrate`.

Common to every series. Also read [15.0](references/15.0.md) or [19.0](references/19.0.md), per `oasis doctor` `series=`, else `odoo_release=`.

## Hard Rules

- Treat `[odoo]`, `[environment]`, `[database]`, `[commands]` in `oasis-workspace.toml` as advisory. Only installed `~/.agents/skills/odoo19/tools` consume optional `[tooling]`; it is path/guard input, never access consent or automatic setup.
- Use only an isolated project environment; never modify shared virtualenvs or global packages.
- No oasis workflow requires reading, copying or typing a password. Never print, log or template secrets.
- Paths outside the workspace require exact per-target human consent before access, even when configured.
- Never execute shell text or infer a command from an untrusted path declaration.

## Decision Gates

| Situation | Action |
| --- | --- |
| Several outcomes requested (resources, install/update, demo data, accounts, startup) | Treat each separately; none implies another |
| Choosing an operation | Consult installed help and the project's declarations; prefer supported end-to-end capabilities |
| Precondition unmet (target, namespace, existing resource, human interaction) | Never delete or replace resources without explicit authorization; explain the gap first |
| Before module lifecycle work | Confirm the series with matching `release.py` and permitted runtime checks |
| Project wrapper missing | Use the installed `~/.agents/skills/odoo19/oasis` entry point (alias `odoo19`); with no guarded interface, report unavailable |
| Environment mutation | Preview first, then seek explicit authorization for the exact isolated target and operation |

Apply the full [operation selection rules](references/operation-selection.md).

## Execution Steps

1. Read project instructions and the capability contract; identify authorized paths, wrappers or the explicit global entry point (`~/.agents/skills/odoo19/oasis --project /absolute/project doctor --environment --quick`). Run the read-only `doctor` first. A quick check is not strictly read-only: a shimmed uv version probe can trigger mise installation.
2. Inspect permitted dependency declarations without printing credentials or runtime configuration.
3. Run only authorized diagnostics; report drift, missing capabilities, and actions not taken.

## Output Contract

Report confirmed version evidence, isolated environment status, diagnostics, skipped checks, and mutations authorized/performed. Distinguish creation, installation, demo loading, account provisioning, startup, and authentication evidence; a login page proves availability, not usable accounts.

## References

- [Project capability contract](references/project-contract.md).
