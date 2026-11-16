---
name: odoo19-environment
description: "Trigger: Odoo 19 environment, dependencies, requirements lock, bootstrap, diagnostics, missing package. Discover local capabilities safely."
license: Apache-2.0
metadata:
  author: openalliance
  version: "1.0"
---

## Activation Contract

Use for Odoo 19 runtime/dependency discovery and diagnostics. A project's instructions may supply the complete contract without the optional template.

## Hard Rules

- Treat `[odoo]`, `[environment]`, `[database]`, `[commands]` in `.odoo19-agent.toml` as advisory. Only installed `~/.agents/skills/odoo19/tools` consume optional `[tooling]`; it is path/guard input, never access consent or automatic setup.
- Use only an isolated project environment; never modify shared virtualenvs or global packages.
- Do not read or log runtime configuration contents if they may contain secrets. Never place secrets in the template.
- Paths outside the workspace require exact per-target human consent before access, even if declared in configuration.
- Never execute shell text or infer a command from an untrusted path declaration.

## Decision Gates

- Separate requested outcomes: resource creation, module install/update, demo data, accounts/credentials, and server startup; none implies another.
- Consult current installed help and applicable declarative profiles before selecting an operation. Prefer supported end-to-end capabilities over ad-hoc substitutes; configuration alone does not prove execution.
- Respect target/namespace, new/existing-resource, and human-interaction preconditions. Never delete or replace resources to satisfy them without explicit authorization. If unsupported, explain the gap before proposing alternatives.
- Before module lifecycle work, confirm Odoo 19 using matching `release.py` and permitted runtime checks; report unavailable evidence.
- Missing project wrapper is not a blocker when the installed global `~/.agents/skills/odoo19/odoo19` entry point, its tools, an authorized explicit project root, and a project-local profile are available. If neither guarded interface is available, report unavailable; never guess substitutes. A template does not install capabilities.
- Environment mutation: preview first, then seek explicit authorization for the exact isolated target and operation.

## Execution Steps

1. Read project instructions and the capability contract; identify authorized paths and wrappers or the explicit global entry point (`~/.agents/skills/odoo19/odoo19 --project /absolute/project check-environment --quick`). Do not assume a quick check is strictly read-only: a shimmed uv version probe can trigger mise installation.
2. Inspect permitted dependency declarations without printing credentials or runtime configuration.
3. Run only authorized diagnostics; report drift, missing capabilities, and actions not taken.

## Output Contract

Report confirmed version evidence, isolated environment status, diagnostics, skipped checks, and mutations authorized/performed. Distinguish creation, installation, demo loading, account provisioning, startup, and authentication evidence; a login page proves availability, not usable accounts.

## References

- [Project capability contract](references/project-contract.md).
- [Optional example](assets/odoo19-agent.example.toml).
