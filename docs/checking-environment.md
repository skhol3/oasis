# Checking the environment

One command, `doctor`, for two questions (v0.16.0: `check-environment` became `doctor --environment`; see
[check-environment, a deprecated alias](#check-environment-a-deprecated-alias)):

- `oasis --project /absolute/project doctor` asks *can oasis work here at all?* It checks the environment contract up front and is read-only: it never starts a service and never prints file contents; its one connection logs in to PostgreSQL with the account Odoo uses (`postgres_connection`, below). In Gentle Shell, `/oasis doctor` shows the same report.
- `oasis --project /absolute/project doctor --environment [--quick|--full]` asks *does the project environment match its locks?* `--quick` (the default) checks the requirement files and their fingerprint, `lock.sha256`, the environment's Python, the virtualenv, uv, the Odoo version and `compose config`; it skips the installed packages, the dependency audit and PostgreSQL (`SKIP <check>=use_--full`). `--full` also checks the installed packages against the locks (`dev.txt`, [The installed packages](#the-installed-packages)) and their compatibility, audits dependencies and logs in to PostgreSQL with the account Odoo uses (`postgres_connection`: the environment's Python and psycopg2 connect to the `db_host` and `db_port` of `odoo.conf` with the `db_user` and `db_password` it sets, else those of the env file; see [The database account](setup.md#the-database-account)), so it needs the database service running. A stopped service is `FAIL postgres_service=not_running`, followed on stderr by `  fix: oasis --project <checkout> start-database` (v0.16.0). It prints `PASS postgres_connection=ready` or `FAIL postgres_connection=<authentication_failed|not_running|no_driver|failed|unchecked>` (`unchecked`: the probe printed none of the other words, an error of the environment's Python), never a value or the server's message; `authentication_failed` is followed on stderr by the same `  fix:` line as doctor's. It ends with `environment_mode=<quick|full>` and `environment_failures=<n>` (exit 1 when `n > 0`). Both modes print `FAIL env_file=unsupported_value <names>` and doctor's `  fix:` line on stderr when the env file writes an account variable Odoo would get with compose interpolation or a double-quoted escape ([The database account](setup.md#the-database-account)); `--full` then does not try the connection. The dependency audit (`oasis audit-dependencies [module]`, also run by `bootstrap --apply`) runs with the environment's Python, 3.7 and later: it maps each imported top-level module to its distribution with `importlib.metadata.packages_distributions` from Python 3.10, and on older Pythons (Odoo 15) from the installed distributions' `top_level.txt`, else their file lists, with the same output.

## The declared Python

The environment's Python is the one the configuration declares: the series' default for a workspace with `[tooling].environment` (`python_default` in `tools/odoo_versions.py`, 3.12 on 19.0), else the `python` of the selected named environment (see [Workspace file](workspace-file.md#checkout-file-and-named-environments)). `bootstrap` creates a missing environment with it (`bootstrap --preview` prints `planned_action=create_python_<version>_and_sync_lock`, or `compile_locks_then_create_python_<version>_and_sync_lock` when it also compiles the [locks](#dependency-locks)), compiles the locks with it, and refuses an existing environment with another Python; `doctor --environment` reports `PASS python_version=<version>`, and on a mismatch stops with exit 2 before any other check:

```text
Python 3.13 is required; found 3.12.
Move /home/you/odoo/19.0/environments/acme-next away and run oasis bootstrap --apply to recreate it with Python 3.13.
```

`bootstrap --apply` saves the packages it found before the sync as `bootstrap-before.txt` in the checkout's log directory, `<logs>/<slug, or main>/`: `[tooling].logs`, else `logs` next to the workspace file (before 0.17.0 that default was `dev/logs/odoo19/`; before 0.12.0 it went to `dev/runtime/`, which a workspace checkout does not have). When the mark of an environment it just created cannot be written, it prints `WARNING: cannot mark <environment> as created by oasis (<environment>/.oasis-created: <reason>): its drift from the locks is reported as a WARN, as for an adopted environment; create that file to have it reported as a FAIL.` to stderr and goes on (`setup --apply` too).

### The exit code of bootstrap

`bootstrap --apply` ends with `doctor --environment --full` (the trailing doctor), and its exit code reports its own work, the locks and the sync (v0.20.0). These keep it non-zero, as before:

- A failure of its own work: a refusal (exit 2), a failed compile of the locks (exit 2), `uv venv` or `uv pip sync` failing (their exit code). It stops there and runs no doctor.
- The trailing doctor's `FAIL locked_environment=drifted` (stderr) for the environment it just synced: the sync did not produce the locked environment ([The installed packages](#the-installed-packages): an environment oasis created that still drifts, a lock that cannot be read, a comparison that crashed). It exits with the doctor's code (1) and prints nothing after the doctor's lines, also when other checks failed too.

- A trailing doctor that did not complete: it did not run (exit 126 or 127, a missing or not executable `check-environment`) or died (a Python traceback, a signal, exit 128+n), so it printed no `environment_failures=<n>` summary line, or it exited with a code other than 0 or 1. Its lines are printed line by line, its exit code is bootstrap's, and one line on stderr says so:

  ```text
  doctor=incomplete exit=127: the trailing doctor --environment --full did not complete (no environment_failures= summary line); the sync succeeded; run oasis --project /home/you/odoo/19.0/projects/acme doctor --environment --full
  ```

  The cause in parentheses is `it printed its summary but exited <n>, not a check result` when the summary
  line was printed with an exit other than 0 or 1. A line without a trailing newline gains one.

Any other failure of a trailing doctor that completed (exit 1 and its `environment_failures=<n>` summary line on stdout) is outside the sync, for example `FAIL postgres_service=not_running` because PostgreSQL is not running yet, a failed `postgres_connection`, `compose_config` or `dependency_audit`: the exit is 0, and the doctor's lines are printed line by line, followed on stdout by:

```text
sync=succeeded
doctor=failed exit=1: the checks above are the results of the trailing doctor --environment --full; the sync succeeded
  next: fix what they report (their fix: lines), then run oasis --project /home/you/odoo/19.0/projects/acme doctor --environment --full
```

bootstrap reads two doctor lines, the drift `FAIL` line and the summary line; both are defined in one place in `tools/bootstrap`, next to the place in `tools/environment_checks.sh` that prints them.

When it passes, the output ends with its `environment_failures=0`, as before; a drift of an adopted environment is a `WARN` there and does not count. Before 0.20.0, `bootstrap --apply` exited with the trailing doctor's code (1 when any check failed, even after a successful sync).

## Dependency locks

`lock.sha256` lists the dependency inputs and locks (`runtime.in`, `runtime.txt`, `dev.in`, `dev.txt`, and `overrides.txt` last when it [exists](#overridestxt)) with their SHA-256, in `sha256sum` format, relative to its own directory: regenerate it there with `sha256sum runtime.in runtime.txt dev.in dev.txt > lock.sha256` (`... dev.txt overrides.txt > lock.sha256` with that file). `doctor --environment` (`dependency_locks`) and `bootstrap` run `sha256sum --check --strict lock.sha256` from that directory first and, for a legacy lock whose entries are relative to the project root (the checkout), from the project root next; either one passing is enough. `oasis migrate` rewrites a legacy lock relative to its directory with the same hashes.

`bootstrap` compiles the locks itself when they need it, before it creates or syncs the environment:

| Locks | `bootstrap --preview` | `bootstrap --apply` |
| --- | --- | --- |
| current: `lock.sha256` passes | unchanged output (`uv pip sync --dry-run`) | syncs; the requirement files stay byte-identical |
| missing: `runtime.txt`, `dev.txt` or `lock.sha256` does not exist | `locks=missing` | compiles, then creates or syncs |
| stale: `lock.sha256` does not record the current `runtime.in` and `dev.in`, or the current [`overrides.txt`](#overridestxt) (an input changed, or the file cannot be read) | `locks=stale` | compiles, then creates or syncs |
| edited: `lock.sha256` records the current inputs but not a lock (changed by hand) | refused, exit 2 | refused, exit 2 |

When it compiles, `--preview` changes nothing and names both steps: `planned_action=compile_locks_then_sync_lock` for an existing environment, `planned_action=compile_locks_then_create_python_<version>_and_sync_lock` for a missing one. `--apply` runs, in the requirements directory and with the [declared Python](#the-declared-python), the commands of [Setting up a new workspace](new-workspace.md#steps) step 4: `uv pip compile --python-version <version> runtime.in -o runtime.txt`, then the same for `dev.in` and `dev.txt` (an existing lock keeps its pins where it can, as uv prefers them), writes `lock.sha256` as `sha256sum` would, prints `locks_compiled=runtime.txt,dev.txt,lock.sha256` and goes on as before. It never writes `runtime.in` or `dev.in`; both must exist (`Missing required local path: <path>`, exit 2). uv's messages go to stderr as uv writes them, while it resolves. A failed compile stops with exit 2 before `lock.sha256` and the environment change:

```text
uv pip compile of dev.in failed (exit 1); lock.sha256 was left as it was.
Fix /home/you/odoo/19.0/projects/acme/config/requirements/dev.in or its access to the package index, then run oasis bootstrap --apply again.
```

An edited lock is never overwritten:

```text
Refusing bootstrap because dependency inputs or locks do not match lock.sha256.
runtime.in and dev.in match it, so a lock was changed by hand: move that lock away for bootstrap to compile it again, or fingerprint it again in <requirements> with sha256sum runtime.in runtime.txt dev.in dev.txt > lock.sha256.
```

Without uv on PATH, `bootstrap` stops with exit 2: `uv is required to bootstrap this environment.`, then `Install uv (https://docs.astral.sh/uv/), then run oasis bootstrap again.`

### overrides.txt

`overrides.txt` in the requirements directory, next to `runtime.in`, is an optional lock input: requirements that replace the ones Odoo's `requirements.txt` pins, such as `cryptography==3.4.8` for an older Python. [`oasis setup`](setup.md#the-projects-requirement-files) writes it, as `-r ../requirements-overrides.txt`, when it adopts a series folder that holds `requirements-overrides.txt`; you may also write it yourself. When it exists:

- Every compile, by `bootstrap --apply` or `oasis setup`, runs `uv pip compile --python-version <version> --override overrides.txt runtime.in -o runtime.txt`, then the same for `dev.in` and `dev.txt`; uv follows a nested `-r` in it.
- `lock.sha256` records it after the four files. An `overrides.txt` that `lock.sha256` does not record (added after the locks), one whose digest changed, or one it records that no longer exists makes the locks stale: `bootstrap` compiles them again (`locks=stale`), and `doctor --environment` fails `dependency_locks=stale_or_modified` until then, since `sha256sum --check` alone cannot see a file `lock.sha256` omits.
- A lock changed by hand under current inputs is refused as before, naming it: `runtime.in, dev.in and overrides.txt match it, so a lock was changed by hand: ... fingerprint it again in <requirements> with sha256sum runtime.in runtime.txt dev.in dev.txt overrides.txt > lock.sha256.`

Without it, the compile commands, `lock.sha256` and every message are exactly as before. `lock.sha256` records `runtime.in` and `overrides.txt`, not the files they include with `-r`: after changing an included file, move `lock.sha256` away so that `bootstrap --apply` compiles the locks again.

## The installed packages

`doctor --environment --full` (and `check-environment --full`, and the end of `bootstrap --apply`) compares
every pin of `dev.txt` with the distributions installed in the environment, with the environment's Python
(3.8 and later). Names are normalized on both sides as [PEP 503](https://peps.python.org/pep-0503/) does
(v0.17.0): lowercase, and runs of `-`, `_` and `.` become `-`, so `zope.event-5.0.dist-info`, as pip
installs it, satisfies `zope-event==5.0` in the lock on every Python (before 0.17.0 an Odoo 15 environment
reported it as `missing_package=zope-event==5.0`). It prints `locked_packages=<n>`, one
`missing_package=<name>==<version>` or `version_mismatch=<name>: expected=<x> actual=<y>` per difference,
then `missing_packages=<n>` and `version_mismatches=<n>`. A dist-info or egg-info without usable metadata (none, no
name or version, or not readable as text) is left out, so the package it would be is reported missing instead of
the comparison failing. The comparison (`tools/check_environment.py`, also the project wrapper
`dev/scripts/check_environment.py <lockfile>`) exits 0 when the environment matches, 3 when it drifted (1 before
0.17.0), 2 for a lock it cannot read, and 1 for a crash (a traceback), which is therefore never reported as a drift.
The result depends on who created the environment:

| Environment | Matches the locks | Does not match them |
| --- | --- | --- |
| Created by oasis: `bootstrap --apply` or `setup --apply` ran `uv venv` and marked it with `<environment>/.oasis-created` | `PASS locked_environment=exact` | `FAIL locked_environment=drifted` on stderr, counted in `environment_failures` (exit 1) |
| Adopted: [`setup --environment`](setup.md#an-existing-environment), an answered path, or any environment without that mark | `PASS locked_environment=exact` | `WARN locked_environment=drifted`, then `  fix: oasis --project <checkout> bootstrap --apply (syncs the adopted environment <dir> to the locks: it changes the packages installed there)`, both on stdout; not counted (the exit code is the one without the drift) |

An adopted environment belongs to you: no oasis command writes into it, marks it or syncs it, except an
explicit `bootstrap --apply` (read `bootstrap --preview`, its `uv pip sync --dry-run`, first). A lock that
cannot be read (malformed, unpinned, no pins) and a comparison that crashed are a `FAIL locked_environment=drifted`
for every environment.
An environment oasis created before 0.17.0 has no mark and is reported as adopted; to have its drift fail
again, create the mark yourself (`touch <environment>/.oasis-created`), or move the environment away and
run `bootstrap --apply`, which creates and marks it.

## check-environment, a deprecated alias

`check-environment [--quick|--full]` is the name `doctor --environment` had before v0.16.0. It keeps
working and stays deprecated: through either entry point, from a project wrapper
(`dev/scripts/check-environment`) or as the tool script, it runs the same checks as
`doctor --environment` with the same mode and prints the same lines, with the same exit codes, as
before; only its usage line differs (`Usage: <program> [--quick|--full]`, as before, against
`Usage: <program> doctor [--environment [--quick|--full]]`). Both are refused where the other is: in a
checkout without a workspace file or with a legacy profile, where `doctor` alone still runs (one
`FAIL configuration`). `bootstrap --apply` still ends with these checks in `--full` mode (since 0.20.0 only their
`FAIL locked_environment=drifted` makes it exit 1: [The exit code of bootstrap](#the-exit-code-of-bootstrap)). Use
`doctor --environment` in new scripts and instructions; the agent tool `oasis_check_environment`
runs it. The policy table lists both, Tier A ([Agent contract](agent-contract.md)).

## The doctor report

`doctor` prints one `PASS|WARN|FAIL <check>[=<value>]` line per check, then `doctor_failures=<n>`, and exits 1 when `n > 0` (a `WARN` does not count), else 0. A check that needs another one is left out when that one failed. Each `FAIL` line is followed by one indented line with the command or action that fixes it (only `FAIL` lines count):

```text
FAIL env_file=empty ODOO_DB_USER,ODOO_DB_PASSWORD
  fix: oasis setup --apply
FAIL python=missing
  fix: oasis bootstrap --apply
```

| Failure | `fix:` |
| --- | --- |
| `configuration`: the legacy profile | `oasis migrate --plan, then oasis migrate --apply` |
| `configuration`: no workspace file (`Missing tooling configuration: ...`), no section for the checkout's series (`... has no [series."<x.y>"] section: ...`), or no Odoo source (`No Odoo source for <x.y>: ...`); `odoo_conf=missing`, `compose=missing`, `env_file=missing` | `oasis setup --apply` |
| `configuration`: any other error | `correct the setting the error names, then run oasis doctor again` |
| `git` | `install git 2.31 or newer on PATH` |
| `docker`, `docker_compose` | `install Docker with its compose plugin on PATH`; `install the Docker Compose plugin: docker compose version must succeed` |
| `python=missing` | `oasis bootstrap --apply` |
| `python=unavailable`, `python=<found> expected=<version>` | `move <environment> away, then oasis bootstrap --apply` |
| `code_python=<x.y> <file>:<line>: <message>; needs Python <a.b> or newer (best-effort)` | `use an environment whose Python can load the code (Python <a.b> or newer): set that Python for the environment in <workspace file> (docs/workspace-file.md), move <environment> away, then oasis bootstrap --apply; where setup plans an environment, --environment <dir> or --python <x.y> chooses it` ([The environment's Python and the code](#the-environments-python-and-the-code)) |
| `odoo_release=missing`, `odoo_release=<found> expected=<x.y>` | `set community under [series."<x.y>"] in <machine file> to an Odoo <x.y> source`, or `set [tooling].community in <workspace file> ...`: the file the source came from |
| `module_series` | `run oasis in a checkout of an Odoo <x.y> branch, or set the version of <module> to <x.y>.x.y.z ...` (see [Workspace file](workspace-file.md#discovery-precedence-and-versions)); with `workspace_version = 2` also `..., or list <module> in series_exceptions under [series."<x.y>"] in <workspace file>`. Where setup would propose the exception (the checkout stays an Odoo `<x.y>` one and the workspace file has no `[series."<x.y>"]` table), the oasis action comes first (v0.16.0): `oasis --project <checkout> setup --answer series_exceptions=add --apply lists <module> in series_exceptions under [series."<x.y>"] in <workspace file> (setup proposes the exception), or run oasis in ...` ([Modules of another series](setup.md#modules-of-another-series)) |
| `series_isolation=db_port`, `series_isolation=compose_project` | `publish another port to 5432 in <compose file> and set db_port in <odoo.conf> to it`; `set another top-level name: in <compose file>`; both `set compose under [series."<x.y>"] in <workspace file> to a compose file of its own` when the series share one compose file |
| `series_isolation=prefixes`, `series_isolation=env_file` | `set dev_prefix and test_prefix under [series."<x.y>"] in <workspace file> to a pair of its own`; `set env_file under [series."<x.y>"] in <workspace file> to a file of its own` |
| `odoo_conf=unreadable`, `compose=unreadable`, `env_file=unreadable` | `make <file> readable by you` |
| `odoo_conf=invalid`; `compose=missing_top_level_name` | `correct the syntax of <odoo.conf>`; `add a top-level name: to <compose file>` |
| `env_file=empty <names>` | `oasis setup --apply`: it generates the empty variables in place, every other byte of the file kept ([The database account](setup.md#the-database-account)) |
| `env_file=unsupported_value <names>` | `write <names> in <env file> literally in single quotes: oasis does not read compose interpolation ($) or double-quoted escapes (\), so Odoo would get another credential` |
| `postgres_connection=authentication_failed` | when `odoo.conf` sets `db_user` or `db_password` to other values than the env file: `<odoo.conf> sets <options> to other values than <env file>: remove <options> from <odoo.conf> so Odoo uses the account of <env file>, then run oasis doctor again`; when `odoo.conf` points at the compose service (`db_host` `127.0.0.1` or `localhost` and the port the compose file publishes to 5432): `the PostgreSQL that <odoo.conf> names refuses the account Odoo uses: its volume was initialized with other credentials than <env file>; oasis --project <checkout> recreate-database-volume --confirm <compose project> recreates it with them (Tier B: it deletes every database of the service)`; when oasis cannot read the port the compose file publishes to 5432 (`it cannot be read`, `several ports`, or `an entry other than - [<address>:]<port>:5432` under `ports:`): `the PostgreSQL that <odoo.conf> names (db_host <host>, db_port <port>) refuses the account Odoo uses, and oasis could not read the port <compose file> publishes to 5432 (<why>), so it cannot tell whether that server is the service of <compose file>: if it is, oasis --project <checkout> recreate-database-volume --confirm <compose project> recreates its volume with the account of <env file> (Tier B: it deletes every database of the service); if it is not, correct that account on that server; then run oasis doctor again`; otherwise `the PostgreSQL that <odoo.conf> names (db_host <host>, db_port <port>) refuses the account Odoo uses, and it is not the service of <compose file> (published on 127.0.0.1:<port>): correct that account on that server, or set db_host = 127.0.0.1 and the db_port <compose file> publishes in <odoo.conf>; then run oasis doctor again` |
| `logs_dir=not_writable`, `data_dir=not_writable` | `make <path> a directory you can write`: the directory, or, when it does not exist yet, its nearest existing parent (also when that is a file) |
| `http_port=invalid` | `set http_port in <odoo.conf> to a port number` |
| `project_wrappers=old_install_dir`: a file of the checkout's `dev/scripts/` (the [project wrappers](project-setup.md)) still calls `~/.agents/skills/odoo19`, the install directory before 0.17.0; the last check, with no line when none does | `replace .agents/skills/odoo19/ with .agents/skills/oasis/ in <wrappers> (the oasis install directory since 0.17.0)`, where `<wrappers>` are their paths (`a`, `a and b`, `a, b and c`) ([From an earlier version](install.md#from-an-earlier-version)) |

The commands the fix lines name start with `oasis`. `doctor` and `setup` are the commands the entry point runs in a checkout without a workspace file: doctor then reports `FAIL configuration=Missing tooling configuration: ...` with `fix: oasis setup --apply`.

| Check | Passes when | Otherwise |
| --- | --- | --- |
| `configuration` | the workspace file loads; the value is `workspace` | `FAIL configuration=<error>` (a checkout that still has the file of earlier versions gives the refusal that names `oasis migrate`, see [Migrating](migrating.md)); the checks after `proc` are left out |
| `odoo_version` | always, when the configuration loads (only supported series load): the checkout's series | |
| `series`, `series_exceptions` | with `workspace_version = 2` only: `series=<x.y> from=<checkout\|manifests\|workspace>`, where the checkout's series came from (see [The checkout's series](workspace-file.md#the-checkouts-series)); `series_exceptions=<modules>` when its section lists any | a series without a section fails `configuration` |
| `series_isolation` | with `workspace_version = 2` and several series: no two series resolve to the same database port (published by their compose files), compose project, `dev_prefix` or `test_prefix`, or env file; the value lists the series (`19.0,15.0`) | `FAIL series_isolation=<db_port\|compose_project\|prefixes\|env_file> series=<x.y>,<x.y>`, one per group of series sharing it (see [Isolation](workspace-file.md#isolation)) |
| `agent_destructive` | always, when the configuration loads: the value of `[tooling].agent_destructive` (`ask`, `deny` or `allow`; `ask` when absent), see [Bash guard](bash-guard.md#the-setting) | an invalid value fails `configuration` |
| `odoo_source_from`, `enterprise_source_from`, `project_environment_from`, `checkout_slug_from` | always, when the configuration loads, one line per layered value that is set: where it came from (`tools/config.py --origins`, see [Workspace file](workspace-file.md#what-the-tools-read-from-it)), as `machine:<machine file>`, `workspace:<workspace file>`, `checkout:<checkout>/oasis-checkout.toml` or `derived` (a linked worktree's slug from its directory name). No Enterprise, no slug: no line | |
| `git` | `git --version` reports 2.31 or newer | `FAIL git=missing`, `FAIL git=<version> minimum=2.31` |
| `docker`, `docker_compose` | `docker` is on PATH and `docker compose version` succeeds | `FAIL docker=missing` (no `docker_compose` line), `FAIL docker_compose=unavailable` |
| `flock` | `flock` is on PATH | `WARN flock=missing`: the database service starts without the cross-checkout lock |
| `proc` | `/proc` is mounted | `WARN proc=missing`: server records cannot tell a live server |
| `python` | the environment's Python exists and reports the expected version (3.12, or the named environment's) | `FAIL python=missing`, `FAIL python=unavailable` (it does not run or prints no version), `FAIL python=<found> expected=<version>` |
| `code_python` | the environment's Python compiles every `.py` file of the checkout: `PASS code_python=<x.y> files=<n>` ([below](#the-environments-python-and-the-code)). Left out when `python` failed | `FAIL code_python=<x.y> <file>:<line>: <message>; needs Python <a.b> or newer (best-effort)` (`the lowest Python it needs is unknown` when oasis cannot tell); `WARN code_python=syntax_error <file>:<line>: <message>` (oasis' own Python rejects the file too); `WARN code_python=timeout files=<n> seconds=<s>`; `WARN code_python=unchecked` (the environment's Python did not answer) |
| `odoo_release` | `odoo/release.py` of the Odoo source declares `odoo_version` | `FAIL odoo_release=missing` (no `odoo/release.py`), `FAIL odoo_release=<found> expected=<version>` (`unknown` when it declares none) |
| `module_series` | no line when no module of the `addons_paths` declares another series than `odoo_version` (manifests without a series-style version are ignored) | `FAIL module_series=<found> module=<module> expected=<version>`; every other command refuses such a checkout (see [Workspace file](workspace-file.md#discovery-precedence-and-versions)) |
| `odoo_conf` | odoo.conf exists and parses | `FAIL odoo_conf=missing\|unreadable\|invalid`; in a workspace checkout, `WARN odoo_conf=addons_path,data_dir` (the options it still holds that oasis passes on the command line) |
| `odoo_conf_password` | no line when odoo.conf sets no `db_password` (empty, `False` and `None` are unset, as Odoo reads them) | `WARN odoo_conf_password`, followed by a `  fix:` line: `oasis setup --apply moves it to <env file> and removes <options> from <odoo.conf> (those lines only)` when the env file holds the same account (or assigns it an empty value, which setup fills from odoo.conf); otherwise `remove <options> from <odoo.conf> once the account of <env file> is the one PostgreSQL accepts (oasis doctor checks it); oasis setup --apply removes it itself when both files hold the same values`. Never a value |
| `compose` | the compose file declares a top-level `name:` | `FAIL compose=missing`, `FAIL compose=unreadable`, `FAIL compose=missing_top_level_name` |
| `env_file` | the env file exists, can be read, and does not assign an empty value to `ODOO_DB_USER` or `ODOO_DB_PASSWORD`, as an older `oasis setup` left them (`NAME=`, `NAME=""`, `NAME=''`, also after `export` or before a ` # comment`; the last assignment counts), and writes the ones Odoo gets (those `odoo.conf` leaves unset) as oasis reads them: no compose interpolation (`$`) outside single quotes and no `\` in double quotes. A file that assigns neither (another account's names) is respected: `WARN env_file=unassigned ODOO_DB_USER,ODOO_DB_PASSWORD`, with the fix `setup leaves <env file> unchanged (an existing file is respected); to use the account oasis generates, add the empty lines ODOO_DB_USER= and ODOO_DB_PASSWORD= to it, then run oasis setup --apply`. Only the names are printed, never a value or a line | `FAIL env_file=missing`, `FAIL env_file=unreadable`, `FAIL env_file=empty <names>`, `FAIL env_file=unsupported_value <names>`, `WARN env_file=unassigned <names>` |
| `logs_dir`, `data_dir` | the directory, or its nearest existing parent, is writable; `data_dir` only with `[tooling].data_dir` | `FAIL logs_dir=not_writable`, `FAIL data_dir=not_writable` |
| `http_port` | the port `start` would use is free, or is this checkout's running server (`server=this_checkout`) | `WARN http_port=<port> in_use` |
| `postgres_connection` | the environment's Python logs in to the PostgreSQL `odoo.conf` names (`db_host` and `db_port`, each left to libpq when empty, as Odoo does) with the account Odoo uses: the `db_user` and `db_password` of `odoo.conf`, else `ODOO_DB_USER` and `ODOO_DB_PASSWORD` of the env file (`tools/db_account.py probe`, psycopg2). Left out when `python`, `odoo_conf` or `env_file` failed. Only one word is reported, never a value or the server's message | `FAIL postgres_connection=authentication_failed` (a server answered and refused the account: a volume initialized with other credentials, or `odoo.conf` values that differ from the env file); `WARN postgres_connection=not_running` (nothing answered: every database command starts the service), followed by `  fix: oasis --project <checkout> start-database` (v0.16.0: it names no env file); `WARN postgres_connection=unchecked` (no psycopg2 in the environment, or another error) |

Tools are found on PATH, as `command -v` finds them, never through a tool manager; the only programs doctor runs are `git --version`, `docker compose version` and the environment's Python (for its version, the compile of the code and the connection probe). A tool-manager shim on PATH can still install on first use (see [Tool-manager side effects](troubleshooting.md#tool-manager-side-effects)). No agent tool runs this report; the agent tool `oasis_check_environment` runs `doctor --environment`.

### The environment's Python and the code

An environment's Python can be one the series supports and still not load the checkout's code (v0.20.0; in the
v0.17.0 field run an environment of Python 3.8 was adopted for a 15.0 checkout whose code uses `match`, which
needs 3.10). After `python`, doctor runs the environment's Python once, `<python> -I -B tools/code_python.py
compile`, with every `.py` file of the checkout on its stdin (not in `.git`, `node_modules` or `__pycache__`, nor in
a directory holding a `pyvenv.cfg`, such as the environment itself when it is inside the checkout; symbolic links
are left out). It compiles the bytes of each file (`compile(source, path, 'exec')`: a coding cookie applies,
nothing is executed and no `.pyc` is written) and answers with the files that do not compile. Its time limit grows
with the files: 20 seconds plus 1 second per 20 files.

```text
FAIL code_python=3.8 /home/you/odoo/15.0/projects/acme/acme_sale/models.py:3: Pattern matching is only supported in Python 3.10 and greater; needs Python 3.10 or newer (best-effort)
  fix: use an environment whose Python can load the code (Python 3.10 or newer): set that Python for the environment in /home/you/odoo/oasis-workspace.toml (docs/workspace-file.md), move /home/you/odoo/environments/acme-15 away, then oasis bootstrap --apply; where setup plans an environment, --environment <dir> or --python <x.y> chooses it
```

- The file is the first one the environment's Python cannot load, with its line and the compiler's message.
- The lowest Python the code needs is best-effort: oasis' own Python parses the code with the grammar of each
  newer Python (`ast.parse(feature_version=...)`), which knows `match`, `except*` and type parameters but not
  every change, such as parenthesized context managers. The FAIL itself always comes from the environment's own
  Python.
- A file that oasis' own Python does not compile either is a syntax error in the code, not a limit of the
  environment's Python: `WARN code_python=syntax_error <file>:<line>: <message>`, followed by `  fix: correct
  <file>: it does not compile with oasis' own Python either, so it is a syntax error in the code, not a limit of the
  environment's Python`. It is not counted, and a file the environment's Python cannot load still fails first.
- The Python of an environment is set in the workspace file: `python` of its `[environments.<name>]` table or of
  its `[series."<x.y>"]` section, else the series' default ([The declared Python](#the-declared-python)).
  `bootstrap` refuses an existing environment of another Python, hence the move before `bootstrap --apply`.

[`oasis setup`](setup.md#the-python-of-the-environment-and-the-code) warns in its plan when the Python of the
environment it adopts or creates may not load the code.
