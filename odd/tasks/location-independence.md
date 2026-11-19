# Location independence (v0.4.0)

One workspace file at the project root replaces per-checkout profiles, so checkouts and worktrees
work at any depth, nothing location-dependent is written into files, and the environment
contract is checked up front. Existing `.odoo19-agent.toml` profiles keep working.

## Specs

- S1. User: "tambien quiero empezar a considerar respecto a las cosas que nos hacen dependientes, por ejhemplo: directorios, configuracion, logs y environment. Como podemos enfrentar eso?"
- S2. Accepted principle 1 (one anchor): "Un ancla, y todo relativo a ella ... que oasis lo encuentre subiendo directorios, igual que git encuentra `.git` ... Las rutas se escriben relativas al archivo que las declara, no al checkout. Un checkout puede estar a cualquier profundidad. Los worktrees no necesitan copia del perfil."
- S3. User correction: "me parece bien pero el oasis-workspaces.toml estaria a nivel de proyecto, porque los entornos pueden varias por poryecto, en este caso la carpeta contenedora/raiz seria corpus-cafe". Name chosen: `oasis-workspace.toml`, one per project, at the project root (e.g. `projects/corpus-cafe/`), holding sources, environment, prefixes, config, data and logs. A checkout has its own file only for exceptions (e.g. `checkout_slug`).
- S4. Accepted principle 2 (generated, not hand-written): "Ninguna ruta absoluta debería vivir en un archivo: oasis pasa por línea de comandos todo lo que depende de la ubicación (`--addons-path`, `--data-dir`, `--http-port`) ... `lock.sha256` guarda rutas relativas a `requirements/`".
- S5. Accepted principle 3 (environment contract): "Un `odoo19 doctor` que verifique todo al principio, con mensajes claros: Python 3.12, git 2.31 o más nuevo, Docker Compose, `flock`, `/proc`; que el venv exista, que `odoo.conf` sea legible y que el puerto esté libre."
- S6. Accepted principle 4 (migration without breaking): "oasis sigue leyendo `.odoo19-agent.toml` por checkout como hasta ahora; el esquema nuevo es opcional; un comando tuyo, `/odoo19 migrate`, mostraría el plan y convertiría corpus-cafe".
- S7. Also in 0.4.0: "la línea de control en el resumen de tests (`log_lines=… errors=… warnings=…`)".

## Tasks

- T1 [S2 S3 S6] Workspace file discovery and layered config (workspace -> optional checkout overrides); legacy profile unchanged — pending
- T2 [S4] Location-dependent values on the command line (`--data-dir`); `lock.sha256` relative to requirements — pending
- T3 [S5] `odoo19 doctor` — pending
- T4 [S6] `odoo19 migrate` + user-run `/odoo19 migrate` (plan, confirm, write workspace file, keep profiles as backup) — pending
- T5 [S7] Control line in the test summary — pending
- T6 Release v0.4.0 — pending

## Log

- L1. User request: see S1. Proposal accepted with S3 correction ("si me parece bien" for the 0.4.0 scope and the four principles).
