# Run project-selected Odoo lint

Use the standalone global `lint-module` command for Python/manifest changes. It complements SonarQube and functional tests; it does not replace either or run automatically inside `verify-module`.

## Quick path

1. Declare an existing, trusted rcfile in the project's `oasis-workspace.toml`:

   ```toml
   [tooling]
   # Other required project tooling declarations remain unchanged.
   lint_rcfile = 'config/lint/.pylintrc'
   ```

   Paths resolve from the workspace file's directory, not the current working directory or VS Code. Absolute or project-relative external rcfiles are supported only with the required per-target access authorization. This is not permission to read arbitrary files. Keep `pylint_odoo` in the rcfile's `load-plugins`; existing plugin/rule selections remain intact.

2. With authorization for the project, interpreter, rcfile and plugins, run:

   ```bash
   ~/.agents/skills/oasis/oasis --project /absolute/project lint-module your_module
   ```

3. Preserve the exact diagnostics and exit code. A nonzero result is not a clean check, even when the score exceeds the configured threshold. Separate existing baseline findings from new findings; do not suppress, change rules, install dependencies or automatically fix code without authorization.

## Behavior and boundaries

- The selected isolated Python must match the declared Python (`PYTHON_VERSION`: by default 3.12 on Odoo 19.0 and 3.9 on 15.0, or the named environment's `python`). It must already provide Pylint and pylint-odoo; the plugin must advertise support for the workspace's `odoo_version` (19.0 or 15.0). Missing/incompatible prerequisites fail rather than installing or falling back to a global interpreter.
- Only a whole technical module under a configured `[tooling].addons_paths` root inside the selected project is accepted. Traversal, module escape and escaping symlinks are refused. This command accepts no arbitrary Pylint arguments or file lists.
- The command passes the declared Odoo and Python targets and disables Pylint persistence/Python bytecode writes. It does not rewrite the rcfile or override its rules/plugin list. A trusted rcfile and plugins can execute Python hooks: this is not a sandbox or a guarantee that arbitrary plugin code is side-effect-free.
- No Odoo server/configuration, credentials, Docker, database, package installer or SonarQube connection is needed. `lint-module --help` requires only the normal explicit project selection, not lint configuration or an installed analyzer.
- stdout, stderr and the analyzer's exit status pass through unchanged. Setup errors use exit 2 and occur before analyzer execution. Declared paths are inputs, not operational consent.

## When to run

Establish a baseline before changing a relevant module or correcting a warning. Run after a Python/manifest work unit, before expensive Odoo tests, not after every edit. At closeout, reuse a passing lint phase only while the module, rcfile/plugins, target settings and runtime baseline remain unchanged. Record the command, module, versions/configuration identity, exit code and relevant findings in the existing task evidence; a changed rule configuration invalidates comparability.

Use the [SonarQube evidence policy](evidence-policy.md) separately for applicable authorized analysis, and still run required behavior/security/install/update tests. A clean lint result does not prove correctness or Odoo view installation.
