// Gentle Shell (Pi) layer for the Odoo 19 bundle. It wraps the agent-agnostic
// `odoo19` entry point shipped in this repository; it changes nothing in Pi or
// Gentle Shell and keeps every guard inside the core tools.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { findProjectRoot, projectContext } from "../lib/project.ts";
import { formatPlain, formatTestRun, testModuleArgs } from "../lib/tools.ts";

const ODOO19 = fileURLToPath(new URL("../../odoo19", import.meta.url));
const MAX_LINES = 60;
const TEST_TIMEOUT_MS = 60 * 60 * 1000;
const TOOL_TIMEOUT_MS = 10 * 60 * 1000;

type Result = { content: { type: "text"; text: string }[]; details: Record<string, unknown> };

function text(body: string, details: Record<string, unknown> = {}): Result {
  return { content: [{ type: "text", text: body }], details };
}

function requireRoot(cwd: string): string {
  const root = findProjectRoot(cwd);
  if (!root) throw new Error(`No .odoo19-agent.toml at or above ${cwd}; not an Odoo 19 project.`);
  return root;
}

function readLog(path: string): string {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return "";
  }
}

export default function odoo19Layer(pi: ExtensionAPI) {
  async function run(root: string, args: string[], signal: AbortSignal | undefined, timeout: number) {
    return pi.exec("python3", ["-B", ODOO19, "--project", root, ...args], { cwd: root, signal, timeout });
  }

  async function plain(cwd: string, args: string[], signal: AbortSignal | undefined): Promise<Result> {
    const root = requireRoot(cwd);
    const result = await run(root, args, signal, TOOL_TIMEOUT_MS);
    return text(formatPlain(result, MAX_LINES), { exit: result.code });
  }

  pi.on("before_agent_start", async (event, ctx) => {
    const root = findProjectRoot(ctx.cwd);
    if (!root) return;
    const sections = event.systemPromptOptions?.sections;
    if (sections) {
      sections.odoo19 = projectContext(root);
      return;
    }
    return { systemPrompt: `${event.systemPrompt}\n\n<odoo19>\n${projectContext(root)}\n</odoo19>` };
  });

  pi.registerTool({
    name: "odoo19_test_module",
    label: "Odoo 19 test module",
    description:
      "Run one Odoo 19 module's tests on its guarded test database (reset first). Returns the result line and " +
      "failures with the end of each traceback; full logs stay under dev/logs/odoo19.",
    promptSnippet: "Run an Odoo 19 module's tests and get only the result and failures",
    promptGuidelines: ["Use odoo19_test_module instead of running odoo-bin --test-tags through bash."],
    parameters: Type.Object({
      module: Type.String({ description: "Technical module name" }),
      database: Type.Optional(Type.String({ description: "Test database; defaults to the profile's test database" })),
      maxFailures: Type.Optional(Type.Integer({ minimum: 0, maximum: 50, default: 10 })),
      traceLines: Type.Optional(Type.Integer({ minimum: 0, maximum: 40, default: 6 })),
    }),
    async execute(_id, params, signal, _onUpdate, ctx) {
      const root = requireRoot(ctx.cwd);
      const result = await run(root, testModuleArgs(params), signal, TEST_TIMEOUT_MS);
      const options = { maxFailures: params.maxFailures ?? 10, traceLines: params.traceLines ?? 6 };
      return text(formatTestRun(params.module, result, readLog, options, MAX_LINES), { exit: result.code });
    },
  });

  pi.registerTool({
    name: "odoo19_module_status",
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
