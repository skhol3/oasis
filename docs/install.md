# Install or update

oasis has two installs, each with its own job. Install both to get everything; neither brings what
the other does.

| Install | What you get | Where it works |
| --- | --- | --- |
| [`./install.sh`](#installing-the-skills-and-the-cli-with-installsh) from this repository | The six `odoo-<topic>` skills and the `oasis` CLI in `~/.agents/skills/oasis` | Any agent (Claude Code, Codex, Gentle Shell) and the terminal |
| [The package](#installing-the-package) from a release tag | The `oasis_*` agent tools, `/oasis`, the `alt+o` panel and the bash guard | Gentle Shell |

- The package does not bring the skills: Gentle Shell finds them in `~/.agents/skills`,
  where `install.sh` puts them. It carries its own copy of the CLI for its tools; the
  `~/.agents/skills/oasis/oasis` path that the skills and docs name comes from `install.sh`.
- `install.sh` copies the package files too, but does not add the tools, `/oasis` or the panel to
  Gentle Shell; only the package install does.
- Since 0.17.0 one name serves every Odoo series: the install directory is `~/.agents/skills/oasis`
  and `oasis` is the one entry point (see [From an earlier version](#from-an-earlier-version)).

## Released versions

Releases follow Semantic Versioning and are tagged `vX.Y.Z`; the [changelog](../CHANGELOG.md)
lists them. Below, `<tag>` is one of those tags, for example `v0.14.0`.

## Installing the skills and the CLI with install.sh

With owner authorization, commit the change, run the test suite, then run `install.sh` from this repository:

```bash
python3 -B -m unittest discover -s tests
./install.sh                                 # installs HEAD into ~/.agents/skills/oasis
./install.sh --target /absolute/scratch/oasis # try it somewhere else first
```

The installer copies the committed HEAD only (uncommitted edits are never installed), drops repository-only files (`AGENTS.md`, `.gitignore`, `install.sh`), records the installed version (from `package.json`) and commit in `.oasis-install.json`, and moves the previous install to `${XDG_STATE_HOME:-~/.local/state}/oasis/backups/`, outside any skill discovery directory. `OASIS_STATE_DIR` overrides that state directory. Run it again to update.

### From an earlier version

Since v0.21.0 nothing of an install before 0.17.0 (`~/.agents/skills/odoo19`) is moved, read or reported: the
[README](../README.md) contract note of v0.21.0 says what a project from an earlier version runs (its
`.odoo19-agent.toml`, project wrappers that call `~/.agents/skills/odoo19/tools`, an old `lock.sha256`). Only the
`OASIS_*` variables are read; neither the entry point nor the wrapper templates set an `ODOO19_*` one.

## Running the CLI

`--project` is optional. Without it the project is the git top level of the current directory
(the current directory itself outside git), so these two run the same command:

```bash
~/.agents/skills/oasis/oasis --project /absolute/project doctor --environment --quick
cd /absolute/project/addons && ~/.agents/skills/oasis/oasis doctor --environment --quick
```

A directory with no `oasis-workspace.toml` at or above its checkout (or, for a linked worktree,
through git) gets the same refusal as `--project` to it, except for `doctor` and `setup`, which
run without a workspace file: [`setup`](setup.md) creates one, and `doctor` reports
`FAIL configuration=Missing tooling configuration: ...` with `fix: oasis setup --apply`.
`--project` keeps working as before.

## Where the Odoo source is declared

Declare the Odoo source of each series once per machine, in `~/.config/oasis/config.toml`
(`$XDG_CONFIG_HOME/oasis/config.toml` when that is set); every project of that series then uses
it, and a project's workspace file sets a source only to override it. `oasis setup` writes it the
first time it sets up a project of that series. See [Machine file](workspace-file.md#machine-file).

```toml
[series."19.0"]
community = '/srv/odoo/19.0/source/odoo'
enterprise = '/srv/odoo/19.0/source/enterprise'
```

## Installing the package

From a release tag, so sessions load a fixed copy that work in a local checkout cannot change:

```bash
gentle-shell install git:github.com/skhol3/oasis@<tag>
```

Then `/reload` open sessions, and run `/oasis setup` once for the subagent overlay (see
[Subagents](subagents.md)).

## Moving the package to another release

Remove the installed tag and install the new one, then `/reload` open sessions. `gentle-shell list`
shows the installed entry.

```bash
gentle-shell remove git:github.com/skhol3/oasis@<installed tag>
gentle-shell install git:github.com/skhol3/oasis@<new tag>
```

Installing a local checkout (`gentle-shell install /absolute/path/to/oasis`) loads whatever that
directory holds, including a branch under development; use it only to try changes.

## What gets installed

The `install.sh` target contains the six `odoo-<topic>` skill directories, `tools/`, `project-wrappers/`, `tests/`, `docs/`, the `oasis` entry point, the Gentle Shell layer (`package.json` and `pi/`), and the [README](../README.md). Restart the agent session or use `/reload` where supported, then check that exactly six skills are discovered. The skill entrypoints are [backend](../odoo-backend/SKILL.md), [security](../odoo-security/SKILL.md), [views/frontend](../odoo-views-frontend/SKILL.md), [testing](../odoo-testing/SKILL.md), [environment](../odoo-environment/SKILL.md), and [module lifecycle](../odoo-module-lifecycle/SKILL.md). Each SKILL.md is common to every series. The backend, security, views/frontend and testing skills send the agent to the task recipes of its series in `references/<series>/` (since 0.19.0; one recipe per task and series, rendered from `recipes/`); the environment and module lifecycle skills send it to their `references/<series>.md`. The series is the one `oasis doctor` prints (`series=`, else `odoo_release=`). Since 0.17.0 the skills are named `odoo-<topic>`; the `odoo19-*` skills of earlier versions are gone: installing replaces the whole target and moves a previous `~/.agents/skills/odoo19` install away, so none is left behind. See the [project capability contract](../odoo-environment/references/project-contract.md).
