# Checking the environment

Two commands, for two questions:

- `oasis --project /absolute/project doctor` asks *can oasis work here at all?* It checks the environment contract up front and is read-only: it never starts a service, never connects to a database and never prints file contents. In Gentle Shell, `/oasis doctor` (or `/odoo19 doctor`) shows the same report.
- `check-environment [--quick|--full]` asks *does the project environment match its locks?* `--quick` (the default) checks the requirement files and their fingerprint, `lock.sha256`, the environment's Python, the virtualenv, uv, the Odoo version and `compose config`; it skips the installed packages, the dependency audit and PostgreSQL (`SKIP <check>=use_--full`). `--full` also checks the installed packages against the locks (`dev.txt`) and their compatibility, audits dependencies and queries PostgreSQL, so it needs the database service running.

## The declared Python

The environment's Python is the one the configuration declares: the series' default for a workspace with `[tooling].environment` (`python_default` in `tools/odoo_versions.py`, 3.12 on 19.0), else the `python` of the selected named environment (see [Workspace file](workspace-file.md#checkout-file-and-named-environments)). `bootstrap` creates a missing environment with it (`bootstrap --preview` prints `planned_action=create_python_<version>_and_sync_lock`, or `compile_locks_then_create_python_<version>_and_sync_lock` when it also compiles the [locks](#dependency-locks)), compiles the locks with it, and refuses an existing environment with another Python; `check-environment` reports `PASS python_version=<version>`, and on a mismatch stops with exit 2 before any other check:

```text
Python 3.13 is required; found 3.12.
Move /home/you/odoo/19.0/environments/acme-next away and run oasis bootstrap --apply to recreate it with Python 3.13.
```

`bootstrap --apply` saves the packages it found before the sync as `bootstrap-before.txt` in the checkout's log directory: `<logs>/<slug, or main>/` with `[tooling].logs`, else `dev/logs/odoo19/` (before 0.12.0 it went to `dev/runtime/`, which a workspace checkout does not have).

## Dependency locks

`lock.sha256` lists the dependency inputs and locks (`runtime.in`, `runtime.txt`, `dev.in`, `dev.txt`) with their SHA-256, in `sha256sum` format, relative to its own directory: regenerate it there with `sha256sum runtime.in runtime.txt dev.in dev.txt > lock.sha256`. `check-environment` (`dependency_locks`) and `bootstrap` run `sha256sum --check --strict lock.sha256` from that directory first and, for a legacy lock whose entries are relative to the project root (the checkout), from the project root next; either one passing is enough. `oasis migrate` rewrites a legacy lock relative to its directory with the same hashes.

`bootstrap` compiles the locks itself when they need it, before it creates or syncs the environment:

| Locks | `bootstrap --preview` | `bootstrap --apply` |
| --- | --- | --- |
| current: `lock.sha256` passes | unchanged output (`uv pip sync --dry-run`) | syncs; the requirement files stay byte-identical |
| missing: `runtime.txt`, `dev.txt` or `lock.sha256` does not exist | `locks=missing` | compiles, then creates or syncs |
| stale: `lock.sha256` does not record the current `runtime.in` and `dev.in` (an input changed, or the file cannot be read) | `locks=stale` | compiles, then creates or syncs |
| edited: `lock.sha256` records the current inputs but not a lock (changed by hand) | refused, exit 2 | refused, exit 2 |

When it compiles, `--preview` changes nothing and names both steps: `planned_action=compile_locks_then_sync_lock` for an existing environment, `planned_action=compile_locks_then_create_python_<version>_and_sync_lock` for a missing one. `--apply` runs, in the requirements directory and with the [declared Python](#the-declared-python), the commands of [Setting up a new workspace](new-workspace.md#steps) step 4: `uv pip compile --python-version <version> runtime.in -o runtime.txt`, then the same for `dev.in` and `dev.txt` (an existing lock keeps its pins where it can, as uv prefers them), writes `lock.sha256` as `sha256sum` would, prints `locks_compiled=runtime.txt,dev.txt,lock.sha256` and goes on as before. It never writes `runtime.in` or `dev.in`; both must exist (`Missing required local path: <path>`, exit 2). A failed compile stops with exit 2 before `lock.sha256` and the environment change:

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

## The doctor report

`doctor` prints one `PASS|WARN|FAIL <check>[=<value>]` line per check, then `doctor_failures=<n>`, and exits 1 when `n > 0` (a `WARN` does not count), else 0. A check that needs another one is left out when that one failed.

| Check | Passes when | Otherwise |
| --- | --- | --- |
| `configuration` | the workspace file loads; the value is `workspace` | `FAIL configuration=<error>` (a checkout that still has the file of earlier versions gives the refusal that names `oasis migrate`, see [Migrating](migrating.md)); the checks after `proc` are left out |
| `odoo_version` | always, when the configuration loads (only supported series load) | |
| `agent_destructive` | always, when the configuration loads: the value of `[tooling].agent_destructive` (`ask`, `deny` or `allow`; `ask` when absent), see [Bash guard](bash-guard.md#the-setting) | an invalid value fails `configuration` |
| `git` | `git --version` reports 2.31 or newer | `FAIL git=missing`, `FAIL git=<version> minimum=2.31` |
| `docker`, `docker_compose` | `docker` is on PATH and `docker compose version` succeeds | `FAIL docker=missing` (no `docker_compose` line), `FAIL docker_compose=unavailable` |
| `flock` | `flock` is on PATH | `WARN flock=missing`: the database service starts without the cross-checkout lock |
| `proc` | `/proc` is mounted | `WARN proc=missing`: server records cannot tell a live server |
| `python` | the environment's Python exists and reports the expected version (3.12, or the named environment's) | `FAIL python=missing`, `FAIL python=<found> expected=<version>` |
| `odoo_release` | `odoo/release.py` of the Odoo source declares `odoo_version` | `FAIL odoo_release=<found> expected=<version>` |
| `odoo_conf` | odoo.conf exists and parses | `FAIL odoo_conf=missing\|unreadable\|invalid`; in a workspace checkout, `WARN odoo_conf=addons_path,data_dir` (the options it still holds that oasis passes on the command line) |
| `compose` | the compose file declares a top-level `name:` | `FAIL compose=missing`, `FAIL compose=missing_top_level_name` |
| `env_file` | the env file exists (never opened) | `FAIL env_file=missing` |
| `logs_dir`, `data_dir` | the directory, or its nearest existing parent, is writable; `data_dir` only with `[tooling].data_dir` | `FAIL logs_dir=not_writable` |
| `http_port` | the port `start` would use is free, or is this checkout's running server (`server=this_checkout`) | `WARN http_port=<port> in_use` |

Tools are found on PATH, as `command -v` finds them, never through a tool manager; the only programs doctor runs are `git --version`, `docker compose version` and the environment's Python (for its version). A tool-manager shim on PATH can still install on first use (see [Tool-manager side effects](troubleshooting.md#tool-manager-side-effects)). No agent tool runs doctor.
