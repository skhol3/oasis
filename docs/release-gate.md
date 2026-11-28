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
3. Run the next steps setup printed: `oasis setup-postgres`, `oasis doctor` (expect `doctor_failures=0`).
4. `oasis test-module --compact <module>` (expect `exit=0`, the disposable database dropped).
5. `oasis worktree-init <feature> <branch> --dry-run`, then the same with `--confirm <path>` (the one
   genuine decision: Tier B).
6. In the worktree: `oasis setup --plan --json`, answer what it asks, `--apply`, `oasis doctor`, and
   `oasis test-module --compact <module>`.
7. Recipes (since 0.18.0; per series since 0.19.0), on every supported series' checkout:
   - `python3 <install>/tools/recipe_module.py <series> <checkout>` builds the `library` module from the
     recipes of that series (expect `ok`), then `oasis test-module --compact library` (expect `exit=0`,
     the tour run, no `skipped` test).
   - The evals of [recipe-evals.md](recipe-evals.md): a fresh agent does each task with only what oasis
     shows, then `python3 <install>/tools/recipe_evals.py <series> <module>` (expect `hits=0`) and
     `oasis test-module --compact <module>` (expect `exit=0`).
   - When a series is added: a fresh agent also builds the module by following the recipes by hand.
   Each point where a recipe was wrong or missing goes into its source in `recipes/` before the release
   and is named in the row's Notes, with the evals result per series.
8. Daily commands (since 0.20.0), on every supported series' checkout, against its real Odoo and
   PostgreSQL:
   - `oasis create-database --plan --json`, answer it without demo data, run its dry run, then the
     same with `--confirm <database>` (a genuine decision: Tier B); again with demo data on a second
     database.
   - `oasis start --detach -d <database> --dev <features>` on the dev database, with dev features of that
     series (15.0 and 19.0 offer different ones: `tools/odoo_versions.py`), then `oasis restart` (expect
     the port and the database kept) and `oasis stop`.
   - `oasis update-module <module> <database>` on the dev database (expect exit 0).
   - `oasis odoo-shell <database>` with one command piped in (for example
     `print(env['res.users'].search_count([]))`; expect its output back and exit 0).
   Record per series each command's exit and what it proved (the database created with or without demo
   data, the dev features in the server's command line, the kept port and database, the updated module,
   the shell output); the row's Notes name them.
9. Remove the compose project (`docker compose -p <name> down -v`) and the scratch directory.

## Results

| Release | Project | Handoffs | Genuine | Notes |
|---|---|---|---|---|
| 0.15.0 | openalliance-odoo (Odoo 15.0) | about 7 | 2 | credentials typed, `.env`, PyPDF2 wheel, python-ldap and cryptography overrides, requirements-extra edit, prunable worktree |
| 0.16.0 | openalliance-odoo (Odoo 15.0) | 1 | 1 | the `worktree-init` confirmation; a first run found two more (a `docker compose` command naming the env file, a manual `[development]` edit), fixed by `start-database` and the `development` question before the release |
| 0.17.0 | openalliance-odoo (Odoo 15.0) | 1 | 1 | the `worktree-init` confirmation; run with the `oasis` install directory and the `odoo-*` skills |
| 0.18.0 | openalliance-odoo (Odoo 15.0), corpus-cafe (Odoo 19.0) | 1 | 1 | the `worktree-init` Tier B confirmation was not given, steps 5-6 skipped; step 7 builds the `library` module from the recipes: 19.0 as written, 15.0 from the *Changed in* tables after 3 fixes a first run found (`sequence` on res.groups is 19.0 only, Owl 1 templates need `owl="1"`, a 15.0 tour has no `url` and waits for `.o_form_readonly`); that run also needed `websocket-client` by hand (HttpCase skips tours without it), now in setup's `dev.in`; `test-module` exit 0 with 7 tests and the tour on both |
| 0.19.0 | openalliance-odoo (Odoo 15.0), corpus-cafe (Odoo 19.0) | 1 | 1 | the `worktree-init` Tier B confirmation was not given, steps 5-6 skipped; step 7 with `recipe_module.py` per series: `library` built from the 15.0 and the 19.0 recipes, `test-module` exit 0 (8 tests with the tour) on both; evals ([recipe-evals.md](recipe-evals.md)): 8 of 8 tasks passed (4 per series, `hits=0`, `test-module` exit 0), every agent opened only its own series' recipes; their gaps went into the recipes (archived records, extending modules, record rules that widen access, field selectors); 15.0 `oa_base` runs 0 tests |
| 0.20.0 | openalliance-odoo (Odoo 15.0), corpus-cafe (Odoo 19.0) | 1 | 1 | the user's Tier B confirmations: `worktree-init` not given (steps 5-6 skipped) and four `create-database` (the session loaded Gentle Shell oasis 0.19.0, whose guard predates the rule: the first ran without asking, the user approved the other three in the chat; the 0.20.0 dialog is checked once the package moves); `setup` asked the environment and its Python on both series; doctor 0 on 19.0 (`code_python=3.12 files=221`), 1 on 15.0 from a misplaced addon's `match` (the project's); step 7: `library` from the 15.0 and 19.0 recipes, 8 tests with the tour on both, no recipe fix, recipe evals not rerun (recipes unchanged since 0.19.0 but one command name); step 8: databases with and without demo checked through `odoo-shell`, `start --dev`, `restart`, `stop`, `update-module`, `odoo-shell` exit 0 on both, missing databases refused naming the plan |
