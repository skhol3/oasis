# Changelog

All notable changes to oasis are recorded here. The format follows Keep a Changelog
(`keepachangelog.com`) and versions follow Semantic Versioning (`semver.org`).

While the version is `0.x`, the contract (the `odoo19` command names and options, the
`.odoo19-agent.toml` `[tooling]` keys, the database prefix guards and the skill names) may
still change in a minor release; every such change is listed here under **Changed**.

## [Unreleased]

## [0.1.0] - 2026-11-16

First tagged release: one project checkout per Odoo project.

### Added

- Agent-agnostic core: the `odoo19` entry point, guarded `tools/`, the six `odoo19-*` skills,
  project wrapper templates and docs.
- `install.sh` installs the committed HEAD into `~/.agents/skills/odoo19`, keeps the previous
  install as a backup and records the installed commit and version in `.oasis-install.json`.
- `odoo19 model-info <model>`: static summary of an Odoo model (definition, extensions,
  fields, overrides, methods) from the Odoo source and the project addons, without starting
  Odoo or touching a database.
- Gentle Shell layer (Pi package): project detection with a compact prompt section, the tools
  `odoo19_test_module`, `odoo19_module_status`, `odoo19_check_environment`,
  `odoo19_lint_module`, `odoo19_find_module` and `odoo19_model_info`, and the `/odoo19`
  status command.
- `odoo19_test_module` returns the result line, stats, failures with traceback tails and
  grouped warnings instead of the full log; full logs stay under `dev/logs/odoo19`.
- In Odoo projects the layer blocks agent bash commands that run `odoo-bin`, `dropdb` or
  `psql` directly and points to the guarded commands.

### Known limitations

- One checkout per project: linked git worktrees share the test database, HTTP port and
  Compose stack of the main checkout. Do not run them at the same time.
- `update-module`, `odoo-shell`, `install-module` without demo and `start -d` accept database
  names outside the managed prefixes.
- The bash guard is a guard rail, not a sandbox: piping into a shell, scripts and `ssh` are
  not detected.

[Unreleased]: https://github.com/skhol3/oasis/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/skhol3/oasis/releases/tag/v0.1.0
