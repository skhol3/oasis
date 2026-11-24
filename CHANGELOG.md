# Changelog

All notable changes to oasis are recorded here. The format follows Keep a Changelog
(`keepachangelog.com`) and versions follow Semantic Versioning (`semver.org`).

While the version is `0.x`, the contract (the `oasis` and `odoo19` command names and
options, the `.odoo19-agent.toml` `[tooling]` keys, the database prefix guards and the skill
names) may still change in a minor release; every such change is listed here under **Changed**.

## [Unreleased]

## [0.10.0] - 2026-11-24

A one-screen map of a module from source: `module-info`.

### Added

- `module-info <module> [--section <name>]`: a one-screen map of one module from its source,
  without starting Odoo: manifest header (version, summary or name, depends, addons root),
  models defined and extended with their field counts and `file:line`, base views per model and
  type and extensions per inherited view, the menu tree, actions, security (groups, access
  lines with their flags, record rules), data and demo files in manifest order with crons, files
  on disk the manifest does not list and listed files that are missing, and the test files with
  their classes. Python is parsed with `ast`, XML with expat and CSV with `csv`; nothing is
  imported or executed. Long lists end with `+<n> more`; `--section` prints one section
  uncapped. An unknown module exits 1 with `module not found: <module>`. New command: nothing
  existing changes.
- Agent tool `oasis_module_info` (module, optional section), active in Odoo projects and in the
  overlay of both subagents (read-only). Some lines of the prompt section were shortened to
  keep it under 1200 characters.
- Action menu: **Modules** › "Show a module's overview from source" runs `module-info`.

## [0.9.0] - 2026-11-23

An action menu to run Odoo operations by hand: `oasis menu` in a terminal and a pop-up panel in
Gentle Shell (`alt+o`), both from one catalog; `start --detach` runs the server in the background.

### Added

- `oasis menu`: numbered menus of the everyday actions of a checkout (server, modules, tests,
  databases and maintenance) that ask the inputs, show the exact command before running it and
  ask you to type the database name or `yes` before a destructive action. It needs a terminal
  (exit 2 without one). `oasis menu --catalog` prints the same actions as JSON for the Gentle
  Shell panel; `tools/actions.py` is the only list of actions.
- `start --detach [odoo options]`: starts the checkout's server in the background with its
  output appended to `server.log` in the compact log directory (`dev/logs/odoo19/`, or
  `<logs>/<slug or main>/` with `[tooling].logs`), prints `pid=<pid> port=<port> log=<path>`
  and returns; a server that exits at once is reported with the end of its log (exit 1). The
  record and `stop` are the same. Without `--detach`, `start` is unchanged.
- Gentle Shell action panel: `alt+o` (`OASIS_MENU_KEY` changes it; empty or `off` disables it)
  and `/oasis menu` open an overlay with the actions of `oasis menu --catalog`. It asks the inputs
  with Pi's dialogs, confirms destructive and user-run actions as the catalog says, runs the exact
  command in the project root and shows it with its output (compact for `test-module` and
  `update-module`) as a session entry that is never sent to the model. No agent tool opens it.
- The bash guard of the Gentle Shell layer blocks agents from running `oasis menu` or `odoo19
  menu`, `--catalog` included, and the menu's scripts `tools/menu` and `tools/actions.py` when
  they are oasis's: each is resolved against the session's directory and literal `cd`/`pushd`
  targets in the same command, and blocked when its `tools` directory sits next to the `oasis`
  entry point and `tools/actions.py` (the installed bundle, an oasis checkout), also when run
  relatively. A `tools/menu` of another project is not blocked; asking only for help is allowed.
- In the terminal menu a number picks from the list and is never taken as a new name; a listed
  value made of digits (a database named `2024`) is taken as written.

## [0.8.0] - 2026-11-23

The harness names itself oasis in what it sets and prints. Everything existing keeps working;
see the contract note in the README.

### Added

- `OASIS_PROJECT_ROOT`, `OASIS_ENTRYPOINT`, `OASIS_TOOLS_DIR` and `OASIS_COMPOSE_LOCK_TIMEOUT`:
  the tools read each one first and its `ODOO19_*` name when it is unset or empty, so the
  `ODOO19_*` names keep working. The entry point and the project wrappers set both names with
  the same value.

### Changed

- With `[tooling].logs`, compact runs and browser evidence go to `<logs>/<slug or main>/run-*`,
  without the `odoo19/` level. Existing `<logs>/odoo19/` directories are never moved or deleted,
  and `oasis_test_summary` accepts the run logs of both layouts. Without `[tooling].logs` runs
  stay under `dev/logs/odoo19/`.
- Messages, help and usage no longer say "Odoo 19": `Unsupported oasis command: <name>` and
  `oasis tools are not installed: <path>` (also in the project wrappers). Help and messages that
  tell you to run `gc`, and the `start` banner, name the invoked entry point (`oasis`, or
  `odoo19` through the alias) instead of a fixed `odoo19`. Errors about the project root name
  `OASIS_PROJECT_ROOT`.
- The variables that pass only between `test-module --compact` and the run it starts are
  `OASIS_RUN_RESULT` and `OASIS_REUSE_RESULT` (internal, no legacy name).
- The Gentle Shell extension is `pi/extensions/oasis.ts`; its prompt section and tag are
  `oasis` and its status message type `oasis-status`.
- `oasis_test_summary` reads run logs only inside the checkout's log locations: `<logs>/` with
  `[tooling].logs`, otherwise `dev/logs/odoo19/` of the checkout (and of the main checkout in a
  linked worktree). A path elsewhere is refused even when it looks like a run log, and so is a
  run directory or log file that is a symlink leading outside those locations.

### Fixed

- `test_shared_conf` (and the port tests of `test_runtime_state`) no longer fail when another
  process's loopback connection takes the port after the configured one: the tests choose their
  configured ports outside the kernel's ephemeral port range.

## [0.7.1] - 2026-11-21

### Fixed

- `xmlid-info` left a whole line out of `referenced by` when it contained `inherit_id`. Only the
  inherit_id reference of a data file is left out now: a `groups` or other reference on the same
  line, and Python that assigns `inherit_id`, are listed.

## [0.7.0] - 2026-11-20

Query tools for views and XML ids, read from source like `model-info`.

### Added

- `view-info <model> [--type <tag>] [--module <technical>]`: the views of a model with the
  views that extend them, their type, XML id, file and line.
- `xmlid-info <module>.<name>`: where an XML id is defined, its fields, the views that extend
  it and the files that reference it.
- Agent tools `oasis_view_info` and `oasis_xmlid_info`, in the overlay of both subagents: run
  `/oasis setup` to refresh an installed overlay.

### Fixed

- A database existence probe that fails now ends the command with `Cannot check whether
  database <name> exists.` instead of looking like a missing database (`module-status` reported
  `database_state=missing`, `update-module` "does not exist", and `test-module --reuse` reset
  the working database).

### Changed

- Prompt section: three tool lines are shorter so the section stays compact with two more tools.

## [0.6.0] - 2026-11-20

Faster test iteration, and a harness that takes the Odoo series from the configuration. Odoo
19.0 remains the only supported series.

### Added

- `test-module --reuse`: keeps a working test database between runs (the explicit database,
  else `tooling.test_database`, else `<test_prefix>[<slug>_]<module>`). When it exists with the
  module installed, the run updates the module and runs the tests instead of installing it in a
  new database; `--compact` adds `database_lifecycle=reused mode=<install|update>`.
  `oasis_test_module` takes `reuse`. Without `--reuse` nothing changes. A run that cannot read
  the module state stops without touching the database.
- Capability `test_class_filter`, and `python3 -I -B tools/odoo_versions.py <version> <key>` to
  read one capability from a shell tool. `test-module --only` asks it.

### Changed

- The Gentle Shell layer names the project's Odoo series from its configuration: the prompt
  section and `/oasis` status start with `Odoo <series> project` (`Odoo project` when the
  configuration cannot be read) instead of a fixed `Odoo 19` / `odoo19 project:`; the prompt
  names the matching `odoo<major>-*` skills; tool labels, descriptions and messages say `Odoo`.
- Internal: the tools no longer write the series. The release and runtime checks,
  `check-environment` and `lint-module` take it from the configuration (`ODOO_VERSION`); their
  output for 19.0 is unchanged. A test fails when a tool names the series outside the
  capability table.

## [0.5.0] - 2026-11-20

Day-to-day operation: narrower test runs, compact updates and the migration plan for agents.
Additions only; no existing command, option, output or guard changes meaning.

### Added

- `test-module --only <Class[.method]>`: runs one test class of the module, or one method of it
  (`--test-tags /<module>:<Class>[.<method>]`). The module is still installed first.
  `oasis_test_module` takes `only` and says so when it matched no test.
- `update-module --compact`: keeps the log on disk and prints the exit code and the log paths.
- `oasis_update_module` (agent tool): updates a module in an existing managed database and
  returns errors and grouped warnings only. The subagent overlay gives it to the worker, not to
  the read-only verify agent: run `/oasis setup` to refresh an installed overlay.
- `migrate --plan`: prints the plan and can never apply (`--plan` with `--apply` is a usage
  error). The bash guard lets an agent run exactly that form, optionally with `--workspace` and
  a literal absolute path; every other form of `migrate` stays user-run.

### Fixed

- Bash guard: `setsid`, `stdbuf`, `ionice` and `doas` are wrappers, so a blocked program or a
  heredoc reader behind them is detected.

## [0.4.2] - 2026-11-20

Follow-ups of the Gentle Shell audit and of the v0.4.1 reviews. No contract changes.

### Fixed

- Bash guard, false blocks: a heredoc body is checked only when a command on its opening line
  runs what it reads, so `git add . && git commit -F - <<'EOF'` or a quoted word such as
  `"fix ssh"` no longer makes a message that mentions `psql` or `dropdb` a command.
- Bash guard, coverage restored: comments after `;`, `&&`, `|` or `(` no longer hide a later
  substitution, `#` after an escaped space is not a comment, and heredocs are checked when their
  reader is on a continued line, after a trailing pipe, behind `docker exec`, or is `ksh`,
  `mksh`, `ash`, `fish`, `csh` or `tcsh`.
- The prompt section names only the `oasis_*` tools the session has; a session with none (a
  subagent without the overlay) is pointed to the `oasis` CLI.

### Changed

- The agent may ask the user-run commands for their help: `migrate` and `worktree-init` with
  `--help` or `-h` as the single argument are no longer blocked. Every other form stays user-run.
- README and release steps: install the Gentle Shell package from the release tag instead of a
  local checkout.
- Internal: the `/oasis` subcommands have one table for completion, usage, description and
  dispatch; the test heartbeat is a tested helper.

## [0.4.1] - 2026-11-19

Operational fixes from an audit of the Gentle Shell layer.

### Added

- `oasis_test_summary` (agent tool): the summary of a compact test run started in the
  background, from the text `test-module --compact` printed; it reads only the run logs that
  output names. The subagent overlay lists it: run `/oasis setup` to refresh an installed one.
- `oasis_test_module` reports the elapsed time every 15 seconds while the suite runs.
- `/oasis` completes its subcommands (`setup`, `doctor`, `migrate`, `worktree`).

### Fixed

- The bash guard no longer blocks text bash would not run: substitutions inside single
  quotes and heredoc bodies written to a file (commit messages, pull request bodies and
  generated scripts that mention `psql`, `dropdb`, `odoo-bin` or the user-run commands). A
  heredoc fed to a shell and substitutions in double quotes stay blocked.

### Changed

- The six `odoo19-*` skills follow the Gentle Shell skill style guide more closely: decision
  gates are tables, each skill says when not to use it and which sibling applies, and long
  rules moved to local references (`test-targets.md`, `checkout-resources.md`,
  `operation-selection.md`) without losing content. Skill names and triggers are unchanged.

## [0.4.0] - 2026-11-19

Location and version independence: one `oasis-workspace.toml` per project instead of a
profile per checkout, a path-free `odoo.conf`, a per-version capability table, the neutral
`oasis` name (with `odoo19` aliases), `oasis doctor` and `oasis migrate`.

### Fixed

- `oasis migrate --apply` undoes its changes on SIGTERM or SIGHUP, and rewrites `odoo.conf`
  last, so a process killed earlier leaves a conf that still names its paths.
- A batch `start --stop-after-init` excludes an explicit `--http-port` from the second free
  port only when it is a valid port (1-65535); any other value still reaches Odoo as given.
- `gc` stops (exit 2) when a linked worktree's `oasis-checkout.toml` is untrusted or
  invalid, instead of guessing that worktree's slug from its folder.

### Added

- Test summary control line `log: <lines> lines, <errors> errors, <warnings> warnings`, with
  uncapped counts for checking the summary against the full logs.
- `oasis-workspace.toml`, one per project at its root: a checkout without
  `.odoo19-agent.toml` (`--project`, or the git top level of the Gentle Shell session
  directory) reads the nearest one above it, at any depth; a directory with a profile on the
  way ends the search. It requires `workspace_version = 1` and `odoo_version = '19.0'`, and its
  `[tooling]` table takes the profile's keys and guards except the derived `version` and
  `python_version`. Paths resolve from the workspace file's directory, `addons_paths` from each
  checkout. A checkout with its own profile is read exactly as before.
- Optional `oasis-checkout.toml` in a workspace checkout: it may set only
  `[tooling].checkout_slug` and `[tooling].environment`; any other key is refused.
- `tools/config.py` appends `WORKSPACE_ROOT` (empty for a profile) after `LOGS_DIR`.
- `worktree-init` in a workspace (main checkout without a profile) only runs
  `git worktree add` and prints `workspace: <dir>`.
- The `odoo19` entry point, the `odoo19_*` tools, the prompt context and `/odoo19` accept a
  checkout without a profile below a workspace file.
- Example `odoo19-environment/assets/oasis-workspace.example.toml`.
- `tools/odoo_versions.py`: one capability table per Odoo series (only `19.0`: Python 3.10 to
  3.14, PostgreSQL 13, `--gevent-port`, demo-off `--without-demo`, `--test-tags` implies
  `--stop-after-init`); the supported `odoo_version` values come from it.
- `tools/config.py` appends `ODOO_VERSION`, `ODOO_SECOND_PORT_OPTION`, `ODOO_DEMO_OFF_ARGS`,
  `ENVIRONMENT_NAME` and `PYTHON_VERSION` after `WORKSPACE_ROOT`, for a profile too; the
  previous assignments are unchanged.
- Named environments in a workspace: `[environments.<name>]` with `path` and `python` (within
  the series' range) instead of `[tooling].environment`; a checkout uses `default` unless its
  `oasis-checkout.toml` sets `[tooling].environment` to another name.
- Workspace trust: `oasis-workspace.toml` and `oasis-checkout.toml` are read only when the
  file and its directory are owned by the current user or root and are not group- or
  other-writable; otherwise `Refusing untrusted workspace file <file>: <reason>.`
- In workspace mode, `init-dev-database` reads `[development]` and `lint-module` reads
  `lint_rcfile` (resolved from the workspace file's directory) from the workspace file, and
  `gc` takes another worktree's slug from its `oasis-checkout.toml`.
- Gentle Shell project detection compares real paths (a symlinked session directory resolves
  to the checkout root) and retries a failed git top-level lookup instead of caching it.
- Optional `[tooling].data_dir` (profile and workspace): every Odoo launch gets
  `--data-dir=<path>`, and disposable runs and `gc --apply` remove filestores under it instead
  of the `odoo.conf` `data_dir`. `tools/config.py` appends `DATA_DIR` (empty when absent) after
  `PYTHON_VERSION`.
- Path-free `odoo.conf`: without an `addons_path`, every Odoo launch of the main checkout and
  linked worktrees gets `--addons-path=<enterprise>,<addon roots>,<community>/addons`;
  `Cannot compose --addons-path: <path> contains a comma.` stops a root with a comma.
- `runtime_state.py ephemeral-port` accepts ports to exclude.
- New public command `oasis doctor` (also `odoo19 doctor`, and `/oasis doctor` or `/odoo19
  doctor` in Gentle Shell, with no agent tool): a read-only check of the environment contract
  (configuration, git 2.31 or newer, docker and `docker compose version`, flock, `/proc`, the
  environment's Python, the Odoo source release, odoo.conf, the compose file's top-level `name:`,
  the env file, the logs and data directories, the HTTP port). It prints one
  `PASS|WARN|FAIL <check>[=<value>]` line per check and `doctor_failures=<n>`, exits 1 when
  `n > 0`, never starts services, connects to a database or prints file contents.
- New public command `oasis migrate [--workspace <dir>] [--apply]` (also `odoo19 migrate`), user-run:
  converts the agreeing `.odoo19-agent.toml` of every checkout of the repository into one
  `oasis-workspace.toml` (0600; paths relative to it, `addons_paths` per checkout) and an
  `oasis-checkout.toml` for each `checkout_slug`, removes `addons_path` and `data_dir` from
  `odoo.conf` (`data_dir` moves to `[tooling].data_dir`; the original is kept as
  `odoo.conf.bak-<stamp>`, 0600), rewrites `lock.sha256` relative to its directory with the same
  hashes, and renames each profile to `.odoo19-agent.toml.bak-<stamp>`. Without `--apply` it only
  prints the plan. With it, every checkout must load the same configuration and Odoo addons path
  and data directory as before; otherwise every change is undone (exit 1). Disagreeing profiles,
  a `--workspace` that is not above every checkout and an existing workspace file are refused
  (exit 2). A second run prints `nothing to migrate: <checkout> has no .odoo19-agent.toml`.
- `/oasis migrate` (and `/odoo19 migrate`) in Gentle Shell: shows the plan and runs
  `migrate --apply` after confirmation. The bash guard blocks agents from running `migrate`
  through `oasis` or `odoo19` or its tool script, the dry run included.

### Changed

- `check-environment` (`dependency_locks`) and `bootstrap` check `lock.sha256` from its own
  directory first, then from the project root as before, so a lock whose entries are relative to
  its directory passes; a legacy lock keeps passing.
- Test runs (`test-module`, the tests phase of `verify-module`) and `start --stop-after-init`
  also get a free second port (`--gevent-port=<port>` on 19.0, distinct from the free
  `--http-port`), so HttpCase tests never collide with a running server's second port; an
  explicit one is passed to `start` as given.
- An `odoo.conf` without `addons_path` used to give `-c <odoo.conf>` alone (Odoo's default
  addons path); it now gets the composed `--addons-path`. With an `addons_path` and without
  `[tooling].data_dir`, command lines are unchanged.

- The demo-off option of `test-module`, `install-module` (and so `verify-module`) and
  `init-dev-database` now comes from the capability table (`ODOO_DEMO_OFF_ARGS`); it is
  unchanged on 19.0 (`--without-demo`).
- `start` passes and recognizes the second server port through `ODOO_SECOND_PORT_OPTION`
  (`--gevent-port` on 19.0); its command lines are unchanged.
- `require_runtime` compares the interpreter with `PYTHON_VERSION` (3.12 for a profile).
- Renamed to oasis: the entry point is `oasis` (installed next to `odoo19`), the Gentle Shell
  tools are `oasis_test_module`, `oasis_find_module`, `oasis_model_info`,
  `oasis_module_status`, `oasis_check_environment` and `oasis_lint_module`, and the command
  is `/oasis` (`setup`, `worktree <feature> <branch>`). Aliases are kept: `odoo19` runs the
  same dispatcher (identical commands, options, exit codes and output; help and usage name
  the program invoked), `/odoo19` runs the same handler, and the `odoo19_*` tools stay
  registered with the same implementation but are never activated by the layer. The overlay
  template names the `oasis_*` tools, so an installed overlay is reported as outdated until
  `/oasis setup` runs again. The prompt context and the bash guard's messages name `oasis`;
  the guard also blocks `oasis ... worktree-init`. The install directory and the `odoo19-*`
  skill names are unchanged.

## [0.3.0] - 2026-11-18

Several checkouts of one project side by side: shared configuration, a server and port per
checkout, disposable test databases and `/odoo19 worktree` to create a worktree.

### Added

- `odoo19 --project <checkout> worktree-init <feature> <branch> [--dry-run]`: creates the
  linked worktree `<main folder>-<feature>` next to the main checkout (existing local branch,
  tracked `origin/<branch>`, or a new branch from the main checkout's `HEAD`) and prepares it:
  copies the untracked profile, links the untracked and ignored entries of `dev/`, copies
  `dev/odoo.conf` (0600) with the worktree root in `addons_path` and without `db_name`, creates
  an own `dev/runtime`, and links the profile's `env_file`. User-run only.
- `/odoo19 worktree <feature> <branch>` in Gentle Shell: shows the dry-run plan and runs
  `worktree-init` after confirmation. The bash guard blocks agents from running
  `worktree-init` in every session.
- Shared `odoo.conf` for every checkout: in a linked worktree, the commands that start Odoo
  (`test-module`, `verify-module`, `install-module`, `update-module`, `odoo-shell`, `start`,
  `init-dev-database`) pass `--addons-path=<value>` after `-c`. The value is the conf's
  `addons_path` (read with `tools/odoo_addons_path.py`; no other option is read or printed),
  with each item at or under the main checkout's root moved to the worktree's root. The main
  checkout and projects outside git keep the same command line. In a linked worktree, an
  `odoo.conf` that cannot be parsed stops those commands with exit 2 before Odoo starts.
- `worktree-init --resume`: an existing folder that is a worktree of this repository on the
  requested branch gets only its missing items (`kept existing <path>` for the others).
- Optional `[tooling].logs` (a path relative to the checkout): `--compact` runs of
  `test-module` and `verify-module` and the browser evidence of test runs go to
  `<logs>/odoo19/<checkout>/run-*` (`main` for the main checkout, the slug for a linked
  worktree), so checkouts need no `dev/` directory. A run directory that resolves outside
  `<logs>` is refused with `Compact logs must remain inside the configured logs directory.`
  `tools/config.py` reports it as a new last line `LOGS_DIR` (empty without the key), and
  `worktree-init` checks that a shared layout's copied profile resolves it to the same
  directory. Without the key, logs stay under `dev/logs/odoo19` as before.
- Per-checkout Odoo server: `start` records its pid and HTTP port in
  `${XDG_RUNTIME_DIR:-/tmp}/oasis-<uid>/<sha256(checkout)[:16]>/server.json` (0700, outside
  the repository; `tools/runtime_state.py`) and refuses a second server for the same checkout.
  The main checkout uses the `http_port` of `odoo.conf` (8069 when absent) and refuses a busy
  one; a linked worktree takes the first free port from `http_port + 1` (up to `+ 50`) and a
  free `--gevent-port` after `gevent_port`; an explicit `-p`/`--http-port` wins. `start`
  passes `--http-port=<port>` after the configuration options and prints
  `odoo19 start: http://localhost:<port> (pid <pid>)` to stderr. A port that cannot be bound
  for another reason than being in use stops `start` with `Cannot bind port <port>: <reason>.`
  (exit 2). A record stays live for 10 s after `started_at` while its pid exists (the window
  before Odoo is exec'd), then only while the process is the Odoo launch
  (`<python> <odoo-bin> ...`, where `<python>` starts with `python` or is the profile's python
  that `start` records in `server.json`, realpaths compared); a stale record is removed only
  if the file is unchanged.
- `start ... --stop-after-init` is a batch run: it skips the server and port checks, writes no
  record and passes a free `--http-port=<port>` (an explicit port is passed as given), so it
  runs while this checkout's server serves. Database guards still apply.
- `status` starts with `server: running pid <pid> port <port>` or `server: stopped`
  (`server: unknown (<reason>)` when the runtime state cannot be read, the reason taken from
  its stderr; warnings of a successful read go to stderr unchanged; `compose ps` still runs);
  `/odoo19` shows `server: running on port <port> (pid <pid>)` or `server: stopped`
  (`runtime_state.py show <checkout>`, no service or database access).
- `test-module` and the tests phase of `verify-module` (also with `--compact`) pass
  `--http-port=<free port>` to the Odoo test process, so test runs never collide with a
  running server ("Port ... is in use by another program").
- `odoo19 --project <checkout> gc [--apply] [--all-checkouts]` (new public command): lists
  the disposable test databases of this checkout's namespace that no live run holds
  (`orphan <name>` lines and `orphans=<n>`) and changes nothing; `--apply` closes their
  sessions, drops them and removes their filestores and stale run locks (`dropped <name>`).
  A failed drop prints `failed <name>` on stderr and the next orphan is still dropped; the run
  ends with `dropped=<n>` and `failed=<m>` and exits 1 when `m` is not 0. The main checkout's
  namespace excludes its existing linked worktrees';
  `--all-checkouts` lists every slug of the test prefix (dropping other namespaces is refused
  in a checkout with a slug). Development databases, test databases without the run suffix
  and the configured `test_database` are never touched. No agent tool runs it.
- `odoo19_test_module` reports `database_lifecycle=disposable dropped=<yes|no>` on its result
  line for disposable runs.

### Changed

- `stop` (contract change) stops only this checkout's Odoo server (SIGTERM, up to 20 s);
  without one it prints `No Odoo server running for this checkout.` and exits 0. It used to
  stop every Compose service. `stop --database` stops the database service, and only when no
  other checkout has a live server; otherwise it exits 2 and lists those checkouts and ports.
- `test-module` and `verify-module` (contract change) without an explicit database and
  without `[tooling].test_database` run on a new disposable database
  `<test_prefix>[<slug>_]<module>_r<6 hex>` (shortened with a hash of the module to fit 56
  bytes; `verify-module` adds its `_update` sibling) instead of resetting and reusing
  `<test_prefix>[<slug>_]<module>`. Each run creates its run lock in the checkout's runtime
  state directory exclusively (`O_EXCL`, 0600, fsynced) before creating the database: an
  existing lock of that name, live or stale, exits 2 with
  `Disposable test database is locked: <name>` and touches neither the lock nor the
  database. It refuses a name that already exists, treats the database as its own once
  `createdb` succeeded (after a failed `createdb`, a database of that name that exists now
  and that no other live run of the user holds a lock of is the run's own and is dropped,
  `Cannot create disposable test database <name>; it was created anyway and is dropped.`;
  otherwise it drops nothing, removes only the run's lock and reports
  `Cannot create disposable test database <name>; it was not dropped.`; both exit non-zero),
  and always drops the database, its `<data_dir>/filestore/<name>` directory and the lock at
  the end: on success, failure, SIGINT and SIGTERM. With `--compact` only, both commands print
  `database_lifecycle=disposable dropped=<yes|no>` (`test-module` after `phase=tests ...`,
  from the result the run itself writes to `database_lifecycle` in its log directory;
  `verify-module` as its last line). An explicit or configured database keeps the
  reset-and-reuse behaviour; pass `<test_prefix><module>` explicitly to keep the previous
  default.
- Names ending in `_r<6 hex>` (optionally `_update`) are reserved for disposable runs
  (contract change): `test-module`, `verify-module` (explicit or configured `test_database`),
  `create-database`, `install-module`, `update-module`, `odoo-shell`, `start -d`/`--database`
  and `init-dev-database` refuse them with exit 2 and
  `Database names ending in _r<6 hex> are reserved for disposable runs: <name>` before
  anything runs. `drop-database`, `module-status` and `gc` still accept them.
- Checkout identity fails closed when git fails inside a repository (git missing, a 5 s
  timeout, a non-zero exit or unexpected output): with a `.git` file at or above the project
  root (a linked worktree) every command exits 2 with
  `Cannot determine the checkout identity: git failed in a linked worktree; check git or set [tooling].checkout_slug.`
  unless `checkout_slug` is set (then kind `linked` with that slug and an empty
  `CHECKOUT_MAIN_ROOT`; commands that start Odoo refuse a shared `odoo.conf` they cannot move
  to the worktree); with a `.git` directory every command exits 2 with
  `Cannot determine the checkout identity: git failed (<reason>).` Before, both were treated
  as a project outside git (kind `none`), which dropped a linked worktree's slug and
  namespace guard. Without any `.git` (searched like git, honouring
  `GIT_CEILING_DIRECTORIES`) the kind is still `none`.
- `start` in the main checkout refuses a busy `http_port` with
  `Port <port> is in use; pass --http-port or stop the other server.` before anything runs,
  and reads `http_port`, `gevent_port` and `http_interface` (only those) from `odoo.conf`.

- `worktree-init` with a shared configuration directory (the profile's `config`, `env_file`,
  `compose` and `requirements` all outside the checkouts) copies only the profile, after
  checking that its paths resolve to the same files from the new folder. It links nothing and
  writes no `odoo.conf` or `dev/`. Other layouts keep the previous behaviour. The README
  recommends the shared layout (`<project>/codigo/<checkouts>`, `<project>/config/`,
  `<project>/data/`).

### Fixed

- Two checkouts that share a compose file no longer race when they start the database
  service at the same moment (the second `compose up` failed with Docker's container name
  conflict): `compose up` now runs under an exclusive `flock` of a per-compose-file lock in
  the user's runtime directory, waiting at most 120 s (`Timed out waiting for another
  checkout to start the database service.`, exit 1). Without `flock` it warns and runs
  unlocked.
- A disposable run never drops a database when `createdb` reports that the name already
  exists (created by something without a run lock); `verify-module` no longer loses a signal
  that arrives right after its locks are taken.
- `status` no longer stops before the server line and `compose ps` when `TMPDIR` is missing
  or not writable: it captures the runtime state read without a temporary file.
- `verify-module` no longer leaks a run lock when SIGINT or SIGTERM arrives between writing a
  lock and recording it: the signal is deferred until the lock is recorded, then the run
  removes its locks and exits 130 or 143.
- `worktree-init` from a linked worktree, when the main checkout's profile (the one that
  gets copied) lacks `config`, `env_file`, `compose` or `requirements` or is not valid TOML,
  refuses with `<profile> does not set [tooling].<key>; prepare the worktree by hand.` or
  `Invalid tooling configuration: <profile>` instead of a message that did not name the file.
- `init-dev-database` in a linked worktree checks the `odoo.conf` it would pass to Odoo before
  any password prompt or database service call: an `odoo.conf` that cannot be parsed exits 2
  with `Cannot read addons_path from <path>: invalid configuration file.` (and a shared one
  that cannot be moved without git with `Cannot move the addons_path of <path> ...`), like
  the other commands that start Odoo. Before, it asked for every password, started the
  database service and then failed with exit 1 and a generic message.

### Known limitations

- Server liveness reads `/proc`: per-checkout servers work on Linux only.
- Simultaneous `start` runs may probe and pick the same free port; start them one at a time.
- Disposable runs and `gc` read `/proc` for run-lock liveness (Linux only). SIGKILL leaves a
  disposable database behind for `gc`. A SIGTERM sent only to `verify-module` (not to its
  process group) takes effect when the phase in progress ends. A run killed after taking its
  lock but before its database existed leaves a lock that `gc` does not remove (it acts on
  existing databases); that random name stays locked. Without an absolute
  `data_dir` in `odoo.conf` filestores are not removed. With `--compact`, a SIGTERM sent only
  to the outer `test-module` process ends it without the summary; the run it started still
  finishes and drops its database.
- Only `-p`, `--http-port <port>` and `--http-port=<port>` are recognized as explicit ports;
  abbreviations such as `--http-p` reach Odoo but are not checked or recorded.

## [0.2.0] - 2026-11-17

Linked git worktrees get their own databases: one checkout no longer steps on another.

### Added

- Checkout identity: `tools/config.py` also emits `CHECKOUT_KIND` (`main`, `linked`, `none`)
  and `CHECKOUT_SLUG`, derived read-only from git; a linked worktree's slug comes from its
  directory name (`corpus-cafe-07.1` -> `07_1`). Optional `[tooling].checkout_slug` overrides
  it. `/odoo19` shows a `checkout:` line.
- `update-module --help` and `odoo-shell --help` describe their database guards.
- `/odoo19 setup`: after confirmation, installs or updates the subagent overlay
  `pi/agent-overlays/oasis.json` as `agent-overlays.d/oasis.json` in the Gentle AI config
  home (`GENTLE_PI_CONFIG_HOME` or `~/.gentle-shell/gentle-ai`), adding the six `odoo19_*`
  tools to the `gentle-ai-worker` and `gentle-ai-verify` subagents; it does nothing when the
  overlay is up to date (see the README, Subagents).
- Session notice: in an Odoo project, oasis reminds the user once per session to run
  `/odoo19 setup` when the overlay is missing or outdated.

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
- The six `odoo19_*` tools are only active in Odoo projects: they are registered inactive and
  activated at session start when `.odoo19-agent.toml` is found at or above the working
  directory, so other projects pay no tokens for them. `/odoo19` stays available everywhere.

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

[Unreleased]: https://github.com/skhol3/oasis/compare/v0.10.0...HEAD
[0.10.0]: https://github.com/skhol3/oasis/releases/tag/v0.10.0
[0.9.0]: https://github.com/skhol3/oasis/releases/tag/v0.9.0
[0.8.0]: https://github.com/skhol3/oasis/releases/tag/v0.8.0
[0.7.1]: https://github.com/skhol3/oasis/releases/tag/v0.7.1
[0.7.0]: https://github.com/skhol3/oasis/releases/tag/v0.7.0
[0.6.0]: https://github.com/skhol3/oasis/releases/tag/v0.6.0
[0.5.0]: https://github.com/skhol3/oasis/releases/tag/v0.5.0
[0.4.2]: https://github.com/skhol3/oasis/releases/tag/v0.4.2
[0.4.1]: https://github.com/skhol3/oasis/releases/tag/v0.4.1
[0.4.0]: https://github.com/skhol3/oasis/releases/tag/v0.4.0
[0.3.0]: https://github.com/skhol3/oasis/releases/tag/v0.3.0
[0.2.0]: https://github.com/skhol3/oasis/releases/tag/v0.2.0
[0.1.0]: https://github.com/skhol3/oasis/releases/tag/v0.1.0
