# Compact Python Review Criteria

Use this reusable summary while writing Odoo Python, without querying SonarQube for each edit. These are review prompts, not framework-specific exemptions, an exhaustive catalog, or a fixed quality profile. Activation and thresholds depend on the effective server/profile; follow the [evidence policy](evidence-policy.md) when verifying findings.

| Rule | Preventive criterion | Odoo review precaution |
| --- | --- | --- |
| `python:S1192` | Consider meaningful constants for repeated string literals. | Preserve model/XML identifiers and translation extraction. Do not mechanically replace literals passed to translation helpers. Confirm the effective duplication threshold before claiming compliance. |
| `python:S3776` | Reduce unnecessary nesting; extract cohesive responsibilities when this improves understanding. | Preserve recordset behavior, access checks, transaction boundaries, and side effects. Do not split methods merely to move complexity elsewhere. Confirm the effective complexity threshold. |
| `python:S1515` | Avoid accidental late binding of loop variables in nested functions/lambdas; capture a value explicitly when required. | Inspect when ORM callbacks actually execute. A warning alone does not prove the current callback is deferred or already produces incorrect results. |
| `python:S3358` | Prefer clear statements over nested conditional expressions. | Preserve branch precedence, fallback values, and short-circuit behavior. The rule documents an exception for conditional expressions in comprehensions. |
| `python:S1854` | Remove local assignments whose values are unused. | Preserve required right-hand-side effects: removing an assignment must not silently remove a write, validation, access check, or other necessary call. |
| `python:S3516` | Inspect multiple return paths that always return the same value. | Check inherited ORM/public return contracts and caller expectations before changing returns. A framework-required result is not automatically a bug. |
| `python:S6890` | Prefer standard-library `zoneinfo` over `pytz` for new standalone Python 3.9+ timezone code when compatible. | Do not mechanically replace Odoo timezone objects or `localize`/`normalize` usage. Verify the APIs of the checkout's Odoo series, conversions, ambiguous/nonexistent local times, and relevant date-boundary behavior before migration. |

## Use and freshness

- The rule descriptions were retrieved from a live SonarQube server on 2026-11-06. This reference contains no server address, credentials, profile binding, or globally enforced thresholds.
- Keep profile identity, activation evidence, effective parameters, retrieval date, and candidate-specific results in the authorized local evidence context. No project is created by this reference.
- Reuse this short summary during implementation. At verification, validate applicable configuration and analyze affected files under the existing workflow; refresh only relevant entries when rule semantics or configuration changes or freshness is uncertain.
- These precautions require case-by-case evaluation; they do not assert that an existing warning is a false positive or that Odoo requires the flagged pattern. Functional tests and actual post-change analysis remain separate proof.
