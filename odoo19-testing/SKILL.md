---
name: odoo19-testing
description: "Trigger: Odoo 19 regression, module tests, fresh install, update, TransactionCase, HttpCase, tour. Verify observable behavior."
license: Apache-2.0
metadata:
  author: openalliance
  version: "1.0"
---

## Activation Contract

Use for Odoo 19 test design, bug reproduction, module install/update verification, and test-layer choice. Project-specific validation requirements remain authoritative.

## Hard Rules

- Assert public behavior, permissions, effects, errors, counters, and side effects relevant to each rule; include rejection paths where specified.
- Keep data deterministic and isolated; never test against production or a shared database.
- Follow existing `tests/__init__.py` imports and the module's conventions.
- Do not treat XML parsing, import success, or a current-code update as proof of historical migration.
- Never assume a wrapper accepts test selectors it does not document.
- Reuse `[tooling].test_database` sequentially; obtain exact-target reset authorization. Preserve development data and failed-run evidence. Separate targets serve parallel jobs or isolated baselines; active-session checks are not locks. Configuration is not consent.
- Prefer `test-module --compact` or `verify-module --compact`: report exits/log paths; inspect relevant failures. Full streams remain under project `dev/logs/odoo19/`. Verification uses a separate `_update` target, not a historical migration baseline.
- For Python/manifest changes, use the authorized standalone `lint-module` command with the project's trusted rcfile and targets; follow the [Pylint guidance](references/pylint-odoo-guidance.md). Do not run it per edit or treat lint as functional proof.
- Read and apply the [verification evidence policy](references/evidence-policy.md) before reusing a passing phase or claiming evidence for the current candidate.
- For SonarQube findings, consult active rules and effective parameters, assess Odoo 19 applicability, and compare analysis before and after correction under that policy. Static analysis never replaces functional verification.

## Decision Gates

- Meaningful behavior change: capture a failing test first when a deterministic runner exists; passive documentation has no meaningful RED.
- Model logic: use focused Odoo test base; HTTP/UI flow: use appropriate HTTP or browser layer.
- Manifest/model/security/data/view changes: fresh install when project requires it; stored fields/XML/data/security/migrations: separate update check.
- Missing runner: mark unavailable; never substitute unguarded database commands.

## Execution Steps

1. Identify existing test conventions, database policy, and authorized project commands.
2. Add narrow tests, reproduce failure when applicable, then verify fix.
3. Preserve separate install, update, test, and manual UI evidence; rerun affected phases after relevant changes. Read and apply the [verification evidence policy](references/evidence-policy.md) before reusing evidence.

## Output Contract

Report test files, exact commands and exit codes, named database if used, RED/GREEN evidence, skipped phases, and coverage gaps.

## References

- [Project capability contract](../odoo19-environment/references/project-contract.md).
- [Verification evidence policy](references/evidence-policy.md).
- [Compact Python review criteria](references/sonarqube-python-guidance.md).
- [Project-selected Pylint execution and cadence](references/pylint-odoo-guidance.md).
