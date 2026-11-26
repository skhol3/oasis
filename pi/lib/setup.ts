// `/oasis setup`: the workspace status and the plan of `oasis setup` for the checkout (never applied), and the
// subagent overlay template installed into the Gentle AI config home. Logic and filesystem only; the extension
// passes its environment, the CLI runner and its UI.
import { isDeepStrictEqual } from "node:util";
import { lstatSync, mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { basename, dirname, isAbsolute, join } from "node:path";

export type OverlayState = "missing" | "outdated" | "current";
export type InstallState = "created" | "updated" | "unchanged";

// Gentle AI config home: an absolute GENTLE_PI_CONFIG_HOME, else ~/.gentle-shell/gentle-ai.
export function configHome(env: Record<string, string | undefined>, homedir: string): string {
  const value = env.GENTLE_PI_CONFIG_HOME;
  if (value && isAbsolute(value)) return value;
  return join(homedir, ".gentle-shell", "gentle-ai");
}

export function overlayTarget(home: string): string {
  return join(home, "agent-overlays.d", "oasis.json");
}

// Only Gentle Shell's subagents read the overlay. Its launcher sets PI_PROGRAM_STATUS_APP=gentle-shell
// for every Pi it starts (documented in Gentle Shell's docs/gentle-shell.md, read by its own
// extensions); an absolute GENTLE_PI_CONFIG_HOME names the config home explicitly. A leftover
// ~/.gentle-shell directory proves nothing: vanilla Pi runs on the same machine.
export function gentleShellHost(env: Record<string, string | undefined>): boolean {
  if (env.PI_PROGRAM_STATUS_APP === "gentle-shell") return true;
  const value = env.GENTLE_PI_CONFIG_HOME;
  return Boolean(value && isAbsolute(value));
}

export const NOT_GENTLE_SHELL =
  "subagent overlay: it applies only to Gentle Shell, and this session is not running in it; nothing written.";

type Notify = (message: string, level?: "info" | "warning" | "error") => void;
export type CommandResult = { code: number; stdout: string; stderr: string };
// What one CLI call gave: its result, or why it could not run.
export type Outcome = CommandResult | { error: string };
export type SetupInput = {
  env: Record<string, string | undefined>;
  homedir: string;
  template: string;
  // Runs `oasis <args>` for the session's checkout (the extension adds --project when it knows the root).
  run: (args: string[]) => Promise<CommandResult>;
  // Shows the report in the session.
  show: (report: string) => void;
  ui: { notify: Notify };
};

const STATUS_ARGS = ["status", "--json"];
const PLAN_ARGS = ["setup", "--plan", "--json"];
const RELOAD = "start a new session or /reload for subagents to use it.";

async function attempt(call: () => Promise<CommandResult>): Promise<Outcome> {
  try {
    return await call();
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

// The overlay step of /oasis setup, done without asking (v0.16.0 L3: the overlay installs itself and says so):
// outside Gentle Shell nothing is written; in it the template is installed when missing or outdated.
export function overlayStep(env: Record<string, string | undefined>, homedir: string, template: string): string {
  if (!gentleShellHost(env)) return NOT_GENTLE_SHELL;
  const target = overlayTarget(configHome(env, homedir));
  try {
    const { state } = installOverlay(template, target);
    if (state === "unchanged") return `subagent overlay: already installed, nothing to do (${target}).`;
    return `subagent overlay: ${state === "created" ? "installed" : "updated"} at ${target}; ${RELOAD}`;
  } catch (error) {
    return `subagent overlay: not installed (${error instanceof Error ? error.message : String(error)})`;
  }
}

type Parsed = { value: Record<string, unknown> } | { problem: string };

// The JSON object a CLI call printed, or why there is none: the error, the command's stderr (exit != 0) or no JSON.
function parsed(outcome: Outcome, refusal: boolean): Parsed {
  if ("error" in outcome) return { problem: `unavailable (${outcome.error})` };
  if (outcome.code !== 0) {
    const message = outcome.stderr.trim();
    if (!message) return { problem: `unavailable (exit ${outcome.code})` };
    return { problem: refusal ? message.split("\n").join("\n  ") : `unavailable (${message.split("\n").pop()})` };
  }
  try {
    const value = JSON.parse(outcome.stdout);
    if (value && typeof value === "object" && !Array.isArray(value)) return { value };
  } catch {
    // Reported below.
  }
  return { problem: "unavailable (no JSON output)" };
}

function detail(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.length ? value.map(String).join(", ") : "none";
  return JSON.stringify(value);
}

function counted(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

type Check = { ready?: unknown; detail?: unknown };
type Question = { id?: unknown; text?: unknown; flag?: unknown; recommended?: unknown };

// The /oasis setup report (v0.16.0 S4.10): the workspace status (`oasis status --json`), the plan of `oasis setup`
// for the checkout (`oasis setup --plan --json`: its changes and open questions; nothing is applied) and what was
// done with the subagent overlay.
export function formatSetupReport({ status, plan, overlay }: { status: Outcome; plan: Outcome; overlay: string }):
  string {
  const state = parsed(status, false);
  const planned = parsed(plan, true);
  const checkout = ("value" in planned && typeof planned.value.checkout === "string" && planned.value.checkout)
    || ("value" in state && typeof state.value.project === "string" && state.value.project) || "";
  const lines = [`oasis setup: ${checkout || "the current checkout"}`];
  if ("problem" in state) {
    lines.push(`status (oasis status --json): ${state.problem}`);
  } else {
    const checks = (state.value.checks ?? {}) as Record<string, Check>;
    const ready = Array.isArray(state.value.ready) ? state.value.ready.map(String) : [];
    const missing = Array.isArray(state.value.missing) ? state.value.missing.map(String) : [];
    lines.push(
      "status (oasis status --json):",
      `  ready: ${ready.length ? ready.join(", ") : "none"}`,
      `  missing: ${missing.length ? missing.map((name) => `${name} (${detail(checks[name]?.detail)})`).join(", ") : "none"}`,
      `  next: ${typeof state.value.next === "string" ? state.value.next : "none"}`,
    );
  }
  if ("problem" in planned) {
    lines.push(`setup plan (oasis setup --plan --json): ${planned.problem}`);
  } else {
    const changes = Array.isArray(planned.value.changes) ? planned.value.changes as { summary?: unknown }[] : [];
    const open = Array.isArray(planned.value.open) ? planned.value.open.map(String) : [];
    const questions = Array.isArray(planned.value.questions) ? planned.value.questions as Question[] : [];
    const parts = [...(changes.length ? [counted(changes.length, "change")] : []),
      ...(open.length ? [counted(open.length, "open question")] : [])];
    lines.push(`setup plan (oasis setup --plan --json): ${parts.length ? parts.join(", ") : "nothing to set up"}`);
    for (const change of changes) lines.push(`  - ${detail(change.summary)}`);
    for (const id of open) {
      const question = questions.find((item) => item.id === id) ?? {};
      const recommended = typeof question.recommended === "string"
        ? `recommended: ${question.recommended}` : "no recommended answer";
      lines.push(`  open question ${id}: ${detail(question.text ?? id)} (${detail(question.flag ?? "")}; ${recommended})`);
    }
    const apply = `oasis --project ${checkout} setup --apply`;
    if (open.length) lines.push(`  nothing applied: answer the open questions, then run ${apply}`);
    else if (changes.length) lines.push(`  nothing applied: ${apply} applies it`);
  }
  lines.push(overlay);
  return lines.join("\n");
}

// User-run only (no tool registers it): shows the workspace status and the plan of `oasis setup` for the
// checkout, never applies setup, and installs the subagent overlay in Gentle Shell (overlayStep).
export async function runSetup({ env, homedir, template, run, show, ui }: SetupInput): Promise<void> {
  try {
    const status = await attempt(() => run(STATUS_ARGS));
    const plan = await attempt(() => run(PLAN_ARGS));
    show(formatSetupReport({ status, plan, overlay: overlayStep(env, homedir, template) }));
  } catch (error) {
    ui.notify(`oasis setup failed: ${error instanceof Error ? error.message : String(error)}`, "error");
  }
}

// The session-start reminder, or null: none outside Gentle Shell, where /oasis setup writes nothing.
export function overlayReminder({ env, homedir, template }: Pick<SetupInput, "env" | "homedir" | "template">):
  string | null {
  if (!gentleShellHost(env)) return null;
  const state = overlayState(template, overlayTarget(configHome(env, homedir)));
  if (state === "current") return null;
  const problem = state === "missing" ? "subagents do not have the oasis tools yet" : "overlay is outdated";
  return `oasis: ${problem}; run /oasis setup`;
}

function parse(path: string): { ok: true; value: unknown } | { ok: false } {
  try {
    return { ok: true, value: JSON.parse(readFileSync(path, "utf8")) };
  } catch {
    return { ok: false };
  }
}

function exists(path: string): boolean {
  try {
    lstatSync(path);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
    throw error;
  }
}

// Compares parsed JSON, so formatting differences count as current; an unreadable target is outdated.
export function overlayState(templatePath: string, targetPath: string): OverlayState {
  if (!exists(targetPath)) return "missing";
  const template = JSON.parse(readFileSync(templatePath, "utf8"));
  const target = parse(targetPath);
  return target.ok && isDeepStrictEqual(target.value, template) ? "current" : "outdated";
}

// Writes the template bytes atomically (temp file in the same directory, then rename).
// Touches no other file in the directory; refuses a symlink or directory target.
export function installOverlay(templatePath: string, targetPath: string): { state: InstallState } {
  let existed = false;
  try {
    const stat = lstatSync(targetPath);
    if (stat.isSymbolicLink()) throw new Error(`Refusing to write ${targetPath}: it is a symlink.`);
    if (stat.isDirectory()) throw new Error(`Refusing to write ${targetPath}: it is a directory.`);
    existed = true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  const bytes = readFileSync(templatePath);
  JSON.parse(bytes.toString("utf8"));
  if (existed && overlayState(templatePath, targetPath) === "current") return { state: "unchanged" };
  const dir = dirname(targetPath);
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  const temp = join(dir, `.${basename(targetPath)}.${process.pid}.${randomBytes(6).toString("hex")}.tmp`);
  writeFileSync(temp, bytes, { flag: "wx", mode: 0o600 });
  try {
    renameSync(temp, targetPath);
  } catch (error) {
    try {
      unlinkSync(temp);
    } catch {
      // The temp file is ours; leaving it is harmless if removal fails.
    }
    throw error;
  }
  return { state: existed ? "updated" : "created" };
}
