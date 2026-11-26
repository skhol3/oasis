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

Before 0.17.0 the install directory was `~/.agents/skills/odoo19`, with an `odoo19` alias of the entry
point. Installing into the default target moves that directory to the backups too
(`previous odoo19 install removed from <dir>; kept in <backup>`), so its `odoo19-*` skills are no longer
discovered. It does so only for an oasis install, a directory holding `.oasis-install.json`; a symlink, a
file or any other directory there is left as it is, with
`install.sh: warning: <dir> is not an oasis install (no .oasis-install.json); not removed`. With `--target`
it is never touched. Then:

- Run `~/.agents/skills/oasis/oasis` (there is no `odoo19` command any more), and in Gentle Shell
  `/oasis` and the `oasis_*` tools (`/odoo19` and the `odoo19_*` aliases are gone; `/oasis setup`
  updates an overlay that still names them).
- Project wrappers copied into a project's `dev/scripts/` from an earlier version call
  `~/.agents/skills/odoo19/tools`. `oasis doctor` reports them as `FAIL project_wrappers=old_install_dir`;
  its fix line lists them: replace `.agents/skills/odoo19/` with `.agents/skills/oasis/` in each (or copy
  them again from `~/.agents/skills/oasis/project-wrappers/`).
- Only the `OASIS_*` variables are read: `ODOO19_PROJECT_ROOT`, `ODOO19_ENTRYPOINT`, `ODOO19_TOOLS_DIR` and
  `ODOO19_COMPOSE_LOCK_TIMEOUT` are ignored, and neither the entry point nor the wrapper templates set them.
  A script that sets one needs the `OASIS_*` name.
- A workspace without `[tooling].logs` keeps its logs in `logs` next to `oasis-workspace.toml` (`logs/<x.y>`
  with `workspace_version = 2`), no longer in each checkout's `dev/logs/odoo19/`; runs already there stay where
  they are and `oasis_test_summary` no longer reads them.

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

The `install.sh` target contains the six `odoo-<topic>` skill directories, `tools/`, `project-wrappers/`, `tests/`, `docs/`, the `oasis` entry point, the Gentle Shell layer (`package.json` and `pi/`), and the [README](../README.md). Restart the agent session or use `/reload` where supported, then check that exactly six skills are discovered. The skill entrypoints are [backend](../odoo-backend/SKILL.md), [security](../odoo-security/SKILL.md), [views/frontend](../odoo-views-frontend/SKILL.md), [testing](../odoo-testing/SKILL.md), [environment](../odoo-environment/SKILL.md), and [module lifecycle](../odoo-module-lifecycle/SKILL.md). Each SKILL.md is common to every series and sends the agent to its `references/15.0.md` or `references/19.0.md`, the series `oasis doctor` prints (`series=`, else `odoo_release=`). Since 0.17.0 the skills are named `odoo-<topic>`; the `odoo19-*` skills of earlier versions are gone: installing replaces the whole target and moves a previous `~/.agents/skills/odoo19` install away, so none is left behind. See the [project capability contract](../odoo-environment/references/project-contract.md).
