# oasis — Odoo Agent Skills & Infrastructure Scripts

## Project

- This repository is the source of the global Odoo agent bundle: the `oasis` entry point
  (with its `odoo19` alias), its guarded `tools/`, the `odoo-<topic>` skills (a reference per
  series), the Gentle Shell layer (`pi/`), project wrapper templates and docs.
- Agents never read this repository directly. `install.sh` copies the committed HEAD to
  `~/.agents/skills/odoo19`; uncommitted edits are never installed.
- Code, comments, commit messages and documentation are in English.

## Boundaries

- Editable: everything in this repository.
- Read-only unless the user explicitly authorizes the exact path: `~/.agents/skills/odoo19`
  (install target, changed only through `install.sh`), Odoo projects that use the bundle,
  Odoo source trees, environments and databases.
- Never print or copy credentials: project `.env` files and `odoo.conf` passwords stay where they are.
- Never unpack historical archives under a skill discovery directory.

## Compatibility

Several Odoo projects depend on the installed bundle. Treat as a contract: both entry point
names, `oasis` and its alias `odoo19` (same dispatcher, identical command names, options,
exit codes and output), the Gentle Shell names (`oasis_*` tools with their inactive
`odoo19_*` aliases, `/oasis` with its alias `/odoo19`), the `oasis-workspace.toml` keys
(with `oasis-checkout.toml`), database prefix guards and the skill names. Changing or removing any of them needs an
explicit decision and a note in the README.

## Verification

Run before every commit:

```bash
python3 -B -m unittest discover -s tests
```

Tests use synthetic fixtures; they must never touch a real project, database or the install
target. Install only after the suite passes and the change is committed:

```bash
./install.sh            # or ./install.sh --target /absolute/scratch/odoo19 to try it
```

## Releases

Versions follow Semantic Versioning and are tagged on `main` only:

0. Run the agent field run of [docs/release-gate.md](docs/release-gate.md) and add its row: the
   release is blocked when the human handoffs grow over the previous release.
1. In the release pull request, move the `[Unreleased]` entries of `CHANGELOG.md` under the
   new version and set the same `version` in `package.json` (patch: fixes; minor: additions,
   or contract changes while `0.x`; major: contract changes after `1.0.0`). Commit as
   `chore(release): vX.Y.Z`. Update the compare links at the bottom of the changelog:
   `[Unreleased]` compares `vX.Y.Z...HEAD` and the new `[X.Y.Z]` points to its release.
2. Merge the pull request to `main`.
3. On the updated `main`, run the test suite, then tag: `git tag -a vX.Y.Z -m "oasis vX.Y.Z"` and push the tag.
4. Publish the GitHub release with the changelog section as notes.
5. Move the Gentle Shell package to the new tag: `gentle-shell remove git:github.com/skhol3/oasis@<old tag>`,
   then `gentle-shell install git:github.com/skhol3/oasis@vX.Y.Z` and `/reload` open sessions. Sessions load
   that fixed copy, so work in this checkout never changes what they run.

`install.sh` records the installed `version` and commit in `.oasis-install.json`.
