# Checking the environment

Two commands, for two questions:

- `oasis --project /absolute/project doctor` asks *can oasis work here at all?* It checks the environment contract up front and is read-only: it never starts a service, never connects to a database and never prints file contents. In Gentle Shell, `/oasis doctor` (or `/odoo19 doctor`) shows the same report.
- `check-environment [--quick|--full]` asks *does the project environment match its locks?* It checks the requirement files and their fingerprint, `lock.sha256`, the virtualenv, uv and `compose config`; `--full` also checks installed packages, audits dependencies and queries PostgreSQL.

## Dependency locks

`lock.sha256` lists the dependency inputs and locks (`runtime.in`, `runtime.txt`, `dev.in`, `dev.txt`) with their SHA-256, in `sha256sum` format, relative to its own directory: regenerate it there with `sha256sum runtime.in runtime.txt dev.in dev.txt > lock.sha256`. `check-environment` (`dependency_locks`) and `bootstrap` run `sha256sum --check --strict lock.sha256` from that directory first and, for a legacy lock whose entries are relative to the project root (the checkout), from the project root next; either one passing is enough. `oasis migrate` rewrites a legacy lock relative to its directory with the same hashes.

## The doctor report

`doctor` prints one `PASS|WARN|FAIL <check>[=<value>]` line per check, then `doctor_failures=<n>`, and exits 1 when `n > 0` (a `WARN` does not count), else 0. A check that needs another one is left out when that one failed.

| Check | Passes when | Otherwise |
| --- | --- | --- |
| `configuration` | the profile or workspace file loads; the value is `legacy` or `workspace` | `FAIL configuration=<error>`; the checks after `proc` are left out |
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
