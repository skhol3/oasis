---
name: odoo-testing
description: "Trigger: Odoo 15.0 or 19.0 regression, module tests, fresh install, update, TransactionCase, HttpCase, tour. Verify observable behavior."
license: Apache-2.0
metadata:
  author: openalliance
  version: "1.0"
---

## Activation Contract

Use for Odoo test design, bug reproduction, module install/update verification, and test-layer choice. Not for lifecycle commands outside verification (`odoo-module-lifecycle`). Project-specific validation requirements remain authoritative.

Common to every series. Also read [15.0](references/15.0.md) or [19.0](references/19.0.md), per `oasis doctor` `series=`, else `odoo_release=`.

## Hard Rules

- Assert public behavior, permissions, effects, errors, counters, and side effects relevant to each rule; include rejection paths where specified.
- Keep data deterministic and isolated; never test against production or a shared database.
- Follow existing `tests/__init__.py` imports and the module's conventions.
- Do not treat XML parsing, import success, or a current-code update as proof of historical migration.
- Never assume a wrapper accepts test selectors it does not document.
- Default runs use a disposable database. Reuse `[tooling].test_database` or explicit targets sequentially, with exact-target reset authorization; configuration is not consent. See [test targets](references/test-targets.md).
- Prefer `test-module --compact` or `verify-module --compact` (Gentle Shell: `oasis_test_module`): report exits, the `log:` control line and log paths; inspect relevant failures.
- For Python/manifest changes, use the authorized standalone `lint-module` command with the project's trusted rcfile and targets; follow the [Pylint guidance](references/pylint-odoo-guidance.md). Do not run it per edit or treat lint as functional proof.
- Read and apply the [verification evidence policy](references/evidence-policy.md) before reusing a passing phase or claiming evidence for the current candidate.
- For SonarQube findings, check active rules and parameters, assess applicability to the series, and compare analysis before and after correction under that policy. Static analysis never replaces functional verification.

## Decision Gates

| Situation | Action |
| --- | --- |
| Meaningful behavior change | Capture a failing test first when a deterministic runner exists; passive documentation has no meaningful RED |
| Test layer | Model logic: focused Odoo test base; HTTP or UI flow: appropriate HTTP or browser layer |
| Manifest, model, security, data or view change | Fresh install when the project requires it |
| Stored fields, XML, data, security or migrations | Separate update check |
| Missing runner | Mark unavailable; never substitute unguarded database commands |

## Execution Steps

1. Identify existing test conventions, database policy, and authorized project commands.
2. Add narrow tests, reproduce failure when applicable, then verify fix.
3. Preserve separate install, update, test, and manual UI evidence; rerun affected phases after relevant changes.

## Output Contract

Report test files, exact commands and exit codes, named database if used, RED/GREEN evidence, skipped phases, and coverage gaps.

## References

- [Project capability contract](../odoo-environment/references/project-contract.md).
- [Compact Python review criteria](references/sonarqube-python-guidance.md).
