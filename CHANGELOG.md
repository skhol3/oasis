# Changelog

All notable changes to oasis are recorded here. The format follows Keep a Changelog
(`keepachangelog.com`) and versions follow Semantic Versioning (`semver.org`).

While the version is `0.x`, the contract (the `odoo19` command names and options, the
`.odoo19-agent.toml` `[tooling]` keys, the database prefix guards and the skill names) may
still change in a minor release; every such change is listed here under **Changed**.

## [Unreleased]

## [0.2.0] - 2026-11-17

Linked git worktrees get their own databases: one checkout no longer steps on another.

### Added

- Checkout identity: `tools/config.py` also emits `CHECKOUT_KIND` (`main`, `linked`, `none`)
  and `CHECKOUT_SLUG`, derived read-only from git; a linked worktree's slug comes from its
  directory name (`corpus-cafe-07.1` -> `07_1`). Optional `[tooling].checkout_slug` overrides
  it. `/odoo19` shows a `checkout:` line.
- `update-module --help` and `odoo-shell --help` describe their database guards.
- Subagent overlay template `pi/agent-overlays/oasis.json`: copied to
  `~/.gentle-shell/gentle-ai/agent-overlays.d/`, it adds the six `odoo19_*` tools to the
  `gentle-ai-worker` and `gentle-ai-verify` subagents (see the README, Subagents).

### Changed

- Per-checkout database names: in a checkout with a slug (a linked worktree, or any checkout
  with `[tooling].checkout_slug`) the slug goes right after the managed prefix in every
  default: `install-module` uses `<dev_prefix><slug>_<module>`, `test-module` and
  `verify-module` use `<test_prefix><slug>_<module>` and its `_update` sibling, and a
  configured `test_database` becomes `<test_prefix><slug>_<rest>` (still at most 56 bytes).
  Database arguments must use that checkout namespace. The main checkout keeps its names.
- `install-module` (with or without `--with-demo`), `update-module`, `odoo-shell` and `start`
  with `-d`/`--database` now require a managed `<dev_prefix>`/`<test_prefix>` database name;
  every database name is limited to 63 bytes, and a `verify-module` test database with an
  `_update` sibling to 56 bytes.
- `update-module` and `odoo-shell` no longer create a missing database: they exit 2 with
  `Database <name> does not exist; create it with install-module or create-database.`

### Fixed

- `test-module --compact` in a linked worktree whose `dev/logs` links to the main checkout:
  `tools/config.py` also emits `CHECKOUT_MAIN_ROOT`, and compact runs in a linked worktree
  accept a log directory inside the main checkout's `dev/logs/odoo19`. Every other location outside the project
  is still refused.
- Browser evidence (`chrome_logs`, screenshots, videos) of `test-module` in a linked worktree
  whose `dev/logs` links to the main checkout is now copied there instead of being refused:
  `tools/common.sh` exports `CHECKOUT_KIND` and `CHECKOUT_MAIN_ROOT` to the evidence helper.

### Known limitations

- A linked worktree needs a link to the main checkout's environment file at the profile's
  `env_file` path, created by the user (agents may not create or read environment files);
  `worktree-init` is planned for 0.3.0.
- `start` without `-d`/`--database` uses the `db_name` and `--db-filter` of the project's
  `odoo.conf`; keep `db_name` out of a linked worktree's `odoo.conf`.
- Slugs are matched as prefixes: a slug that is the start of another (`wt`, `wt_1`) can reach
  the other checkout's databases.
- Checkout detection needs git 2.31 or newer; without it a worktree is treated as outside
  git and keeps the main checkout's names.
- Linked worktrees still share the HTTP port and the Compose stack (planned for 0.3.0).

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

[Unreleased]: https://github.com/skhol3/oasis/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/skhol3/oasis/releases/tag/v0.2.0
[0.1.0]: https://github.com/skhol3/oasis/releases/tag/v0.1.0
