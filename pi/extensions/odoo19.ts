// Gentle Shell (Pi) layer for the Odoo 19 bundle. It wraps the agent-agnostic
// `odoo19` entry point shipped in this repository; it changes nothing in Pi or
// Gentle Shell and keeps every guard inside the core tools.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { fileURLToPath } from "node:url";
import { blockedProgram, blockReason, WORKTREE_INIT } from "../lib/bash-guard.ts";
import { findModules, formatModules, loadModules, DEFAULT_LIMIT } from "../lib/modules.ts";
import { findProjectRoot, findWorkspaceFile, projectContext } from "../lib/project.ts";
import { formatStatus, listModules, parseAssignments, parseGit, parseServer, type StatusInput } from "../lib/status.ts";
import { nextActiveTools, ODOO19_TOOLS } from "../lib/activation.ts";
import { configHome, installOverlay, overlayState, overlayTarget } from "../lib/setup.ts";
import { formatPlain, formatTestRun, testModuleArgs } from "../lib/tools.ts";

const ODOO19 = fileURLToPath(new URL("../../odoo19", import.meta.url));
const CONFIG_PY = fileURLToPath(new URL("../../tools/config.py", import.meta.url));
const RUNTIME_STATE_PY = fileURLToPath(new URL("../../tools/runtime_state.py", import.meta.url));
const OVERLAY_TEMPLATE = fileURLToPath(new URL("../agent-overlays/oasis.json", import.meta.url));
const STATUS_TIMEOUT_MS = 15000;
const MAX_LINES = 60;
// model-info output is already compact; a larger cap keeps --methods/--all-fields useful.
const MODEL_INFO_MAX_LINES = 200;
const TEST_TIMEOUT_MS = 60 * 60 * 1000;
const TOOL_TIMEOUT_MS = 10 * 60 * 1000;

type Result = { content: { type: "text"; text: string }[]; details: Record<string, unknown> };

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

export default function odoo19Layer(pi: ExtensionAPI) {
  // Git top level of each directory under a workspace file, read once (null: git cannot tell).
  const topLevels = new Map<string, string | null>();

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

  // The checkout root of cwd (lib/project.ts); git runs only for a directory under a workspace file.
  async function projectRoot(cwd: string): Promise<string | null> {
    const lookup = { missing: null as string | null };
    const root = findProjectRoot(cwd, (start) => {
      if (topLevels.has(start)) return topLevels.get(start) ?? null;
      lookup.missing = start;
      return null;
    });
    if (lookup.missing === null) return root;
    topLevels.set(lookup.missing, await gitTopLevel(lookup.missing));
    return findProjectRoot(cwd, (start) => topLevels.get(start) ?? null);
  }

  async function requireRoot(cwd: string): Promise<string> {
    const root = await projectRoot(cwd);
    if (!root) throw new Error(`Not an Odoo 19 project: ${notProject(cwd)}.`);
    return root;
  }

  async function run(root: string, args: string[], signal: AbortSignal | undefined, timeout: number) {
    return pi.exec("python3", ["-B", ODOO19, "--project", root, ...args], { cwd: root, signal, timeout });
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
        ctx.ui.notify(`odoo19 setup: subagent overlay is up to date (${target})`, "info");
        return;
      }
      const verb = state === "missing" ? "Create" : "Update";
      const question = `${verb} ${target} so gentle-ai-worker and gentle-ai-verify get the odoo19 tools?`;
      if (!(await ctx.ui.confirm("odoo19 setup", question))) {
        ctx.ui.notify("odoo19 setup: nothing changed.", "info");
        return;
      }
      const result = installOverlay(OVERLAY_TEMPLATE, target);
      if (result.state === "unchanged") {
        ctx.ui.notify(`odoo19 setup: subagent overlay is up to date (${target})`, "info");
        return;
      }
      ctx.ui.notify(
        `odoo19 setup: subagent overlay ${result.state} at ${target}. ` +
          "Start a new session or /reload for subagents to use it.",
        "info",
      );
    } catch (error) {
      ctx.ui.notify(`odoo19 setup failed: ${error instanceof Error ? error.message : String(error)}`, "error");
    }
  }

  // User-run only (agents are blocked from worktree-init): show the dry-run plan, then create it on yes.
  async function worktree(ctx: { cwd: string; ui: { notify: (message: string, level?: "info" | "warning" | "error") => void;
    confirm: (title: string, message: string) => Promise<boolean> } }, feature: string, branch: string): Promise<void> {
    const root = await projectRoot(ctx.cwd);
    if (!root) {
      ctx.ui.notify(`Not an Odoo 19 project: ${notProject(ctx.cwd)}`, "warning");
      return;
    }
    const args = ["worktree-init", feature, branch];
    try {
      const plan = await run(root, [...args, "--dry-run"], undefined, TOOL_TIMEOUT_MS);
      if (plan.code !== 0) {
        ctx.ui.notify(`odoo19 worktree: ${plan.stderr.trim() || `exit ${plan.code}`}`, "error");
        return;
      }
      const steps = plan.stdout.trim().split("\n").filter((line) => line !== "dry run: nothing changed");
      if (!(await ctx.ui.confirm("odoo19 worktree", `${steps.join("\n")}\n\nCreate this worktree?`))) {
        ctx.ui.notify("odoo19 worktree: nothing changed.", "info");
        return;
      }
      const result = await run(root, args, undefined, TOOL_TIMEOUT_MS);
      const output = [result.stdout.trim(), result.stderr.trim()].filter(Boolean).join("\n");
      ctx.ui.notify(`odoo19 worktree:\n${output || `exit ${result.code}`}`, result.code === 0 ? "info" : "error");
    } catch (error) {
      ctx.ui.notify(`odoo19 worktree failed: ${error instanceof Error ? error.message : String(error)}`, "error");
    }
  }

  const USAGE = "Usage: /odoo19 [setup | worktree <feature> <branch>]";

  pi.registerCommand("odoo19", {
    description:
      "Odoo 19 project status: profile, addon modules, databases, git worktree and this checkout's server; " +
      "`setup` installs the subagent overlay; `worktree <feature> <branch>` creates a prepared linked worktree",
    handler: async (args, ctx) => {
      const argument = (args ?? "").trim();
      if (argument === "setup") {
        await setup(ctx);
        return;
      }
      const words = argument.split(/\s+/);
      if (words[0] === "worktree") {
        if (words.length !== 3 || words.slice(1).some((word) => word.startsWith("-"))) {
          ctx.ui.notify(USAGE, "warning");
          return;
        }
        await worktree(ctx, words[1], words[2]);
        return;
      }
      if (argument) {
        ctx.ui.notify(USAGE, "warning");
        return;
      }
      const root = await projectRoot(ctx.cwd);
      if (!root) {
        ctx.ui.notify(`Not an Odoo 19 project: ${notProject(ctx.cwd)}`, "warning");
        return;
      }
      const content = formatStatus(await projectStatus(root));
      pi.sendMessage({ customType: "odoo19-status", content, display: true });
    },
  });

  // The odoo19_* tools are registered inactive; activate them only in sessions inside an Odoo 19
  // project so other projects pay no tokens for their schemas and guidelines. Other tools are untouched.
  pi.on("session_start", async (_event, ctx) => {
    const active = pi.getActiveTools();
    const next = nextActiveTools(active, (await projectRoot(ctx.cwd)) !== null, ODOO19_TOOLS);
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
      const problem = state === "missing" ? "subagents do not have the odoo19 tools yet" : "overlay is outdated";
      ctx.ui.notify(`oasis: ${problem}; run /odoo19 setup`, "info");
    } catch {
      // Never block startup on the overlay check.
    }
  });

  pi.on("before_agent_start", async (event, ctx) => {
    const root = await projectRoot(ctx.cwd);
    if (!root) return;
    // A checkout without profile names its workspace file (null when the root holds the profile).
    const context = projectContext(root, findWorkspaceFile(root));
    const sections = event.systemPromptOptions?.sections;
    if (sections) {
      sections.odoo19 = context;
      return;
    }
    return { systemPrompt: `${event.systemPrompt}\n\n<odoo19>\n${context}\n</odoo19>` };
  });

  // Agent bash only: direct odoo-bin/dropdb/psql bypass the core's database guards (Odoo projects);
  // worktree-init links environment files, so it is user-run in every session.
  pi.on("tool_call", async (event, ctx) => {
    if (event.toolName !== "bash") return;
    const command = (event.input as { command?: unknown }).command;
    if (typeof command !== "string") return;
    const program = blockedProgram(command);
    if (!program) return;
    if (program === WORKTREE_INIT) return { block: true, reason: blockReason(program, "") };
    const root = await projectRoot(ctx.cwd);
    if (root) return { block: true, reason: blockReason(program, root) };
  });

  pi.registerTool({
    name: "odoo19_test_module",
    defaultActive: false,
    label: "Odoo 19 test module",
    description:
      "Run one Odoo 19 module's tests on a new disposable test database dropped afterwards (a given or configured " +
      "database is reset first instead). Returns the result line and " +
      "failures with the end of each traceback; full logs stay in the profile logs directory (default dev/logs/odoo19).",
    promptSnippet: "Run an Odoo 19 module's tests and get only the result and failures",
    promptGuidelines: ["Use odoo19_test_module instead of running odoo-bin --test-tags through bash."],
    parameters: Type.Object({
      module: Type.String({ description: "Technical module name" }),
      database: Type.Optional(Type.String({
        description: "Test database to reset and reuse; default: the profile's test_database, else a disposable one",
      })),
      maxFailures: Type.Optional(Type.Integer({ minimum: 0, maximum: 50, default: 10 })),
      traceLines: Type.Optional(Type.Integer({ minimum: 0, maximum: 40, default: 6 })),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      const root = await requireRoot(ctx.cwd);
      const result = await run(root, testModuleArgs(params), signal, TEST_TIMEOUT_MS);
      const options = { maxFailures: params.maxFailures ?? 10, traceLines: params.traceLines ?? 6 };
      return text(formatTestRun(params.module, result, readLog, options, MAX_LINES), { exit: result.code });
    },
  });

  pi.registerTool({
    name: "odoo19_find_module",
    defaultActive: false,
    label: "Odoo 19 find module",
    description:
      "Find technical module names in the project's addon roots from a functional name, matching words of the " +
      "technical name and the manifest name, summary and category. Returns `technical — manifest name` lines.",
    promptSnippet: "Map a functional module name to its technical name",
    promptGuidelines: [
      "Use odoo19_find_module to map functional names to technical module names instead of ls/grep over addons.",
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

  pi.registerTool({
    name: "odoo19_model_info",
    defaultActive: false,
    label: "Odoo 19 model info",
    description:
      "Static summary of one Odoo model from the Odoo source and the project's addons (ast only; no Odoo, " +
      "environment or database): definition, extending modules, fields, field overrides and methods.",
    promptSnippet: "Learn an Odoo model's fields, methods and inheritance without opening source files",
    promptGuidelines: [
      "Use odoo19_model_info before reading Odoo source files to learn a model's fields, methods or inheritance.",
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

  pi.registerTool({
    name: "odoo19_module_status",
    defaultActive: false,
    label: "Odoo 19 module status",
    description: "Database and module state (missing, uninitialized, installed, version) for a managed database.",
    parameters: Type.Object({
      module: Type.String({ description: "Technical module name" }),
      database: Type.String({ description: "Managed database (dev or test prefix)" }),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      return plain(ctx.cwd, ["module-status", params.module, params.database], signal);
    },
  });

  pi.registerTool({
    name: "odoo19_check_environment",
    defaultActive: false,
    label: "Odoo 19 check environment",
    description: "Check the project's Odoo 19 environment. Quick mode by default; full mode needs the user's consent.",
    parameters: Type.Object({
      full: Type.Optional(Type.Boolean({ description: "Run full diagnostics", default: false })),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      return plain(ctx.cwd, ["check-environment", params.full ? "--full" : "--quick"], signal);
    },
  });

  pi.registerTool({
    name: "odoo19_lint_module",
    defaultActive: false,
    label: "Odoo 19 lint module",
    description: "Run Pylint with the project's declared rcfile on one module, without starting Odoo.",
    parameters: Type.Object({
      module: Type.String({ description: "Technical module name" }),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      return plain(ctx.cwd, ["lint-module", params.module], signal);
    },
  });
}
