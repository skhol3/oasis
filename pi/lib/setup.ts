// `/oasis setup`: install the subagent overlay template into the Gentle AI config home.
// Logic and filesystem only; the extension passes its environment and its UI dialogs.
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
  "oasis setup: the subagent overlay applies only to Gentle Shell, and this session is not running in it; nothing written.";

type Notify = (message: string, level?: "info" | "warning" | "error") => void;
export type SetupInput = {
  env: Record<string, string | undefined>;
  homedir: string;
  template: string;
  ui: { notify: Notify; confirm: (title: string, message: string) => Promise<boolean> };
};

// User-run only (no tool registers it): outside Gentle Shell say so and write nothing; in it,
// install or update the subagent overlay after confirmation.
export async function runSetup({ env, homedir, template, ui }: SetupInput): Promise<void> {
  try {
    if (!gentleShellHost(env)) {
      ui.notify(NOT_GENTLE_SHELL, "info");
      return;
    }
    const target = overlayTarget(configHome(env, homedir));
    const state = overlayState(template, target);
    if (state === "current") {
      ui.notify(`oasis setup: subagent overlay is up to date (${target})`, "info");
      return;
    }
    const verb = state === "missing" ? "Create" : "Update";
    const question = `${verb} ${target} so gentle-ai-worker and gentle-ai-verify get the oasis tools?`;
    if (!(await ui.confirm("oasis setup", question))) {
      ui.notify("oasis setup: nothing changed.", "info");
      return;
    }
    const result = installOverlay(template, target);
    if (result.state === "unchanged") {
      ui.notify(`oasis setup: subagent overlay is up to date (${target})`, "info");
      return;
    }
    ui.notify(
      `oasis setup: subagent overlay ${result.state} at ${target}. ` +
        "Start a new session or /reload for subagents to use it.",
      "info",
    );
  } catch (error) {
    ui.notify(`oasis setup failed: ${error instanceof Error ? error.message : String(error)}`, "error");
  }
}

// The session-start reminder, or null: none outside Gentle Shell, where /oasis setup writes nothing.
export function overlayReminder({ env, homedir, template }: Omit<SetupInput, "ui">): string | null {
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
