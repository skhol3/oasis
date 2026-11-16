# Verification Evidence Policy

Use these rules when recording or reusing Odoo 19 module verification evidence. They guide evidence claims; they do not automatically enforce command execution or authorize database operations.

- Keep one concise evidence entry in the existing task log or delivery report: module, candidate identity (commit plus relevant uncommitted changes), command, database and baseline, phase, exit code, and log location. Do not create another tracking document solely for this entry.
- Reuse a passing phase only while its relevant source, tests, manifest, XML, security, data, dependencies/runtime, and database baseline remain unchanged. A matching HEAD alone is insufficient when there are uncommitted changes. If validity is uncertain, do not claim the old result covers the current candidate.
- Re-run the affected checks after relevant changes; old evidence is historical, not a new execution. Do not repeat all phases automatically for an unrelated change.
- `verify-module` already runs module tests, a separate fresh install, and a current-code update. Preserve each phase's result; do not repeat a successful phase through an individual command for the same unchanged candidate and baseline. Failed or skipped phases remain open.
- Fresh installation and update are distinct proof. An update over a current-code fresh install does not prove migration from an older revision; prepare that baseline when historical migration coverage is required.
- Retain full logs, but report commands, phase results, test counts, and relevant error excerpts instead of loading successful logs in full. Read more only to investigate a concrete gap.

## Pylint evidence

Use the [project-selected Pylint guidance](pylint-odoo-guidance.md) for the standalone `lint-module` command. Obtain a relevant baseline before changes, run after a Python/manifest work unit before expensive functional checks, and reuse only unchanged-candidate/configuration/runtime evidence. Preserve raw diagnostics and status; distinguish prior findings from new ones. Do not run per edit, silently change rules or combine lint with SonarQube or functional results as one undifferentiated pass. `verify-module` is unchanged and does not implicitly run lint.

## SonarQube evidence

### Token-efficient workflow

- During Python implementation, use the [compact Python review criteria](sonarqube-python-guidance.md), validated Odoo/project conventions, and any relevant current rule summary. Do not call the MCP for every edit, file switch, or planning step. The compact reference covers seven rules, not the complete active catalog or proof of framework applicability.
- At verification of code changes where SonarQube analysis is applicable and authorized, analyze only affected supported files, in bounded batches if the available tool supports them. For a warning correction, obtain the baseline before editing and reanalyze affected files afterward. Reuse analysis only for the same unchanged candidate, scope, and configuration; do not rerun merely to repeat a report.
- Resolve the effective profile once per relevant context; retain a concise summary of relevant rule keys, parameters, applicability rationale, profile identity, and retrieval date. Reuse it while configuration is known unchanged. Refresh affected entries when the server/profile binding, active rules, parameters, analyzer version, or language/scope changes, or freshness is uncertain. Do not fetch the entire catalog each task; fetch detailed explanations only for new, unknown, or changed rules, or to resolve a concrete discrepancy.
- Prefer file-path input when an existing authorized integration supports it. Otherwise submit only required complete files faithfully, not the whole repository; never truncate content merely to save tokens. Keep full findings available and return compact rule/location/message summaries, expanding only findings being investigated. Never hide errors, new findings, or unavailable checks to reduce output.
- This is agent workflow guidance, not an automatic file watcher or new CLI hook. Missing MCP access is an explicit analysis gap, not a reason to install tools, reconnect an IDE, or silently substitute a clean result.

### Before correction

- When SonarQube is relevant, use the existing authorized integration to identify the effective quality profile, active rules, and rule parameters for the affected language and scope. Without a project binding, identify the server's default profile rather than assuming IDE parity or inventing a project. Generic rule documentation alone does not establish active configuration. If configuration evidence is unavailable, report the gap; never request credentials in chat.
- Preserve the candidate identity, analysis scope and tool/version when available, rule key, affected location, effective parameters, and relevant finding evidence. Verify that submitted content faithfully represents the intended file. A successful response with zero findings is not proof that all expected rules ran; investigate discrepancies against known findings before claiming equivalence.
- Inspect the surrounding implementation and assess the rule against Odoo 19 behavior and project conventions before editing. Consult matching Odoo 19 sources only with permission when framework behavior is uncertain. A finding is evidence to investigate, not authority to replace framework-required patterns or mechanically satisfy a metric.

### After correction

- Analyze the changed candidate with comparable scope and configuration. Report the targeted finding's resulting status and relevant new findings. Explain scope or configuration differences; old analysis and pending background work do not prove the correction passed. If analysis is unavailable, report the correction as unverified by SonarQube.
- Keep static analysis separate from functional evidence. Run focused behavior, permission, and side-effect tests and applicable installation/update checks required by the change. A clean analysis or passing quality gate does not establish functional correctness.
- Record concise before/after evidence and applicability rationale in the existing task log or delivery report. Document justified non-applicability; never silently suppress findings or change rule parameters, profiles, or quality gates without separate authorization.

### Scope and portability

- This policy grants no permission to access a server, submit source, or run analysis. Discover actual tool capabilities; do not assume the MCP requires an IDE or exposes an installed analyzer. Keep server URLs, credentials, MCP configuration, and fixed server profiles out of the global bundle. Use authorized project-local configuration; do not install or reconfigure integrations implicitly.
- Consult only relevant rules and parameters rather than loading the complete catalog into context. If retaining a rule snapshot locally, record its profile, scope, and retrieval date, omit credentials, and revalidate it when configuration changes; it is not a universal Odoo standard.
