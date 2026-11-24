# Fresh development database with role accounts

Use the global `init-dev-database` command for a **new, explicitly authorized development database**. By default it initializes Odoo without demo data, configures the administrator, installs one project module, and creates the project-declared role accounts. Pass `--with-demo` explicitly to use Odoo's native demo loader. `create-database` (empty PostgreSQL database), `install-module`, `update-module`, `start`, and test commands do not provision these users.

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

From an interactive terminal, run the full executable path with the actual module and a fresh database name under the project's `[tooling].dev_prefix`:

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

## Credential entry and recovery

The command requests and confirms each password with terminal echo disabled. It refuses piped password entry, test/unmanaged databases, and existing databases; it never resets existing credentials. Passwords are not passed in arguments or environment variables, saved to files, or relayed in logs. Do not put them in the workspace file, shell commands, or chat. A failed setup retains the new database for inspection and reports a sanitized error; no automatic deletion or retry occurs. Base initialization, module installation, and account creation are separate phases; role accounts are created in one transaction. Tests continue to create their own actors independently.

Before modifying an installed bundle without a source checkout, make and validate a complete backup. Recover only affected files after preserving unrelated later edits; a reinstall may overwrite local changes. Fresh database initialization is not permission to modify an existing database.
