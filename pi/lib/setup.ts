// `/odoo19 setup`: install the subagent overlay template into the Gentle AI config home.
// Pure logic and filesystem only; the extension owns confirmation and notifications.
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
