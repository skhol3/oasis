// Gentle Shell (Pi) layer for the Odoo bundle. It wraps the agent-agnostic
// `oasis` entry point shipped in this repository; it changes nothing in Pi or
// Gentle Shell and keeps every guard inside the core tools. The pre-0.4.0 names stay as
// aliases: `/odoo19` and the inactive odoo19_* tools.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { fileURLToPath } from "node:url";
import {
  parseCommand, SUBCOMMAND_SUMMARY, type SubcommandName, subcommandCompletions, USAGE,
} from "../lib/commands.ts";
import { withHeartbeat } from "../lib/heartbeat.ts";
import { blockedProgram, blockReason, MIGRATE, WORKTREE_INIT } from "../lib/bash-guard.ts";
import { findModules, formatModules, loadModules, DEFAULT_LIMIT } from "../lib/modules.ts";
import { findWorkspaceFile, projectContext, projectRootResolver } from "../lib/project.ts";
import { formatStatus, listModules, parseAssignments, parseGit, parseServer, type StatusInput } from "../lib/status.ts";
import { aliasOf, nextActiveTools, OASIS_TOOLS } from "../lib/activation.ts";
import { configHome, installOverlay, overlayState, overlayTarget } from "../lib/setup.ts";
import {
  formatBackgroundRun, formatPlain, formatTestRun, formatUpdateRun, testModuleArgs, updateModuleArgs, viewInfoArgs,
} from "../lib/tools.ts";

const OASIS = fileURLToPath(new URL("../../oasis", import.meta.url));
const CONFIG_PY = fileURLToPath(new URL("../../tools/config.py", import.meta.url));
const RUNTIME_STATE_PY = fileURLToPath(new URL("../../tools/runtime_state.py", import.meta.url));
const OVERLAY_TEMPLATE = fileURLToPath(new URL("../agent-overlays/oasis.json", import.meta.url));
const STATUS_TIMEOUT_MS = 15000;
const MAX_LINES = 60;
// model-info output is already compact; a larger cap keeps --methods/--all-fields useful.
const MODEL_INFO_MAX_LINES = 200;
const TEST_TIMEOUT_MS = 60 * 60 * 1000;
const HEARTBEAT_MS = 15 * 1000;
const TOOL_TIMEOUT_MS = 10 * 60 * 1000;
// doctor's probes (git, docker compose, the environment's Python) each stop after 20 s.
const DOCTOR_TIMEOUT_MS = 2 * 60 * 1000;

type Result = { content: { type: "text"; text: string }[]; details: Record<string, unknown> };
type ToolDefinition = Parameters<ExtensionAPI["registerTool"]>[0];

function text(body: string, details: Record<string, unknown> = {}): Result {
  return { content: [{ type: "text", text: body }], details };
}

function readLog(path: string): string {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return "";
  }
}

function notProject(cwd: string): string {
  return `no .odoo19-agent.toml or oasis-workspace.toml at or above ${cwd}`;
}

export default function oasisLayer(pi: ExtensionAPI) {
  async function gitTopLevel(start: string): Promise<string | null> {
    try {
      const result = await pi.exec("git", ["-C", start, "rev-parse", "--show-toplevel"], {
        cwd: start, timeout: STATUS_TIMEOUT_MS,
      });
      return (result.code === 0 && result.stdout.trim()) || null;
    } catch {
      return null;
    }
  }

  // The checkout root of cwd (lib/project.ts); git runs only for a directory under a workspace
  // file. A found top level is kept; a failed lookup is retried on the next call.
  const projectRoot = projectRootResolver(gitTopLevel);

  async function requireRoot(cwd: string): Promise<string> {
    const root = await projectRoot(cwd);
    if (!root) throw new Error(`Not an Odoo project: ${notProject(cwd)}.`);
    return root;
  }

  async function run(root: string, args: string[], signal: AbortSignal | undefined, timeout: number) {
    return pi.exec("python3", ["-B", OASIS, "--project", root, ...args], { cwd: root, signal, timeout });
  }

  async function plain(
    cwd: string, args: string[], signal: AbortSignal | undefined, maxLines = MAX_LINES,
  ): Promise<Result> {
    const root = await requireRoot(cwd);
    const result = await run(root, args, signal, TOOL_TIMEOUT_MS);
    return text(formatPlain(result, maxLines), { exit: result.code });
  }

  // Resolved profile from tools/config.py (read-only): values, or the error it reported.
  async function profileConfig(root: string): Promise<{ config?: Record<string, string>; error?: string }> {
    const config = await pi.exec("python3", ["-B", CONFIG_PY, root], { cwd: root, timeout: STATUS_TIMEOUT_MS });
    if (config.code === 0) return { config: parseAssignments(config.stdout) };
    return { error: config.stderr.trim() || `config.py exited with ${config.code}` };
  }

  // The project's Odoo series (ODOO_VERSION of tools/config.py), read once per root; a failed
  // read is retried on the next call.
  const versions = new Map<string, string>();
  async function projectVersion(root: string): Promise<string | undefined> {
    const known = versions.get(root);
    if (known) return known;
    try {
      const version = (await profileConfig(root)).config?.ODOO_VERSION;
      if (version) versions.set(root, version);
      return version;
    } catch {
      return undefined;
    }
  }

  function addonRoots(config: Record<string, string>): string[] {
    return (config.ADDON_ROOTS ?? "").split("\n").filter(Boolean);
  }

  // This checkout's server record (pid, port) from tools/runtime_state.py; no service or database access.
  async function serverState(root: string): Promise<Pick<StatusInput, "server" | "serverError">> {
    const shown = await pi.exec("python3", ["-I", "-B", RUNTIME_STATE_PY, "show", root], {
      cwd: root, timeout: STATUS_TIMEOUT_MS,
    });
    if (shown.code === 0) return { server: parseServer(shown.stdout) };
    return { serverError: shown.stderr.trim() || `runtime_state.py exited with ${shown.code}` };
  }

  // Read-only status: the profile, addon roots, git state and this checkout's server record.
  // Never starts services or queries databases.
  async function projectStatus(root: string): Promise<StatusInput> {
    const status: StatusInput = { root, modules: [], git: null };
    const { config, error } = await profileConfig(root);
    if (config) {
      status.config = config;
      status.modules = addonRoots(config).map((addons) => ({ root: addons, names: listModules(addons) }));
    } else {
      status.configError = error;
    }
    const options = { cwd: root, timeout: STATUS_TIMEOUT_MS };
    const revParse = await pi.exec(
      "git", ["-C", root, "rev-parse", "--abbrev-ref", "HEAD", "--git-dir", "--git-common-dir"], options,
    );
    if (revParse.code === 0) {
      const porcelain = await pi.exec("git", ["-C", root, "status", "--porcelain"], options);
      if (porcelain.code === 0) status.git = parseGit(root, revParse.stdout, porcelain.stdout);
    }
    Object.assign(status, await serverState(root));
    return status;
  }

  function currentOverlayTarget(): string {
    return overlayTarget(configHome(process.env, homedir()));
  }

  // User-run only (no tool registers it): install or update the subagent overlay after confirmation.
  async function setup(ctx: { ui: { notify: (message: string, level?: "info" | "warning" | "error") => void;
    confirm: (title: string, message: string) => Promise<boolean> } }): Promise<void> {
    try {
      const target = currentOverlayTarget();
      const state = overlayState(OVERLAY_TEMPLATE, target);
      if (state === "current") {
        ctx.ui.notify(`oasis setup: subagent overlay is up to date (${target})`, "info");
        return;
      }
      const verb = state === "missing" ? "Create" : "Update";
      const question = `${verb} ${target} so gentle-ai-worker and gentle-ai-verify get the oasis tools?`;
      if (!(await ctx.ui.confirm("oasis setup", question))) {
        ctx.ui.notify("oasis setup: nothing changed.", "info");
        return;
      }
      const result = installOverlay(OVERLAY_TEMPLATE, target);
      if (result.state === "unchanged") {
        ctx.ui.notify(`oasis setup: subagent overlay is up to date (${target})`, "info");
        return;
      }
      ctx.ui.notify(
        `oasis setup: subagent overlay ${result.state} at ${target}. ` +
          "Start a new session or /reload for subagents to use it.",
        "info",
      );
    } catch (error) {
      ctx.ui.notify(`oasis setup failed: ${error instanceof Error ? error.message : String(error)}`, "error");
    }
  }

  // User-run only (agents are blocked from worktree-init): show the dry-run plan, then create it on yes.
  async function worktree(ctx: { cwd: string; ui: { notify: (message: string, level?: "info" | "warning" | "error") => void;
    confirm: (title: string, message: string) => Promise<boolean> } }, feature: string, branch: string): Promise<void> {
    const root = await projectRoot(ctx.cwd);
    if (!root) {
      ctx.ui.notify(`Not an Odoo project: ${notProject(ctx.cwd)}`, "warning");
      return;
    }
    const args = ["worktree-init", feature, branch];
    try {
      const plan = await run(root, [...args, "--dry-run"], undefined, TOOL_TIMEOUT_MS);
      if (plan.code !== 0) {
        ctx.ui.notify(`oasis worktree: ${plan.stderr.trim() || `exit ${plan.code}`}`, "error");
        return;
      }
      const steps = plan.stdout.trim().split("\n").filter((line) => line !== "dry run: nothing changed");
      if (!(await ctx.ui.confirm("oasis worktree", `${steps.join("\n")}\n\nCreate this worktree?`))) {
        ctx.ui.notify("oasis worktree: nothing changed.", "info");
        return;
      }
      const result = await run(root, args, undefined, TOOL_TIMEOUT_MS);
      const output = [result.stdout.trim(), result.stderr.trim()].filter(Boolean).join("\n");
      ctx.ui.notify(`oasis worktree:\n${output || `exit ${result.code}`}`, result.code === 0 ? "info" : "error");
    } catch (error) {
      ctx.ui.notify(`oasis worktree failed: ${error instanceof Error ? error.message : String(error)}`, "error");
    }
  }

  // User-run only (agents are blocked from migrate): show the dry-run plan, then `migrate --apply` on yes.
  async function migrate(ctx: { cwd: string; ui: { notify: (message: string, level?: "info" | "warning" | "error") => void;
    confirm: (title: string, message: string) => Promise<boolean> } }): Promise<void> {
    const root = await projectRoot(ctx.cwd);
    if (!root) {
      ctx.ui.notify(`Not an Odoo project: ${notProject(ctx.cwd)}`, "warning");
      return;
    }
    try {
      const plan = await run(root, ["migrate"], undefined, TOOL_TIMEOUT_MS);
      if (plan.code !== 0) {
        ctx.ui.notify(`oasis migrate: ${plan.stderr.trim() || `exit ${plan.code}`}`, "error");
        return;
      }
      const output = plan.stdout.trim();
      if (output.startsWith("nothing to migrate")) {
        ctx.ui.notify(`oasis migrate: ${output}`, "info");
        return;
      }
      const steps = output.split("\n").filter((line) => !line.startsWith("dry run: "));
      if (!(await ctx.ui.confirm("oasis migrate", `${steps.join("\n")}\n\nMigrate to this workspace file?`))) {
        ctx.ui.notify("oasis migrate: nothing changed.", "info");
        return;
      }
      const result = await run(root, ["migrate", "--apply"], undefined, TOOL_TIMEOUT_MS);
      const shown = [result.stdout.trim(), result.stderr.trim()].filter(Boolean).join("\n");
      ctx.ui.notify(`oasis migrate:\n${shown || `exit ${result.code}`}`, result.code === 0 ? "info" : "error");
    } catch (error) {
      ctx.ui.notify(`oasis migrate failed: ${error instanceof Error ? error.message : String(error)}`, "error");
    }
  }

  // User-run only (no agent tool): `oasis doctor`, read-only, shown like the status.
  async function doctor(ctx: { cwd: string; ui: { notify: (message: string, level?: "info" | "warning" | "error") => void } }):
    Promise<void> {
    const root = await projectRoot(ctx.cwd);
    if (!root) {
      ctx.ui.notify(`Not an Odoo project: ${notProject(ctx.cwd)}`, "warning");
      return;
    }
    try {
      const result = await run(root, ["doctor"], undefined, DOCTOR_TIMEOUT_MS);
      const output = [result.stdout.trim(), result.stderr.trim()].filter(Boolean).join("\n");
      pi.sendMessage({ customType: "oasis-doctor", content: output || `exit ${result.code}`, display: true });
    } catch (error) {
      ctx.ui.notify(`oasis doctor failed: ${error instanceof Error ? error.message : String(error)}`, "error");
    }
  }

  const COMMAND_DESCRIPTION =
    "Odoo project status: profile, addon modules, databases, git worktree and this checkout's server; " +
    SUBCOMMAND_SUMMARY;
  // One entry per subcommand of the table in lib/commands.ts, which also drives completion and usage.
  type CommandContext = Parameters<Parameters<ExtensionAPI["registerCommand"]>[1]["handler"]>[1];
  const subcommands: Record<SubcommandName, (ctx: CommandContext, args: string[]) => Promise<void>> = {
    setup: (ctx) => setup(ctx),
    doctor: (ctx) => doctor(ctx),
    migrate: (ctx) => migrate(ctx),
    worktree: (ctx, args) => worktree(ctx, args[0], args[1]),
  };

  // `/oasis`, and `/odoo19` as its alias: one handler, the same subcommands.
  const command: Parameters<ExtensionAPI["registerCommand"]>[1] = {
    description: COMMAND_DESCRIPTION,
    getArgumentCompletions: (prefix: string) => subcommandCompletions(prefix),
    handler: async (args, ctx) => {
      const parsed = parseCommand(args ?? "");
      if (parsed.kind === "usage") {
        ctx.ui.notify(USAGE, "warning");
        return;
      }
      if (parsed.kind === "run") {
        await subcommands[parsed.name](ctx, parsed.args);
        return;
      }
      const root = await projectRoot(ctx.cwd);
      if (!root) {
        ctx.ui.notify(`Not an Odoo project: ${notProject(ctx.cwd)}`, "warning");
        return;
      }
      const content = formatStatus(await projectStatus(root));
      pi.sendMessage({ customType: "oasis-status", content, display: true });
    },
  };
  pi.registerCommand("oasis", command);
  pi.registerCommand("odoo19", { ...command, description: `Alias of /oasis. ${COMMAND_DESCRIPTION}` });

  // The oasis_* tools are registered inactive; activate them only in sessions inside an Odoo
  // project so other projects pay no tokens for their schemas and guidelines. Other tools, the
  // odoo19_* aliases included, are untouched.
  pi.on("session_start", async (_event, ctx) => {
    const inProject = (await projectRoot(ctx.cwd)) !== null;
    // Read after the await: another handler may change the active tools meanwhile.
    const active = pi.getActiveTools();
    const next = nextActiveTools(active, inProject, OASIS_TOOLS);
    if (next.length !== active.length || next.some((name, index) => name !== active[index])) pi.setActiveTools(next);
  });

  // Session notice: remind the user once when the subagent overlay is missing or outdated.
  let overlayNoticeShown = false;
  pi.on("session_start", async (_event, ctx) => {
    if (overlayNoticeShown) return;
    try {
      if (!(await projectRoot(ctx.cwd))) return;
      const state = overlayState(OVERLAY_TEMPLATE, currentOverlayTarget());
      if (state === "current") return;
      overlayNoticeShown = true;
      const problem = state === "missing" ? "subagents do not have the oasis tools yet" : "overlay is outdated";
      ctx.ui.notify(`oasis: ${problem}; run /oasis setup`, "info");
    } catch {
      // Never block startup on the overlay check.
    }
  });

  pi.on("before_agent_start", async (event, ctx) => {
    const root = await projectRoot(ctx.cwd);
    if (!root) return;
    // A checkout without profile names its workspace file (null when the root holds the profile).
    // Name only the oasis tools this session has: a subagent without the overlay has none.
    const context = projectContext(root, findWorkspaceFile(root), pi.getActiveTools(), await projectVersion(root));
    const sections = event.systemPromptOptions?.sections;
    if (sections) {
      sections.oasis = context;
      return;
    }
    return { systemPrompt: `${event.systemPrompt}\n\n<oasis>\n${context}\n</oasis>` };
  });

  // Agent bash only: direct odoo-bin/dropdb/psql bypass the core's database guards (Odoo projects);
  // worktree-init links environment files and migrate rewrites configuration files, so both are
  // user-run in every session.
  pi.on("tool_call", async (event, ctx) => {
    if (event.toolName !== "bash") return;
    const command = (event.input as { command?: unknown }).command;
    if (typeof command !== "string") return;
    const program = blockedProgram(command);
    if (!program) return;
    if (program === WORKTREE_INIT || program === MIGRATE) return { block: true, reason: blockReason(program, "") };
    const root = await projectRoot(ctx.cwd);
    if (root) return { block: true, reason: blockReason(program, root) };
  });

  // Each tool is registered under its oasis_* name and, always inactive, under its odoo19_* alias
  // with the same parameters and implementation, for overlays and allowlists that name the old
  // tools; the layer activates only the oasis_* names (OASIS_TOOLS).
  function registerWithAlias(tool: ToolDefinition): void {
    pi.registerTool(tool);
    const alias = aliasOf(tool.name);
    pi.registerTool({
      ...tool,
      name: alias,
      defaultActive: false,
      label: `${tool.label} (alias of ${tool.name})`,
      description: `Alias of ${tool.name}. ${tool.description}`,
      ...(tool.promptGuidelines
        ? { promptGuidelines: tool.promptGuidelines.map((line) => line.replaceAll(tool.name, alias)) }
        : {}),
    });
  }

  registerWithAlias({
    name: "oasis_test_module",
    defaultActive: false,
    label: "Odoo test module",
    description:
      "Run one Odoo module's tests on a new disposable test database dropped afterwards (a given or configured " +
      "database is reset first instead). Returns the result line and " +
      "failures with the end of each traceback; full logs stay in the profile logs directory (default dev/logs/odoo19).",
    promptSnippet: "Run an Odoo module's tests and get only the result and failures",
    promptGuidelines: [
      "Use oasis_test_module instead of running odoo-bin --test-tags through bash.",
      "While fixing one failing test, pass `only` (Class or Class.method) and `reuse: true` to oasis_test_module; " +
        "before finishing, run the whole module once without `reuse`.",
      "For a suite expected to take minutes, run `oasis --project <root> test-module --compact <module>` with the " +
        "background shell tool instead of oasis_test_module, then pass what it printed to oasis_test_summary.",
    ],
    parameters: Type.Object({
      module: Type.String({ description: "Technical module name" }),
      database: Type.Optional(Type.String({
        description: "Test database to reset and reuse; default: the profile's test_database, else a disposable one",
      })),
      only: Type.Optional(Type.String({
        description: "Run one test class, or one method of it: Class or Class.method. Default: every test of the module",
        pattern: "^[A-Za-z_][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)?$",
      })),
      reuse: Type.Optional(Type.Boolean({
        description:
          "Keep the test database between runs: the first run installs the module, later runs update it (seconds " +
          "instead of a fresh install). Use while iterating; run once without it for the final result",
        default: false,
      })),
      maxFailures: Type.Optional(Type.Integer({ minimum: 0, maximum: 50, default: 10 })),
      traceLines: Type.Optional(Type.Integer({ minimum: 0, maximum: 40, default: 6 })),
    }),
    async execute(_id, params, signal, onUpdate, ctx) {
      const root = await requireRoot(ctx.cwd);
      // The run is silent until it ends: report elapsed time so a long suite is not mistaken for a hang.
      const result = await withHeartbeat(
        () => run(root, testModuleArgs(params), signal, TEST_TIMEOUT_MS),
        (seconds) => onUpdate?.({
          content: [{ type: "text", text: `running tests of ${params.module}: ${seconds} s` }],
          details: { running: true, seconds },
        }),
        HEARTBEAT_MS,
      );
      const options = { maxFailures: params.maxFailures ?? 10, traceLines: params.traceLines ?? 6 };
      return text(formatTestRun(params.module, result, readLog, options, MAX_LINES, params.only), { exit: result.code });
    },
  });

  registerWithAlias({
    name: "oasis_test_summary",
    defaultActive: false,
    label: "Odoo test summary",
    description:
      "Summarize a test run started outside oasis_test_module (for example in the background): pass the text " +
      "that `oasis --project <root> test-module --compact <module>` printed. Reads only the run logs it names and " +
      "returns the same summary as oasis_test_module.",
    promptSnippet: "Summarize a compact Odoo test run that finished in the background",
    parameters: Type.Object({
      module: Type.String({ description: "Technical module name" }),
      output: Type.String({ description: "What test-module --compact printed (phase, stdout_log and stderr_log lines)" }),
      maxFailures: Type.Optional(Type.Integer({ minimum: 0, maximum: 50, default: 10 })),
      traceLines: Type.Optional(Type.Integer({ minimum: 0, maximum: 40, default: 6 })),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      await requireRoot(ctx.cwd);
      const options = { maxFailures: params.maxFailures ?? 10, traceLines: params.traceLines ?? 6 };
      return text(formatBackgroundRun(params.module, params.output, readLog, options, MAX_LINES));
    },
  });

  registerWithAlias({
    name: "oasis_update_module",
    defaultActive: false,
    label: "Odoo update module",
    description:
      "Update one module in an existing managed database (dev or test prefix) after changing its models, views " +
      "or data. Returns errors and grouped warnings only; the full log stays on disk.",
    promptGuidelines: [
      "Use oasis_update_module instead of running odoo-bin -u through bash; it never creates a database.",
    ],
    parameters: Type.Object({
      module: Type.String({ description: "Technical module name" }),
      database: Type.String({ description: "Existing managed database (dev or test prefix)" }),
      maxFailures: Type.Optional(Type.Integer({ minimum: 0, maximum: 50, default: 10 })),
      traceLines: Type.Optional(Type.Integer({ minimum: 0, maximum: 40, default: 6 })),
    }),
    async execute(_id, params, signal, onUpdate, ctx) {
      const root = await requireRoot(ctx.cwd);
      const result = await withHeartbeat(
        () => run(root, updateModuleArgs(params), signal, TEST_TIMEOUT_MS),
        (seconds) => onUpdate?.({
          content: [{ type: "text", text: `updating ${params.module} in ${params.database}: ${seconds} s` }],
          details: { running: true, seconds },
        }),
        HEARTBEAT_MS,
      );
      const options = { maxFailures: params.maxFailures ?? 10, traceLines: params.traceLines ?? 6 };
      return text(formatUpdateRun(params.module, result, readLog, options, MAX_LINES), { exit: result.code });
    },
  });

  registerWithAlias({
    name: "oasis_find_module",
    defaultActive: false,
    label: "Odoo find module",
    description:
      "Find technical module names in the project's addon roots from a functional name, matching words of the " +
      "technical name and the manifest name, summary and category. Returns `technical — manifest name` lines.",
    promptSnippet: "Map a functional module name to its technical name",
    promptGuidelines: [
      "Use oasis_find_module to map functional names to technical module names instead of ls/grep over addons.",
    ],
    parameters: Type.Object({
      query: Type.String({ description: "Words of the functional or technical module name" }),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 30, default: DEFAULT_LIMIT })),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      const root = await requireRoot(ctx.cwd);
      const { config, error } = await profileConfig(root);
      if (!config) throw new Error(`Cannot read the project profile: ${error}`);
      const { matches, total } = findModules(loadModules(addonRoots(config)), params.query, params.limit ?? DEFAULT_LIMIT);
      return text(formatModules(matches, total), { total });
    },
  });

  registerWithAlias({
    name: "oasis_model_info",
    defaultActive: false,
    label: "Odoo model info",
    description:
      "Static summary of one Odoo model from the Odoo source and the project's addons (ast only; no Odoo, " +
      "environment or database): definition, extending modules, fields, field overrides and methods.",
    promptSnippet: "Learn an Odoo model's fields, methods and inheritance without opening source files",
    promptGuidelines: [
      "Use oasis_model_info before reading Odoo source files to learn a model's fields, methods or inheritance.",
    ],
    parameters: Type.Object({
      model: Type.String({ description: "Model name, e.g. sale.order" }),
      field: Type.Optional(Type.String({ description: "Only this field: definition and overrides with file:line" })),
      module: Type.Optional(Type.String({ description: "Only the details contributed by this technical module" })),
      methods: Type.Optional(Type.Boolean({ description: "Every method with decorators and super() calls", default: false })),
      allFields: Type.Optional(Type.Boolean({ description: "Do not cap the field list", default: false })),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      const args = ["model-info", params.model];
      if (params.field) args.push("--field", params.field);
      if (params.module) args.push("--module", params.module);
      if (params.methods) args.push("--methods");
      if (params.allFields) args.push("--all-fields");
      return plain(ctx.cwd, args, signal, MODEL_INFO_MAX_LINES);
    },
  });

  registerWithAlias({
    name: "oasis_view_info",
    defaultActive: false,
    label: "Odoo view info",
    description:
      "The views of one Odoo model from the Odoo source and the project's addons (static XML parsing; no Odoo, " +
      "environment or database): each base view with its type, XML id and file:line, and the views that extend it.",
    promptSnippet: "List a model's views and their extensions without opening XML files",
    promptGuidelines: [
      "Use oasis_view_info before searching XML files to find a model's views or what extends a view.",
    ],
    parameters: Type.Object({
      model: Type.String({ description: "Model name, e.g. sale.order" }),
      type: Type.Optional(Type.String({ description: "Only base views of this type (form, list, kanban, search, ...)" })),
      module: Type.Optional(Type.String({ description: "Only the views this technical module defines" })),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      return plain(ctx.cwd, viewInfoArgs(params), signal, MODEL_INFO_MAX_LINES);
    },
  });

  registerWithAlias({
    name: "oasis_xmlid_info",
    defaultActive: false,
    label: "Odoo XML id info",
    description:
      "Where one XML id (record, template or menuitem) is defined, its fields, the views that extend it and the " +
      "files that reference it, from source (no Odoo, environment or database).",
    promptSnippet: "Locate an XML id, its extensions and its references without grep",
    promptGuidelines: [
      "Use oasis_xmlid_info instead of grep to locate an XML id or to see what references it.",
    ],
    parameters: Type.Object({
      id: Type.String({ description: "Full XML id: <module>.<name>, e.g. sale.view_order_form" }),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      return plain(ctx.cwd, ["xmlid-info", params.id], signal, MODEL_INFO_MAX_LINES);
    },
  });

  registerWithAlias({
    name: "oasis_module_status",
    defaultActive: false,
    label: "Odoo module status",
    description: "Database and module state (missing, uninitialized, installed, version) for a managed database.",
    parameters: Type.Object({
      module: Type.String({ description: "Technical module name" }),
      database: Type.String({ description: "Managed database (dev or test prefix)" }),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      return plain(ctx.cwd, ["module-status", params.module, params.database], signal);
    },
  });

  registerWithAlias({
    name: "oasis_check_environment",
    defaultActive: false,
    label: "Odoo check environment",
    description: "Check the project's Odoo environment. Quick mode by default; full mode needs the user's consent.",
    parameters: Type.Object({
      full: Type.Optional(Type.Boolean({ description: "Run full diagnostics", default: false })),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      return plain(ctx.cwd, ["check-environment", params.full ? "--full" : "--quick"], signal);
    },
  });

  registerWithAlias({
    name: "oasis_lint_module",
    defaultActive: false,
    label: "Odoo lint module",
    description: "Run Pylint with the project's declared rcfile on one module, without starting Odoo.",
    parameters: Type.Object({
      module: Type.String({ description: "Technical module name" }),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      return plain(ctx.cwd, ["lint-module", params.module], signal);
    },
  });
}
