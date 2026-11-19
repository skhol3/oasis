# Changelog

All notable changes to oasis are recorded here. The format follows Keep a Changelog
(`keepachangelog.com`) and versions follow Semantic Versioning (`semver.org`).

While the version is `0.x`, the contract (the `odoo19` command names and options, the
`.odoo19-agent.toml` `[tooling]` keys, the database prefix guards and the skill names) may
still change in a minor release; every such change is listed here under **Changed**.

## [Unreleased]

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

[Unreleased]: https://github.com/skhol3/oasis/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/skhol3/oasis/releases/tag/v0.2.0
[0.1.0]: https://github.com/skhol3/oasis/releases/tag/v0.1.0
