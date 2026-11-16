# Per-checkout isolation (v0.2.0, v0.3.0)

oasis derives the Odoo runtime resources (databases, port, process) of each git checkout from
the directory it runs in, so linked worktrees used by Gentle Shell sessions and subagents never
step on each other. Gentle Shell keeps owning sessions, worktrees, ODD, review and memory.

## Specs

- S1. User: "como deberiamos empezar, cuando gentle-shell esta ocupando un puerto accede  otro o para los worktrees crea crea oras bases o para los test crea bses descartables, en ese sentido como debemos mejorar la herramienta para no pisar lo bueno de gentle-shell pero que si sea un buen complemento para gentle-shell?"
- S2. Accepted principle: "**El punto de unión es la carpeta.** oasis no pregunta en qué worktree está ni lleva su propio registro: deduce todo de la carpeta en la que corre."
- S3. Accepted principle 1: "**Identidad del checkout derivada de git.** El checkout principal se queda con sus nombres actuales y un worktree enlazado recibe un sufijo con el nombre de su carpeta (`07_1`), configurable en el perfil. Es determinístico y no guarda estado: la misma carpeta siempre da los mismos nombres."
- S4. Accepted principle 2: "**Bases de desarrollo persistentes por checkout.** Por ejemplo `cc_dev_07_1_<módulo>`. oasis nunca las borra solo."
- S5. Accepted principle 3: "**Bases de test descartables por corrida.** ... cada corrida usa una base propia (`cc_test_07_1_<módulo>_<id>`) que se borra al terminar ... hace falta un `odoo19 gc` que limpie las bases huérfanas que deja una corrida cortada. Solo actuaría sobre los prefijos administrados."
- S6. Accepted principle 4: "**Puerto con fallback, pero solo el HTTP.** Cada checkout tiene un puerto preferido derivado de su identidad. Si está ocupado, toma el siguiente libre y lo anota en `dev/runtime/`, para que `/odoo19` te diga dónde quedó. El servidor de PostgreSQL es uno solo y compartido."
- S7. Accepted principle 5: "**Cada checkout controla solo lo suyo.** `start` y `stop` manejan su propio proceso de Odoo, con un archivo de PID. Apagar el contenedor de DB compartido requiere que ningún otro checkout lo esté usando."
- S8. Accepted principle 6: "**Guards en todos los comandos que tocan una DB**, incluidos `update-module` y `odoo-shell`. Si la base no existe, el comando la rechaza en vez de crearla."
- S9. Accepted rule: "oasis solo *agrega*. El bloqueo de bash frena únicamente comandos de Odoo y las herramientas solo leen la carpeta actual. No hay worktrees, memoria ni review propios."
- S10. Accepted plan: steps 1-2 -> v0.2.0 (worktrees no longer step on the main checkout); steps 3-5 -> v0.3.0.

## Tasks

- [x] T1 [S2 S3 S9] Checkout identity (slug) from git, profile override, shown by `/odoo19` — worker — commit: ebdbcb4
- T2 [S3 S4 S8] Per-checkout DB names, test_database + slug in linked worktrees, 63-byte check, managed-prefix guard and missing-DB refusal for update-module, odoo-shell, install-module, start -d (Risk: items 2, 3) — worker + verify — commit: pending
- T3 [S5] Disposable test databases per run + `odoo19 gc` (Risk: item 1) — pending (v0.3.0)
- T4 [S6 S7] Per-checkout HTTP port with fallback, pidfile, own start/stop — pending (v0.3.0)
- T5 [S2] `worktree-init` — pending (v0.3.0)

## Log

- L1. User request: see S1.
- L2. User: "si me parece que si complementan sin pisar gentle-shell" (accepts S2-S10).
- L3. Evidence: corpus-cafe `.odoo19-agent.toml` is untracked (each checkout has its own), so a `[tooling].checkout_slug` override is per checkout. `git worktree list`: corpus-cafe (main, feature/AZ_daily_mass_production) and corpus-cafe-07.1 (linked, feature/AZ_mrp_cost_deviation_alert).
- L4. T1 field check (read-only): corpus-cafe -> CHECKOUT_KIND=main, slug empty; corpus-cafe-07.1 -> CHECKOUT_KIND=linked, slug 07_1. Suite 122 OK. Override also applies outside git (kind none). Needs git >= 2.31 (--path-format), else kind none.
- L5. T2 decisions derived from the accepted S3, S4 and S8 (no new user decision needed):
  - Names: the slug goes right after the managed prefix, as in S4/S5: dev default `<dev_prefix><slug>_<module>` (`cc_dev_07_1_coffee`), test default `<test_prefix><slug>_<module>`. A configured `test_database` becomes `<test_prefix><slug>_<rest>` (`cc_test_corpus_cafe` -> `cc_test_07_1_corpus_cafe`). Empty slug (main checkout) -> names unchanged.
  - Namespace guard: in a checkout with a slug, every managed name (explicit or default) must start with `<prefix><slug>_`, so a linked worktree cannot touch the main checkout's databases. The main checkout keeps the current managed-prefix rule.
  - Length: every database name the tools compute or accept is at most 63 UTF-8 bytes; names that get an `_update` sibling at most 56. Fail with a clear message before any database command.
  - S8 guards: update-module, odoo-shell, install-module (with and without demo) and `start -d` require a managed name; update-module and odoo-shell refuse a missing database (`does not exist; create it with install-module or create-database`) instead of creating it.
  - Contract change (AGENTS.md): listed under `### Changed` in CHANGELOG `[Unreleased]` and noted in the README.
