# Documentation restructure (v0.10.1)

The README becomes a landing page; the detail moves to one file per topic under docs/. No
command, option, output or test behaviour changes.

## Specs

- S1. User (2026-11-23): "ahora hay que hacer cambios respecto a la docuemntacion - un solo readme
  hacer enorme la documentacions - investiga como podemos mejorar esa presentacion - checa como
  muestra la docuemntacion gentle-shell en su repo para ver que podemos tomar o que descartar,
  claro para solo para presentar nuestra documentacion".
- S2. User decisions (2026-11-24): README "Landing al estilo Gentle Shell"; images "Solo diagramas
  de flujo (recomendado)"; language "Inglés (recomendado)".
- S3. README.md as a landing page: what oasis is (an Odoo development harness: CLI, skills and a
  thin Gentle Shell layer; not a seventh skill), install or update (install.sh and the Gentle
  Shell package from a release tag), a five-minute start, one short paragraph per feature with a
  "Docs →" link (Gentle Shell layer and agent tools, checkouts and worktrees, tests and
  databases, static inspection, action menu, environment and workspace file), and a final
  "Documentation | Purpose" table. Taken from Gentle Shell: the destination table and the
  "Docs →" links. Discarded: badges, star charts, sponsor, video, community and author sections,
  and any catch-all reference file.
- S4. docs/ holds one topic per file with one H1 and relative links that work inside the
  installed bundle (no links to files install.sh does not install, such as AGENTS.md or odd/).
  docs/README.md is the index by reader (new user, daily user, agent and skill author,
  contributor). Every current README section lands in exactly one file; nothing is dropped.
  The orphan docs/odoo19-chromium-socket-path-too-long.md is linked from troubleshooting.
- S5. Diagrams only where there is a flow: what the agent bash guard blocks and where; how
  checkouts and worktrees get their databases, ports and logs; the life of a test database
  (disposable, reused, configured). Mermaid in the Markdown (renders on GitHub, stays text).
- S6. The "Contract change in …" notes move to CHANGELOG.md (under the release that made each
  change) or to the topic file, not lost.
- S7. Tests that pin README text keep pinning the same text where it now lives
  (test_module_info, test_migrate, test_doctor, test_global_cli, test_bundle); the link check
  covers README.md and docs/*.md, each link resolved from its own file.

## Tasks

- T1 [S3-S7] README landing + docs/ split + diagrams + tests — worker — commit: pending
- T2 Release v0.10.1 — inline — commit: pending

## Log

- L1. Research (explore task mwu1ba1t-d-fipu, memory oasis/docs-restructure): README 630 lines,
  17 H2 sections; Gentle Shell README as landing plus ~55 topic docs; proposed file list:
  install, gentle-shell-layer, subagents, project-setup, checking-environment, workspace-file,
  migrating, static-inspection, dev-database, testing, checkouts-and-worktrees, action-menu,
  servers-and-ports, troubleshooting, verification, docs/README.md index.
- L2. After this: the operations audit (user, 2026-11-24): "luego de la documentacion hacemos
  auditoria para ver que falta respecto a comandos para levantar, actualizar, elegir puerto,
  levantar con test y demas".
