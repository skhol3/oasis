---
name: odoo-testing
description: "Trigger: Odoo regression, module tests, fresh install, update, TransactionCase, HttpCase, tour. Verify observable behavior."
license: Apache-2.0
metadata:
  author: openalliance
  version: "1.0"
---

## Activation Contract

Use for Odoo test design, bug reproduction, install/update verification and test-layer choice. Not for lifecycle commands outside verification (`odoo-module-lifecycle`). Project validation requirements remain authoritative.

Common to every series: run `oasis doctor` and open `references/<series>/` for its `series=`, else `odoo_release=`.

## Hard Rules

- Assert public behavior, permissions, errors, counters and side effects of each rule, rejection paths included.
- Keep data deterministic and isolated; never test against production or a shared database.
- Follow the module's `tests/__init__.py` imports and conventions.
- XML parsing, import success or a current-code update never prove a historical migration.
- Never assume undocumented test selectors work; `--project` takes an absolute path.
- Default runs use a disposable database. Reuse `[tooling].test_database` or explicit targets sequentially, with exact-target reset authorization; configuration is not consent. See [test targets](references/test-targets.md).
- Prefer `test-module --compact` or `verify-module --compact`: report each `phase=... exit=` line, log paths; the test count (`N failed, M error(s) of K tests`) and failures are in the log (Gentle Shell's `oasis_test_module` returns them and a `log:` line).
- For Python/manifest changes, use the authorized standalone `lint-module` command with the project's trusted rcfile; follow the [Pylint guidance](references/pylint-odoo-guidance.md). Without `tooling.lint_rcfile` it exits 2: skip lint and report that. Never lint per edit or treat lint as functional proof.
- Apply the [verification evidence policy](references/evidence-policy.md) before reusing a passing phase or claiming evidence for the current candidate.
- For SonarQube findings, check active rules, their applicability to the series, and the analysis before and after correction under that policy; it never replaces functional verification.

## Decision Gates

| Situation | Action |
| --- | --- |
| Meaningful behavior change | Capture a failing test first when a deterministic runner exists; passive documentation has no meaningful RED |
| Test layer | Model logic: `TransactionCase`, `references/<series>/model-tests.md`; UI flow: `HttpCase` tour, `references/<series>/tours.md` |
| Manifest, model, security, data or view change | Fresh install when the project requires it |
| Stored fields, XML, data, security or migrations | Separate update check |
| Missing runner | Mark unavailable; never substitute unguarded database commands |

## Execution Steps

1. Identify test conventions, database policy and authorized commands.
2. Add narrow tests, reproduce the failure when applicable, verify the fix.
3. Keep install, update, test and manual UI evidence separate; rerun affected phases after changes.

## Output Contract

Report test files, exact commands and exit codes, any named database, RED/GREEN evidence, skipped phases and coverage gaps.

## References

- Recipes in `references/<series>/`: `model-tests.md`, `tours.md`.
- [Project capability contract](../odoo-environment/references/project-contract.md).
- [Compact Python review criteria](references/sonarqube-python-guidance.md).
