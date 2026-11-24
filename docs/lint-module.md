# Lint one module without starting Odoo

Declare an existing trusted Pylint rcfile in the project's `oasis-workspace.toml`:

```toml
[tooling]
# Keep the project's other required tooling values.
lint_rcfile = 'config/lint/.pylintrc'
```

With authorization for the declared paths and installed plugins, run:

```bash
~/.agents/skills/odoo19/oasis --project /absolute/project lint-module your_module
```

The project Python must already provide Pylint and pylint-odoo supporting Odoo 19. The command selects the whole module from project-contained tooling addon roots, preserves rcfile rules/plugins, selects Odoo 19/Python 3.12 and disables bytecode/Pylint persistence. It returns raw analyzer stdout/stderr/status; it never installs dependencies, starts services, uses database credentials or automatically fixes warnings. Trusted rcfile hooks/plugins are not sandboxed. A relative rcfile path resolves from the workspace file's directory, like the other tooling paths; external paths require explicit access consent. Missing lint config does not affect other commands. `lint-module --help` describes this contract; `verify-module` remains separate.

Run at a relevant baseline and after a Python/manifest work unit, not each edit. See [Pylint guidance and evidence reuse](../odoo19-testing/references/pylint-odoo-guidance.md) alongside the independent [SonarQube policy](../odoo19-testing/references/evidence-policy.md). Static analysis never replaces functional Odoo checks.
