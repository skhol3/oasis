# Migrating to the workspace file

`oasis migrate` converts the `.odoo19-agent.toml` of every checkout of a repository into one `oasis-workspace.toml`, keeping every profile as a backup. Run it yourself, from any checkout that has a profile, in Gentle Shell or in a terminal:

```text
/oasis migrate
```

```bash
~/.agents/skills/odoo19/oasis --project /absolute/checkout migrate [--workspace <dir>] [--apply | --plan]
```

## How it works

- Without `--apply` it prints the plan and changes nothing; the plan ends with `dry run: nothing changed; run with --apply to migrate`. `--plan` asks for that plan explicitly and can never apply: with `--apply` it is a usage error (exit 2). It is the one form an agent may run (see the [bash guard](bash-guard.md)). `/oasis migrate` (or `/odoo19 migrate`) shows the plan and runs `migrate --apply` after confirmation. Agents cannot run it: the bash guard blocks it, the dry run included.
- Checkouts: every worktree that `git worktree list` reports (outside git, the checkout alone). A missing worktree stops it with `Worktree <path> is missing; restore it or run git worktree prune.`
- Workspace directory: by default the deepest directory above every checkout and the profile's `odoo.conf` (`<project>` in the [workspace layout](workspace-file.md)). `--workspace <dir>` names another one; it must be an absolute existing directory above every checkout (`Refusing --workspace <dir>: it is not above every checkout (<checkouts>).`). An existing `oasis-workspace.toml` there is never replaced (`<file> already exists.`); a directory the trust rule would refuse, and a nearer `oasis-workspace.toml` or `.odoo19-agent.toml` between a checkout and that directory, are refused too.
- Agreement: every profile must give the same `[tooling]` and `[development]` values, paths resolved from its checkout, except `checkout_slug`. Otherwise it stops with `Cannot migrate: the profiles of the checkouts disagree on <section>.<key>, ...` (keys only, never values).

## The plan

- The plan, in order:
  - `write <dir>/oasis-workspace.toml` (mode 0600; its content follows, indented): `workspace_version = 1`, `odoo_version` from the profile's `version`, `[tooling]` without `version`, `python_version` and `checkout_slug`, every path relative to `<dir>` (`addons_paths` stays relative to each checkout), and `[development]` as it is.
  - `write <checkout>/oasis-checkout.toml` (mode 0600) with `[tooling].checkout_slug`, for each checkout whose profile sets one.
  - `back up <odoo.conf> as odoo.conf.bak-<stamp>` (a 0600 copy) and `remove addons_path and data_dir from <odoo.conf>` (or just one of them): only those lines of `[options]`, every other line kept. A `data_dir` moves to `[tooling].data_dir` (`; data_dir moves to [tooling].data_dir`; it must be an absolute path) unless the profile sets one. oasis then passes both on the command line (see [Path-free odoo.conf](path-free-odoo-conf.md)). The content of `odoo.conf` is never printed.
  - `rewrite <requirements>/lock.sha256: <n> entries relative to its directory, hashes unchanged` for a legacy lock that matches from the checkout; otherwise `keep <lock>: <reason>` (already relative, or not matching: regenerate it).
  - `rename <checkout>/.odoo19-agent.toml to .odoo19-agent.toml.bak-<stamp>` for every checkout, since a profile wins over the workspace file. `<stamp>` is the UTC time, `YYYYMMDDTHHMMSSZ`.
  - `not migrated: <sections> (kept in the profile backups)` for advisory sections such as `[odoo]`, `[environment]` or `[commands]`.

## Verification and exit status

- Verification: with `--apply`, every checkout must then load the same `tools/config.py` values as before, except `WORKSPACE_ROOT`, `ENVIRONMENT_NAME` and `DATA_DIR`, find the new workspace file, and get the same addons path and data directory on its Odoo command line; a rewritten `lock.sha256` must match from its directory. It then prints `verified: <n> checkouts load the same configuration from <file>`. Otherwise every change is undone and it exits 1 with `ERROR: Verification failed; every change was undone:` and one `  <checkout>: <names>` line per checkout that differs (for example `addons_path` when `odoo.conf` lists a directory that no `addons_paths` root gives, or lists them in another order than `<enterprise>,<addon roots>,<community>/addons`).
- Exit status: 0 for the plan and for a verified migration, 2 for a refusal (nothing changed), 1 when the migration was undone. Run again afterwards, it prints `nothing to migrate: <checkout> has no .odoo19-agent.toml` (exit 0). To go back by hand, rename the backups to their original names and delete the files it wrote.
