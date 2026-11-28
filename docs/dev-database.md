# Fresh development database with role accounts

Use the global `create-database` command for a **new, explicitly authorized development or test database**: it is the one oasis command that creates a database (v0.20.0; named `init-dev-database` until v0.20.0, a name that is gone with no alias), the way Odoo's database manager form does, through the same Odoo function (`exp_create_database`: name, demo data, language, administrator, country). By default it initializes Odoo without demo data, configures the administrator (Odoo's default password `admin`, or the env file's `ODOO_ADMIN_PASSWORD`), installs one project module, and creates the project-declared role accounts. Pass `--with-demo` explicitly to use Odoo's native demo loader. The Odoo options come from the series table (`tools/odoo_versions.py`): without demo data `--without-demo` on 19.0 and `--without-demo=all` on 15.0; with it `--with-demo` on 19.0 and nothing on 15.0, which loads demo data by default and has no `--with-demo` option. Role accounts get their groups through the series' `res.users` field (`group_ids` on 19.0, `groups_id` on 15.0). The part that runs inside Odoo uses the project environment's Python (3.7 or later, such as the 3.8 or 3.9 of an Odoo 15 environment) and only its standard library: the configuration is read by oasis's own Python, which passes it the values it needs. `install-module`, `update-module`, `start`, and test commands do not provision these users. `install-module`, `update-module`, `odoo-shell`, `start` and `restart` work on existing databases only: a missing one exits 2 with `Database <name> does not exist; create it with: oasis --project <checkout> create-database --plan`, before Odoo starts (`odoo-bin -d <name>` would create a missing database by itself). The disposable and kept test databases of `test-module` and `verify-module` are theirs, as before ([Disposable test databases](disposable-test-databases.md)).

The language (`--lang <code>`, `en_US` without it) is one of the codes the Odoo source lists (`odoo/addons/base/data/res.lang.csv`, what the form lists; `en_US` alone when that file cannot be read, as Odoo does): Odoo loads it into the new database and gives it to the administrator. The country (`--country <code>`, none without it) is one of the Odoo source's countries (`odoo/addons/base/data/res_country_data.xml`; its codes are lowercase, `AR` is taken as `ar`): Odoo sets the company's country and currency, and the users' time zone when the country has only one. Odoo 15.0 and 19.0 take both the same way (`exp_create_database(..., lang, ..., country_code)`), so both apply on both series. Another code is refused before anything runs, exit 2: `ERROR: Unknown language <code>: Odoo <series> lists its languages in <file>; create-database --plan --json shows them. No database was created.` (`Unknown country <code>: ... lists its countries in <file> ...` for a country; `ERROR: Cannot read the countries of Odoo <series>: <file>. No database was created.` when that file cannot be read).

Declare non-secret accounts in the project's `oasis-workspace.toml`. A workspace `oasis setup` creates already has the table, with the administrator alone (the question `development`, recommended `add`; [Setup](setup.md#what-it-infers-and-what-it-asks)): `[development]` and `administrator_login = 'admin'`, so `create-database` runs without editing the file; `--answer development=none` leaves it out, and setup's next steps then name those two lines. Edit it, for example:

```toml
[development]
administrator_login = 'local_admin'

[[development.users]]
login = 'planner'
name = 'Development Planner'
groups = ['your_module.group_planner']
```

Replace the example group with an actual installed `res.groups` XML ID. Additional `[[development.users]]` entries declare other roles; omit them when only the administrator is needed. Every role account receives `base.group_user` plus its declared groups, limited to the initial company. The module must define its roles outside demo data. Logins must be unique and names/groups nonempty; unknown keys, including credentials, are rejected.

Run the full executable path with the actual module and a fresh database name under the project's `[tooling].dev_prefix` (a development database) or `[tooling].test_prefix` (a test database, created the same way; at most 56 bytes, as `[tooling].test_database`, so verify-module's `_update` sibling fits), from a terminal or not. Any other name exits 2 with `ERROR: Initialization requires a named development or test database.` Creating a database is the user's decision (v0.20.0: Tier B in the [agent contract](agent-contract.md)): the command creates it only with `--confirm` naming that database:

```bash
~/.agents/skills/oasis/oasis --project /absolute/project create-database your_module project_dev_manual --confirm project_dev_manual
```

Without `--confirm`, or with another name, it checks the configuration, then changes nothing, exits 2 and names the exact command:

```text
ERROR: create-database creates the development database project_dev_manual with its accounts and installs your_module, demo data: no (Tier B: it needs explicit confirmation); nothing changed. Run: oasis --project /absolute/project create-database your_module project_dev_manual --confirm project_dev_manual
```

The confirmation goes with the command into its Python scripts (v0.20.0): `tools/dev_users.py` creates a database only when its first two arguments are `--confirm <database>`, after the same name guards (prefix, checkout slug, letters, digits and underscores, 63 bytes, 56 for a test database, no trash or disposable run name), and refuses anything else with exit 2 naming the `create-database` command; `tools/dev_users_runtime.py` runs only with the payload `dev_users.py` sends it, which names the confirmed database (`ERROR: dev_users_runtime.py runs only under create-database (tools/dev_users.py), which confirms the database; nothing was created.`, exit 3). The Gentle Shell bash guard asks for a direct call of either script like for `create-database` ([Bash guard](bash-guard.md)).

`--dry-run` prints what it would create and changes nothing (exit 0):

```text
database: project_dev_manual
kind: dev
module: your_module
demo: no
language: en_US
country: none
dry run: nothing changed
```

## The plan of a new database

A database is created only when the user asks for one, and the user chooses what Odoo's database manager form asks: its name, its kind, its module, its demo data, its language and its country; oasis chooses none of them. `create-database --plan` lists them as questions, and `--json` prints them as one JSON object in the shape of [setup's plan](setup.md#questions-and-answers): an agent relays the open questions to the user and passes the answers back with `--answer <id>=<value>` (repeatable) or `--answers <file.json>` (one JSON object of ids and text answers):

| Id | Answer | Recommended |
| --- | --- | --- |
| `suffix` | the part of the name after the prefix (and the checkout slug): letters, digits and underscores | none |
| `kind` | `dev`, `test` or `both`: `<dev_prefix>[<slug>_]<suffix>`, `<test_prefix>[<slug>_]<suffix>` or both, each created the same way | none |
| `module` | one of the checkout's addon modules (the options it lists) | none |
| `demo` | `no` (without demo data) or `yes` (`--with-demo`) | `no`, still asked |
| `language` | one of the Odoo source's languages (the options it lists, by name, as the form does) | `en_US`, still asked |
| `country` | `none` or one of the Odoo source's countries (the options it lists; either case) | none |

```bash
~/.agents/skills/oasis/oasis --project /absolute/project create-database --plan --json
~/.agents/skills/oasis/oasis --project /absolute/project create-database --plan --json --answer suffix=shop --answer kind=both --answer module=your_module --answer demo=no --answer language=en_US --answer country=none
```

- The prefixes are the workspace's `[tooling].dev_prefix` and `test_prefix`, shown under `inferred` (with the checkout slug of a linked worktree): changing a prefix is a workspace setting ([Workspace file](workspace-file.md)), not an answer of the plan.
- The document holds `format` (`oasis-database-plan`), `version` (1), `command`, `checkout`, `complete`, `inferred` (`{"<key>": {"value", "origin"}}`), `questions` (each with `id`, `text`, `options` (`[{"value", "label"}]`), `recommended`, `flag`, `answer` and `origin`, as in setup's plan), `open` (the ids still unanswered), `databases` and `lines` (the text plan, which `--plan` without `--json` prints).
- With an open question the plan lists it (`open question <id>: <text>. Answer with <flag> (no recommended answer).`) and ends with `nothing changed: answer the open questions above (docs/dev-database.md#the-plan-of-a-new-database), then run the plan again` (exit 0).
- Once every question is answered, the plan runs `create-database --dry-run` for each database (dev first), so the database name guards decide (letters, digits and underscores, the checkout's namespace, at most 63 bytes, 56 for a test database, no trash or disposable-run suffix) and the `[development]` configuration is checked, prints it, then `run: <the exact --confirm command>` of each database (`--lang <code>` always, `--country <code>` unless `none`); `databases` lists `{"database", "kind", "command", "module", "demo", "language", "country"}` (`country` null for none). The user confirms each command; the plan itself never creates anything.
- An unknown id, an answer outside a question's options (a question with more than 10 options says `answer one of the <n> options of the question (create-database --plan --json lists them)` instead of listing them), an answer given twice, or a name the guards refuse is refused (exit 2) with the reason, and nothing changes.

## Listing this checkout's databases

```bash
~/.agents/skills/oasis/oasis --project /absolute/project list-databases
```

`list-databases` prints the databases of the current checkout, one name per line in name order, and nothing when there are none; it takes no arguments (exit 2 with its usage). It starts the database service like the other database commands. The menu's database choices (terminal and Gentle Shell panel) come from it. The namespace is the one `gc` uses (see [Disposable test databases](disposable-test-databases.md#cleaning-up-after-interrupted-runs)): in a checkout with a slug (a linked worktree, or a configured `checkout_slug`) only `<dev_prefix><slug>_<name>` and `<test_prefix><slug>_<name>`; in the main checkout (or a project outside git) every name under both prefixes except the namespaces of its existing linked worktrees, from `git worktree list`. The databases of a removed worktree are listed again by the checkout whose namespace holds them, usually the main checkout. PostgreSQL is asked only for the names under the two prefixes (their `_` escaped in `LIKE`); the slugs are compared outside SQL. [Trash](trash.md) entries are listed like any other name of the namespace, as before; a bare prefix (`<dev_prefix>` alone) is not a managed name and is not listed.

## Optional native demo loading

```bash
~/.agents/skills/oasis/oasis --project /absolute/project create-database --with-demo your_module project_dev_training --confirm project_dev_training
```

This opts in to native Odoo demo loading for base, installed dependencies, and the selected module's manifest `demo` files. It does not generate product records or import custom scenario scripts. Demo data is module-owned; the global tool contains no customer catalog. Without the flag, no demo is loaded and optional demo environment modules are not installed.

When a project's native demo XML needs optional modules not declared as addon dependencies, declare them explicitly in the same `[development]` table:

```toml
[development]
administrator_login = 'local_admin'
demo_modules = ['purchase_stock']
```

`demo_modules` is optional and defaults to an empty list. Entries must be unique Odoo technical module names (letters, digits and underscores). Only with `--with-demo`, the tool installs them sequentially in declared order, using the native loader, before installing the selected module. This does not change any addon's `depends`, and does not broaden the selected project module roots. Odoo itself resolves the optional modules through its configured addon paths; a missing module or installation failure retains the new database and reports failure. The declaration is not permission to install modules or operate services. Choose native demo user logins that do not collide with configured manual accounts: account collisions are refused without overwriting them.

`--with-demo` remains restricted to the fresh databases this command creates. It cannot load demo into an existing database, enable it for tests, reset credentials, or modify previously created project data. No project configuration is automatically edited by this command.

## Passwords: Odoo's default for the administrator, no password file

No password needs to be typed (v0.16.0: no oasis workflow requires reading, copying or typing one), and none is written to a file or printed (v0.20.0):

- The administrator (`administrator_login`) keeps Odoo's default password, `admin`, on every database the command creates. To use another one, set `ODOO_ADMIN_PASSWORD` in the env file (`[tooling].env_file`, the file of `ODOO_DB_USER` and `ODOO_DB_PASSWORD`; in the default layout `.oasis/config/.env`), read as `ODOO_DB_PASSWORD` is: the last assignment wins, a value in single quotes is literal, and an empty value keeps the default. A value written with compose interpolation (`$`) or a double-quoted escape (`\`) is refused before anything runs, exit 2: `ERROR: <env file> sets ODOO_ADMIN_PASSWORD with compose interpolation ($) or a double-quoted escape (\), which oasis does not read: write the value literally in single quotes.`; an env file oasis cannot read stops with `ERROR: Cannot read <env file>.` The administrator's password is never asked, also on a terminal.
- Each `[[development.users]]` account: on a terminal, the command first says `Enter at a password prompt generates one, which is not stored or shown.`, then asks `Password for <login>: ` with the echo off. Enter generates that password; a typed one is asked again (`Confirm password for <login>: `) and must match (`ERROR: Passwords must match; no database was created.`). Without a terminal (an agent, a script, CI) it is generated (`secrets.token_urlsafe(24)`). A generated password is not stored or shown anywhere, so nobody can log in with it: the administrator sets one in Odoo (Settings, Users) when that account is needed for a login. With the administrator alone, nothing is asked.

The output says what each account's password is, never its value:

```text
Development database initialized: acme_dev_manual
Accounts ready: 2
Account local_admin (administrator), password: Odoo's default
Account planner, password: generated, not stored or shown (local_admin can set one in Odoo)
```

With `ODOO_ADMIN_PASSWORD` set, the administrator's line is `Account local_admin (administrator), password: from /home/you/src/acme/.oasis/config/.env ODOO_ADMIN_PASSWORD`; a typed password is `password: typed on the terminal`.

An existing database is refused (`ERROR: Could not create a fresh development database; existing data was not modified.`, exit 1). When the database was created and a later step failed (`ERROR: Development setup failed; the new database was retained.`), or the outcome is unknown (`ERROR: Development setup stopped unexpectedly (exit <n>); <database> may exist: oasis list-databases shows it.`, an exit the initialization does not use, such as 1 for an error it did not catch: it says `4` when it created the database and a later step failed; or `ERROR: Interrupted while creating <database>; it may exist: oasis list-databases shows it.`, Ctrl-C once it started, exit 130), the output still prints the administrator's line, since its password is already set in a database that exists. If the env file's directory does not exist, the command stops before any prompt or service with `ERROR: <directory> does not exist: run oasis setup --apply; no database was created.`

Versions before 0.20.0 wrote the generated passwords to `<database>.logins` next to the env file. oasis no longer writes or reads that file, and since v0.21.0 says nothing of it: delete it yourself once you no longer need it.

## Credential handling and recovery

The command refuses unmanaged databases and existing databases; it never resets existing credentials. Passwords are not passed in arguments or environment variables, printed, written to a file or relayed in logs; the administrator's is Odoo's default or the env file's `ODOO_ADMIN_PASSWORD`. Do not put them in the workspace file, shell commands, or chat. A failed setup retains the new database for inspection and reports a sanitized error; no automatic deletion or retry occurs. Base initialization, module installation, and account creation are separate phases; role accounts are created in one transaction. Tests continue to create their own actors independently.

Before modifying an installed bundle without a source checkout, make and validate a complete backup. Recover only affected files after preserving unrelated later edits; a reinstall may overwrite local changes. Fresh database initialization is not permission to modify an existing database.
