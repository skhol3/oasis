# Test targets and compact runs

- Default: `test-module` and `verify-module` without an explicit or configured database create a disposable database for the run and drop it afterwards, also after a failure or an interruption. `gc` lists leftovers; only the user runs `gc --apply`.
- Reused targets: `[tooling].test_database` or an explicit database is reset and reused. Run such targets sequentially, with exact-target reset authorization. Preserve development data and failed-run evidence; active-session checks are not locks. Configuration is not consent.
- Names: with a checkout slug, test targets are `<test_prefix><slug>_<name>`. Names ending in `_r` plus six hex digits are reserved for disposable runs.
- Verification uses a separate `_update` target, not a historical migration baseline.
- One class or method: `test-module --only <Class[.method]>` (Gentle Shell: `only` of `oasis_test_module`) while fixing a single test; run the whole module before reporting.
- Compact runs: `test-module --compact` and `verify-module --compact` print each phase, its exit code and the log paths. Full streams remain in the logs directory: `[tooling].logs` when set, otherwise the project's `dev/logs/odoo19/`.
- In Gentle Shell, `oasis_test_module` returns the result line, failures and grouped warnings, and ends with `log: <lines> lines, <errors> errors, <warnings> warnings`, counted over the full logs. Open the logs only when the summary is not enough.
