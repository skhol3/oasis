# Documentation: setting up a new workspace

A step-by-step guide to start a project with `oasis-workspace.toml`, and the workspace
reference completed. Documentation only, plus tests that pin the behaviour the guide states.

## Specs

- S1. User (2026-11-24), asking where the docs explain how to build the workspace: "en la
  documentacion en que parte te dice como armar el workspace para oasis?"; then "aparte"
  (separate version); "el environmet no se declara tambien en el oasis-workspace?"; "se puede
  declarar la ruta abosoluta?"; "tambien para la documentacion convendria ademas un ejemple del
  directorio"; "si" (start it).
- S2. docs/new-workspace.md: the steps from an empty folder to a working checkout: folders, Odoo
  source (and optional Enterprise), Python environment, compose file, environment file and
  odoo.conf (path-free), the oasis-workspace.toml, `oasis doctor` until every check passes, a
  development database, a first test run, and adding a linked worktree. Every command is a real
  oasis command with its real options.
- S3. A full example directory tree of a realistic workspace (source, environments, project with
  checkouts and a linked worktree, config, data, logs per checkout), each folder annotated, next
  to the matching oasis-workspace.toml where each key points at its folder.
- S4. Paths: relative paths resolve from the workspace file's directory (addons_paths from each
  checkout); absolute paths are accepted; the Python environment must be inside the checkout or
  under a directory whose name ends in `environments`, and may not be or contain the Odoo source
  (`Unsafe tooling environment target.`). Examples of accepted and refused values.
  Both the single `[tooling].environment` and `[environments.<name>]` with
  `oasis-checkout.toml` are shown.
- S5. docs/project-setup.md leads with the workspace file and keeps the legacy
  `.odoo19-agent.toml` profile as the alternative; README's five-minute start and docs/README.md
  link to the guide.
- S6. Every behaviour the guide states (absolute paths, the environment rule, named environment
  selection) is pinned by a test; add tests where none exist.

## Tasks

- T1 [S2-S6] Guide, reference updates and tests — worker — commit: pending
- T2 Publish — inline — commit: pending

## Log

- L1. Model: corpus-cafe (memory oasis/corpus-cafe-shared-layout): projects/<name>/{codigo/<main>,
  codigo/<main>-<feature>, config/{.env, odoo.conf, compose.yml, requirements/}, data/, logs/},
  source and environments under the series folder ~/Work/odoo/19.0/. Never copy real values,
  names or credentials into the docs; use a fictional project (acme).
- L2. Worker mwuv6uid-6-4uy1 found that tools/config.py accepts an environment inside the Odoo
  source (for example <source>/environments/acme). S4's "or sit inside" was the parent's wording,
  not the user's and not the code: S4 narrowed to the code's rule (option B), no behaviour change.
  Also found, outside scope: bootstrap --apply writes $PROJECT_ROOT/dev/runtime (fails in a workspace
  checkout) and always creates a 3.12 venv; check-environment expects Python 3.12 even for a named
  3.13 environment. The guide creates the environment with uv instead.
