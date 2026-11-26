// Gentle Shell (Pi) layer for the Odoo bundle. It wraps the agent-agnostic
// `oasis` entry point shipped in this repository; it changes nothing in Pi or
// Gentle Shell and keeps every guard inside the core tools.
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { existsSync, readFileSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { fileURLToPath } from "node:url";
import {
  parseCommand, registerSubcommandAutocomplete, SUBCOMMAND_SUMMARY, type SubcommandName, subcommandCompletions, USAGE,
} from "../lib/commands.ts";
import { withHeartbeat } from "../lib/heartbeat.ts";
import { DECISION_ENTRY, type GateEffects, settingReader, toolCallRouter } from "../lib/destructive.ts";
import { findModules, formatModules, loadModules, DEFAULT_LIMIT } from "../lib/modules.ts";
import {
  findWorkspaceFile, legacyProfile, migrateFlow, notProject, type PlanFlow, projectContext, projectRootResolver,
  worktreeFlow,
} from "../lib/project.ts";
import { formatStatus, listModules, parseAssignments, parseGit, parseServer, type StatusInput } from "../lib/status.ts";
import { nextActiveTools, OASIS_TOOLS } from "../lib/activation.ts";
import { overlayReminder, runSetup, setupCommand, type SetupInput } from "../lib/setup.ts";
import { type Answers, menuShortcut, type PickerChoice, RunForm } from "../lib/menu.ts";
import { actionPanel, type ExecPurpose } from "../lib/panel.ts";
import { readTail } from "../lib/log-tail.ts";
import { LogPanel, MENU_ENTRY, MenuPanel, renderMenuEntry, RunFormPanel } from "../ui/menu-panel.ts";
import {
  formatBackgroundRun, formatPlain, formatTestRun, formatUpdateRun, moduleInfoArgs, testModuleArgs, updateModuleArgs,
  viewInfoArgs,
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
// The action panel's footer status key; its commands get the test timeout (a whole suite may run).
const MENU_STATUS = "oasis-menu";
const MENU_TIMEOUT_MS = TEST_TIMEOUT_MS;

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

  // The resolved configuration from tools/config.py (read-only): values, or the error it reported.
  async function projectConfig(root: string): Promise<{ config?: Record<string, string>; error?: string }> {
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
      const version = (await projectConfig(root)).config?.ODOO_VERSION;
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

  // Read-only status: the configuration, addon roots, git state and this checkout's server record.
  // Never starts services or queries databases.
  async function projectStatus(root: string): Promise<StatusInput> {
    const status: StatusInput = { root, modules: [], git: null };
    const { config, error } = await projectConfig(root);
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

  // User-run only (no tool registers it): the workspace status and the `oasis setup` plan of the session's
  // checkout (`--project <root>` under a workspace file, else the checkout of the working directory, as the CLI
  // finds it), never applied; the subagent overlay is installed in Gentle Shell only (lib/setup.ts).
  async function setup(ctx: { cwd: string; ui: SetupInput["ui"] }): Promise<void> {
    const root = await projectRoot(ctx.cwd);
    await runSetup({
      env: process.env, homedir: homedir(), template: OVERLAY_TEMPLATE,
      run: (args) => {
        const call = setupCommand(OASIS, root, ctx.cwd, args);
        return pi.exec(call.command, call.args, { cwd: call.cwd, timeout: DOCTOR_TIMEOUT_MS });
      },
      show: (content) => pi.sendMessage({ customType: "oasis-setup", content, display: true }),
      ui: ctx.ui,
    });
  }

  type FlowUi = { notify: (message: string, level?: "info" | "warning" | "error") => void;
    confirm: (title: string, message: string) => Promise<boolean> };
  // The CLI in the project root and the session's dialogs, for the plan-then-confirm flows (lib/project.ts).
  function planFlow(root: string, ui: FlowUi): PlanFlow {
    return {
      run: (args) => run(root, args, undefined, TOOL_TIMEOUT_MS),
      ui,
    };
  }

  // The user's /oasis worktree: the dry-run plan, then `worktree-init --confirm <worktree path>` (Tier B)
  // on yes, with the path the plan names (worktreeFlow).
  async function worktree(ctx: { cwd: string; ui: FlowUi }, feature: string, branch: string): Promise<void> {
    const root = await projectRoot(ctx.cwd);
    if (!root) {
      ctx.ui.notify(`Not an Odoo project: ${notProject(ctx.cwd)}`, "warning");
      return;
    }
    await worktreeFlow(planFlow(root, ctx.ui), feature, branch);
  }

  // The user's /oasis migrate: the plan, then `migrate --apply --confirm <workspace file>` (Tier B) on yes,
  // with the workspace file the plan writes (migrateFlow).
  async function migrate(ctx: { cwd: string; ui: FlowUi }): Promise<void> {
    const root = await projectRoot(ctx.cwd);
    if (!root) {
      ctx.ui.notify(`Not an Odoo project: ${notProject(ctx.cwd)}`, "warning");
      return;
    }
    await migrateFlow(planFlow(root, ctx.ui));
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

  // The action panel (alt+o or OASIS_MENU_KEY, and /oasis menu): user-run only, no agent tool opens
  // it. lib/panel.ts decides everything (catalog, inputs, confirmation, run, result); this adapter
  // gives it pi.exec in the project root, the Pi dialogs and the overlays (the picker, with the
  // checkout's server state from runtime_state in its header, the start / restart form with the
  // native odoo-bin line from `start --print-command`, and the live server log, which reads the end
  // of server.log again every second while open), records results as custom session entries
  // (pi.appendEntry with an entry renderer, the full native line included): Pi shows them but never
  // sends them to the model, and remembers the action that ran for Repeat (runtime_state.py remember).
  pi.registerEntryRenderer(MENU_ENTRY, renderMenuEntry);
  const EXEC_TIMEOUTS: Record<ExecPurpose, number> = {
    catalog: STATUS_TIMEOUT_MS, list: TOOL_TIMEOUT_MS, print: STATUS_TIMEOUT_MS, run: MENU_TIMEOUT_MS,
  };
  const openPanel = actionPanel({
    projectRoot: (cwd) => projectRoot(cwd),
    notProject,
    catalogArgv: (root) => ["python3", "-B", OASIS, "--project", root, "menu", "--catalog"],
    exec: (argv, cwd, purpose) => pi.exec(argv[0], argv.slice(1), { cwd, timeout: EXEC_TIMEOUTS[purpose] }),
    exists: existsSync,
    readLog,
    home: homedir(),
    appendEntry: (entry) => pi.appendEntry(MENU_ENTRY, entry),
    serverState: (root) => serverState(root),
    remember: async (root, action, answers) => {
      const result = await pi.exec("python3", ["-I", "-B", RUNTIME_STATE_PY, "remember", root, action,
        JSON.stringify(answers)], { cwd: root, timeout: STATUS_TIMEOUT_MS });
      if (result.code !== 0) throw new Error(result.stderr.trim() || `runtime_state.py exited with ${result.code}`);
    },
  });

  function menu(ctx: ExtensionContext): Promise<void> {
    return openPanel({
      mode: ctx.mode,
      cwd: ctx.cwd,
      ui: {
        pick: (catalog, header) => ctx.ui.custom<PickerChoice | undefined>(
          (tui, theme, keybindings, done) => new MenuPanel(catalog, header, tui, theme, keybindings, done),
          {
            overlay: true,
            overlayOptions: { anchor: "center", width: "80%", minWidth: 40, maxHeight: "90%" },
            blocked: { kind: "question", message: "oasis menu" },
          },
        ),
        form: (spec) => ctx.ui.custom<Answers | undefined>(
          (tui, theme, keybindings, done) => new RunFormPanel(new RunForm(spec), tui, theme, keybindings, done),
          {
            overlay: true,
            overlayOptions: { anchor: "center", width: "80%", minWidth: 40, maxHeight: "90%" },
            blocked: { kind: "question", message: "oasis menu" },
          },
        ),
        follow: (path, title) => ctx.ui.custom<void>(
          (tui, theme, keybindings, done) => new LogPanel(title, () => readTail(path), tui, theme, keybindings,
            () => done()),
          { overlay: true, overlayOptions: { anchor: "center", width: "90%", minWidth: 40, maxHeight: "90%" } },
        ),
        select: (title, options) => ctx.ui.select(title, options),
        input: (title, placeholder) => ctx.ui.input(title, placeholder),
        confirm: (title, message) => ctx.ui.confirm(title, message),
        notify: (message, level) => ctx.ui.notify(message, level),
        setStatus: (text) => ctx.ui.setStatus(MENU_STATUS, text),
      },
    });
  }

  // OASIS_MENU_KEY (alt+o when unset; empty or `off` disables it), read when Pi loads the extension
  // (startup and /reload). An unusable value turns the shortcut off and is reported once.
  const shortcut = menuShortcut(process.env.OASIS_MENU_KEY);
  if (shortcut.key) {
    pi.registerShortcut(shortcut.key as Parameters<ExtensionAPI["registerShortcut"]>[0], {
      description: "Open the oasis action panel",
      handler: (ctx) => menu(ctx),
    });
  }
  let shortcutNoticeShown = false;
  pi.on("session_start", async (_event, ctx) => {
    if (!shortcut.error || shortcutNoticeShown) return;
    shortcutNoticeShown = true;
    ctx.ui.notify(`oasis: ${shortcut.error}`, "warning");
  });

  const COMMAND_DESCRIPTION =
    "Odoo project status: configuration, addon modules, databases, git worktree and this checkout's server; " +
    SUBCOMMAND_SUMMARY;
  // One entry per subcommand of the table in lib/commands.ts, which also drives completion and usage.
  type CommandContext = Parameters<Parameters<ExtensionAPI["registerCommand"]>[1]["handler"]>[1];
  const subcommands: Record<SubcommandName, (ctx: CommandContext, args: string[]) => Promise<void>> = {
    setup: (ctx) => setup(ctx),
    doctor: (ctx) => doctor(ctx),
    migrate: (ctx) => migrate(ctx),
    worktree: (ctx, args) => worktree(ctx, args[0], args[1]),
    menu: (ctx) => menu(ctx),
  };

  // `/oasis`: one handler for the status and every subcommand.
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

  // Typing `/oa` (no space yet) also suggests `/oasis <subcommand>` (lib/commands.ts
  // subcommandAutocomplete); everything else goes to the provider it
  // wraps. Pi drops extension providers when it rebinds a session, so each session registers it once,
  // in the TUI only (registerSubcommandAutocomplete).
  pi.on("session_start", async (_event, ctx) => {
    registerSubcommandAutocomplete(ctx);
  });

  // The oasis_* tools are registered inactive; activate them only in sessions inside an Odoo
  // project so other projects pay no tokens for their schemas and guidelines. Other tools are
  // untouched.
  pi.on("session_start", async (_event, ctx) => {
    const inProject = (await projectRoot(ctx.cwd)) !== null;
    // Read after the await: another handler may change the active tools meanwhile.
    const active = pi.getActiveTools();
    const next = nextActiveTools(active, inProject, OASIS_TOOLS);
    if (next.length !== active.length || next.some((name, index) => name !== active[index])) pi.setActiveTools(next);
  });

  // Session notice: remind the user once when the subagent overlay is missing or outdated, only in
  // Gentle Shell (lib/setup.ts overlayReminder).
  let overlayNoticeShown = false;
  pi.on("session_start", async (_event, ctx) => {
    if (overlayNoticeShown) return;
    try {
      if (!(await projectRoot(ctx.cwd))) return;
      const reminder = overlayReminder({ env: process.env, homedir: homedir(), template: OVERLAY_TEMPLATE });
      if (!reminder) return;
      overlayNoticeShown = true;
      ctx.ui.notify(reminder, "info");
    } catch {
      // Never block startup on the overlay check.
    }
  });

  pi.on("before_agent_start", async (event, ctx) => {
    const root = await projectRoot(ctx.cwd);
    if (!root) return;
    // The checkout's workspace file; null when the root holds a legacy profile, which config.py
    // refuses (the context then says so). Name only the oasis tools this session has: a subagent
    // without the overlay has none.
    const workspace = legacyProfile(root) ? null : findWorkspaceFile(root);
    const context = projectContext(root, workspace, pi.getActiveTools(), await projectVersion(root));
    const sections = event.systemPromptOptions?.sections;
    if (sections) {
      sections.oasis = context;
      return;
    }
    return { systemPrompt: `${event.systemPrompt}\n\n<oasis>\n${context}\n</oasis>` };
  });

  // Agent shell (bash, bash_background, monitor: SHELL_TOOLS), edit and write tool calls, nested
  // ones (codemode) included; lib/destructive.ts decides (toolCallRouter) with the tiers of the core
  // policy table (lib/policy.ts). Deny tier (C): direct odoo-bin/dropdb/psql bypass the core's database
  // guards (Odoo projects), and the user's interactive menu is denied in every session. Ask tier (B):
  // drop-database, stop --database, gc --apply --trash, migrate --apply and worktree-init run after the
  // user types the database name or `yes` in a dialog, unless
  // [tooling].agent_destructive (read through config.py, never from a tool argument) says deny or
  // allow: the stricter of the session project's and the target project's (`--project`, or a tool
  // script's OASIS_PROJECT_ROOT or ODOO19_PROJECT_ROOT). The files that hold that setting (an
  // oasis-workspace.toml, or a legacy .odoo19-agent.toml that migrate converts, in the session's
  // directory or above it) are in the
  // ask tier too: bash writes to them and Pi's edit and write tool calls on them. Each ask decision
  // is a custom session entry: Pi shows it but never sends it to the model.
  pi.registerEntryRenderer(DECISION_ENTRY, renderMenuEntry);
  const gateEffects: GateEffects = {
    projectRoot: (cwd) => projectRoot(cwd),
    home: homedir(),
    exists: existsSync,
    agentDestructive: settingReader(projectConfig),
    appendEntry: (entry) => pi.appendEntry(DECISION_ENTRY, entry),
    realpath: realpathSync,
  };
  const routeToolCall = toolCallRouter(gateEffects);
  pi.on("tool_call", (event, ctx) => routeToolCall(event, ctx));

  // Each tool is registered inactive under its oasis_* name; the layer activates them in Odoo
  // projects (OASIS_TOOLS).
  pi.registerTool({
    name: "oasis_test_module",
    defaultActive: false,
    label: "Odoo test module",
    description:
      "Run one Odoo module's tests on a new disposable test database dropped afterwards (a given or configured " +
      "database is reset first instead). Returns the result line and " +
      "failures with the end of each traceback; full logs stay in the configured logs directory (default: logs next " +
      "to oasis-workspace.toml).",
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
        description: "Test database to reset and reuse; default: the configured test_database, else a disposable one",
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

  pi.registerTool({
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
      const root = await requireRoot(ctx.cwd);
      // The named logs must lie in this checkout's logs directory ([tooling].logs, else logs next to the workspace file).
      const { config, error } = await projectConfig(root);
      if (!config) throw new Error(`Cannot read the project configuration: ${error}`);
      const options = { maxFailures: params.maxFailures ?? 10, traceLines: params.traceLines ?? 6 };
      // lib/tools.ts decides: the named logs' real paths in the real log locations (symlinks followed).
      return text(formatBackgroundRun(params.module, params.output, config, { realpath: realpathSync, readLog }, options,
        MAX_LINES));
    },
  });

  pi.registerTool({
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

  pi.registerTool({
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
      const { config, error } = await projectConfig(root);
      if (!config) throw new Error(`Cannot read the project configuration: ${error}`);
      const { matches, total } = findModules(loadModules(addonRoots(config)), params.query, params.limit ?? DEFAULT_LIMIT);
      return text(formatModules(matches, total), { total });
    },
  });

  pi.registerTool({
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

  pi.registerTool({
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

  pi.registerTool({
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

  pi.registerTool({
    name: "oasis_module_info",
    defaultActive: false,
    label: "Odoo module info",
    description:
      "One-screen map of one Odoo module from source (ast, expat and csv only; no Odoo, environment or database): " +
      "manifest, models defined and extended, views, menus, actions, security, data files, crons and tests.",
    promptSnippet: "See a module's architecture without opening its files",
    promptGuidelines: [
      "Use oasis_module_info before opening a module's files to learn its models, views, menus, security and data.",
    ],
    parameters: Type.Object({
      module: Type.String({ description: "Technical module name, e.g. sale_mrp" }),
      section: Type.Optional(Type.String({
        description: "Only this section, uncapped: models, views, menus, actions, security, data or tests",
      })),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      return plain(ctx.cwd, moduleInfoArgs(params), signal, MODEL_INFO_MAX_LINES);
    },
  });

  pi.registerTool({
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

  pi.registerTool({
    name: "oasis_check_environment",
    defaultActive: false,
    label: "Odoo check environment",
    description: "Check the project's Odoo environment. Quick mode by default; full mode needs the user's consent.",
    parameters: Type.Object({
      full: Type.Optional(Type.Boolean({ description: "Run full diagnostics", default: false })),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      // v0.16.0 S5: doctor --environment, which check-environment (a deprecated alias) runs with the same output.
      return plain(ctx.cwd, ["doctor", "--environment", params.full ? "--full" : "--quick"], signal);
    },
  });

  pi.registerTool({
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
