# Gentle Shell layer for oasis

A thin Pi package that layers Odoo 19 value on top of Gentle Shell without changing Gentle Shell itself.
The agent-agnostic core (`odoo19`, `tools/`, `odoo19-*` skills) stays usable by other agents.

## Specs

- S1. "quiero que esta herramineta sea un comlpemento de gentle-shell, osea que use como base pero que aporte para el desarrollo en odoo"
- S2. "tambien me gustaria que se use pueda usar  en otros agentes pero vamos como partida con genlte-shel"
- S3. "la idea es una capa, osea no me quiero meter con nada del nucleo gentle-shell, la idea es un complemento para reducir el uso de tokens en odoo"
- S4. Project detection (selected): "Al iniciar sesión detecta .odoo19-agent.toml y avisa al agente que use odoo19 (contexto en el prompt)"
- S5. Typed tools (selected): "check-environment, module-status, test-module, lint-module como tools con parámetros validados"
- S6. Dangerous bash blocking (selected): "En proyectos Odoo, bloquear odoo-bin/dropdb/psql directos y redirigir a los comandos con guard"
- S7. `/odoo19` command (selected): "Estado rápido del proyecto: perfil, módulos, DB, worktree"
- S8. Order (selected): "Adaptador primero" — "Esqueleto del paquete + primer slice; el aislamiento por checkout después, en el núcleo"

## Tasks

- [x] T1 [S1 S2 S3] Pi package skeleton in this repo, loadable by Gentle Shell, no core changes — inline — commit: 64ce76d
- [x] T2 [S3 S4] Project detection and compact prompt context — inline — commit: 64ce76d
- [x] T3 [S3 S5] Typed tools with compact output — inline — commit: 64ce76d
- [x] T4 [S6] Block direct odoo-bin/dropdb/psql in Odoo projects (Risk: item 2, own commit) — inline + verify — commit: d8b278f, 8dfe915
- T5 [S7] `/odoo19` status command — inline — commit: pending
- T6 [S1 S2] README install docs for Gentle Shell and other agents — inline — commit: pending

## Log

- L1. User request (2026-11-16): "repo agregado, el ssh para la cuenta de github esta activo (checalo), continuamos con nustras mejoreas del bundle global orientado ya a una herramienta, habia algo para poner que lo esoty haciendo con gentle shell ponlo"
- L2. "antes de seguir quiero que esta herramineta sea un comlpemento de gentle-shell, osea que use como base pero que aporte para el desarrollo en odoo"
- L3. "tambien me gustaria que se use pueda usar  en otros agentes pero vamos como partida con genlte-shel"
- L4. Install question answer: "la idea es una capa, osea no me quiero meter con nada del nucleo gentle-shell, la idea es un complemento para reducir el uso de tokens en odoo"; first slice: all four options; order: adapter first.
- L5. Evidence: Gentle Shell installs Pi packages (`gentle-shell install` forwards to `pi install` against `~/.gentle-shell/agent`); extensions are TS loaded by jiti; `pi.exec` runs without a shell; Pi and gentle-pi already scan `~/.agents/skills`. Review lenses are closed; no registration API for subagents.
- L6. 64ce76d (T1-T3) is one slice of 507 lines, past the ~400 guideline because skeleton, detection and tools form one capability; slice boundary recorded here. Load verified with a probe extension in `pi --mode rpc` that wrote the registered odoo19_* tool names (a plain get_state does not surface load errors).
- L7. T4 independent verify (S6 partially met on d8b278f): bypasses bash -lc/sh -ec, then/do/!, eval; false positive command -v. Fixed with regression tests in 8dfe915 (also watch, find -exec, source). Accepted as guard-rail limits: piping into a shell, here-strings into bash, scripts, ssh, su -c, python3 -m odoo.
- L8. /odoo19 shows configured DB names only: `list-databases` runs `compose up -d` (starts the DB service), which a quick status must not do.
