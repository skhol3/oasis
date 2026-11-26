# Release gate: the agent field run

Before each release, the same field run is repeated from a fresh clone, with oasis driven the way an
agent drives it: no terminal, answers through `setup --plan --json` and `--answers`, and every command
taken from what oasis printed. It counts the human handoffs: each time the agent would have to ask the
user for a command to copy, a file to edit or a value to type. The target is 0 except genuine
decisions (a Tier B confirmation, which module or name). The release is blocked when the count grows
over the previous release.

## The run

In a scratch directory (`mktemp -d`), with a copy of the machine file (`XDG_CONFIG_HOME` pointing to the
copy) and a scratch install (`./install.sh --target <dir>/oasis`):

1. Clone a project into `<dir>/proj/code/<repo>`.
2. `oasis setup --plan --json`, answer every open question with its recommended answer, then
   `oasis setup --answers <file> --apply`.
3. Run the next steps setup printed: `oasis start-database`, `oasis doctor` (expect `doctor_failures=0`).
4. `oasis test-module --compact <module>` (expect `exit=0`, the disposable database dropped).
5. `oasis worktree-init <feature> <branch> --dry-run`, then the same with `--confirm <path>` (the one
   genuine decision: Tier B).
6. In the worktree: `oasis setup --plan --json`, answer what it asks, `--apply`, `oasis doctor`, and
   `oasis test-module --compact <module>`.
7. Remove the compose project (`docker compose -p <name> down -v`) and the scratch directory.

## Results

| Release | Project | Handoffs | Genuine | Notes |
|---|---|---|---|---|
| 0.15.0 | openalliance-odoo (Odoo 15.0) | about 7 | 2 | credentials typed, `.env`, PyPDF2 wheel, python-ldap and cryptography overrides, requirements-extra edit, prunable worktree |
| 0.16.0 | openalliance-odoo (Odoo 15.0) | 1 | 1 | the `worktree-init` confirmation; a first run found two more (a `docker compose` command naming the env file, a manual `[development]` edit), fixed by `start-database` and the `development` question before the release |
