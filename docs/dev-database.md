# Fresh development database with role accounts

Use the global `init-dev-database` command for a **new, explicitly authorized development database**. By default it initializes Odoo without demo data, configures the administrator, installs one project module, and creates the project-declared role accounts. Pass `--with-demo` explicitly to use Odoo's native demo loader. The Odoo options come from the series table (`tools/odoo_versions.py`): without demo data `--without-demo` on 19.0 and `--without-demo=all` on 15.0; with it `--with-demo` on 19.0 and nothing on 15.0, which loads demo data by default and has no `--with-demo` option. Role accounts get their groups through the series' `res.users` field (`group_ids` on 19.0, `groups_id` on 15.0). The part that runs inside Odoo uses the project environment's Python (3.7 or later, such as the 3.8 or 3.9 of an Odoo 15 environment) and only its standard library: the configuration is read by oasis's own Python, which passes it the values it needs. `create-database` (empty PostgreSQL database), `install-module`, `update-module`, `start`, and test commands do not provision these users.

Declare non-secret accounts in the project's `oasis-workspace.toml`:

```toml
[development]
administrator_login = 'local_admin'

[[development.users]]
login = 'planner'
name = 'Development Planner'
groups = ['your_module.group_planner']
```

Replace the example group with an actual installed `res.groups` XML ID. Additional `[[development.users]]` entries declare other roles; omit them when only the administrator is needed. Every role account receives `base.group_user` plus its declared groups, limited to the initial company. The module must define its roles outside demo data. Logins must be unique and names/groups nonempty; unknown keys, including credentials, are rejected.

Run the full executable path with the actual module and a fresh database name under the project's `[tooling].dev_prefix`, from a terminal or not (an agent runs it too: Tier A in the [agent contract](agent-contract.md)):

```bash
~/.agents/skills/odoo19/oasis --project /absolute/project init-dev-database your_module project_dev_manual
```

## Listing this checkout's databases

```bash
~/.agents/skills/odoo19/oasis --project /absolute/project list-databases
```

`list-databases` prints the databases of the current checkout, one name per line in name order, and nothing when there are none; it takes no arguments (exit 2 with its usage). It starts the database service like the other database commands. The menu's database choices (terminal and Gentle Shell panel) come from it. The namespace is the one `gc` uses (see [Disposable test databases](disposable-test-databases.md#cleaning-up-after-interrupted-runs)): in a checkout with a slug (a linked worktree, or a configured `checkout_slug`) only `<dev_prefix><slug>_<name>` and `<test_prefix><slug>_<name>`; in the main checkout (or a project outside git) every name under both prefixes except the namespaces of its existing linked worktrees, from `git worktree list`. The databases of a removed worktree are listed again by the checkout whose namespace holds them, usually the main checkout. PostgreSQL is asked only for the names under the two prefixes (their `_` escaped in `LIKE`); the slugs are compared outside SQL. [Trash](trash.md) entries are listed like any other name of the namespace, as before; a bare prefix (`<dev_prefix>` alone) is not a managed name and is not listed.

## Optional native demo loading

```bash
~/.agents/skills/odoo19/oasis --project /absolute/project init-dev-database --with-demo your_module project_dev_training
```

This opts in to native Odoo demo loading for base, installed dependencies, and the selected module's manifest `demo` files. It does not generate product records or import custom scenario scripts. Demo data is module-owned; the global tool contains no customer catalog. Without the flag, no demo is loaded and optional demo environment modules are not installed.

When a project's native demo XML needs optional modules not declared as addon dependencies, declare them explicitly in the same `[development]` table:

```toml
[development]
administrator_login = 'local_admin'
demo_modules = ['purchase_stock']
```

`demo_modules` is optional and defaults to an empty list. Entries must be unique Odoo technical module names (letters, digits and underscores). Only with `--with-demo`, the tool installs them sequentially in declared order, using the native loader, before installing the selected module. This does not change any addon's `depends`, and does not broaden the selected project module roots. Odoo itself resolves the optional modules through its configured addon paths; a missing module or installation failure retains the new database and reports failure. The declaration is not permission to install modules or operate services. Choose native demo user logins that do not collide with configured manual accounts: account collisions are refused without overwriting them.

`--with-demo` remains restricted to fresh development databases. It cannot load demo into an existing database, enable it for tests, reset credentials, or modify previously created project data. No project configuration is automatically edited by this command.

## Passwords: generated, or typed only if you want your own

No password needs to be typed (v0.16.0: no oasis workflow requires reading, copying or typing one):

- Without a terminal (an agent, a script, CI), every account's password is generated (`secrets.token_urlsafe(24)`: 32 letters, digits, `-` and `_`).
- On a terminal, the command first says `Enter at a password prompt generates one into <file> (mode 0600).`, then asks `Password for <login>: ` for each account with the echo off. Enter generates that password; a typed one is asked again (`Confirm password for <login>: `) and must match (`ERROR: Passwords must match; no database was created.`). Typing is for a person who wants their own password (Tier C).

Generated passwords go to one file next to the env file (`[tooling].env_file`), named for the database: `<database>.logins`, for example `.oasis/config/acme_dev_manual.logins`, mode 0600. It holds two comment lines, then one `<login> <password>` line per generated account; typed passwords are never written to it, and with every password typed there is no file. The command prints only where it is and for which logins, never a password:

```text
Development database initialized: acme_dev_manual
Accounts ready: 2
Generated passwords: /home/you/src/acme/.oasis/config/acme_dev_manual.logins (mode 0600): local_admin, planner
```

The file is written once the database exists: the passwords are first written to a 0600 temporary file `.<database>.logins.<random>` in the same directory (removed again when it cannot be written: `ERROR: Cannot write the generated passwords next to <file>; no database was created.`), then renamed to `<database>.logins` when the database was created. An existing database is refused (`ERROR: Could not create a fresh development database; existing data was not modified.`) and keeps the file it had; a failed setup after the database was created keeps the new database and still writes the file, since the administrator's password is already set there. When the outcome is unknown, the temporary file is kept and named instead, never a password: `ERROR: Development setup stopped unexpectedly (exit <n>); <database> may exist: oasis list-databases shows it.` (an exit the initialization does not use, such as 1 for an error it did not catch: it says `4` when it created the database and a later step failed), or `ERROR: Interrupted while creating <database>; it may exist: oasis list-databases shows it.` (Ctrl-C once it started, exit 130), each followed by `Generated passwords: <temporary file> (mode 0600; rename it to <file> if <database> exists): <logins>`. When the rename itself fails, the database is initialized and the command exits 1 with `ERROR: Cannot rename <temporary file> to <file>; the generated passwords stay in <temporary file>.` and `Generated passwords: <temporary file> (mode 0600; it could not be renamed to <file>): <logins>`. If the env file's directory does not exist, the command stops before any prompt or service with `ERROR: <directory> does not exist: run oasis setup --apply; no database was created.` Read it to log in; never commit it (it sits next to the env file; in the default layout under `.oasis/`, which setup excludes from git). Dropping the database does not remove it; a new database of the same name replaces it.

## Credential handling and recovery

The command refuses test/unmanaged databases and existing databases; it never resets existing credentials. Passwords are not passed in arguments or environment variables, printed, or relayed in logs; generated ones are only in the `.logins` file. Do not put them in the workspace file, shell commands, or chat. A failed setup retains the new database for inspection and reports a sanitized error; no automatic deletion or retry occurs. Base initialization, module installation, and account creation are separate phases; role accounts are created in one transaction. Tests continue to create their own actors independently.

Before modifying an installed bundle without a source checkout, make and validate a complete backup. Recover only affected files after preserving unrelated later edits; a reinstall may overwrite local changes. Fresh database initialization is not permission to modify an existing database.
