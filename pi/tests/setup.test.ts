import { test } from "node:test";
import assert from "node:assert/strict";
import {
  mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, symlinkSync, utimesSync, writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import {
  configHome, gentleShellHost, installOverlay, NOT_GENTLE_SHELL, overlayReminder, overlayState, overlayTarget, runSetup,
} from "../lib/setup.ts";

const TEMPLATE_BODY = '{\n  "gentle-ai-worker": { "add": ["odoo19_test_module"] }\n}\n';

function scratch(): string {
  return mkdtempSync(join(tmpdir(), "oasis-setup-"));
}

function withScratch(body: (dir: string, template: string) => void): void {
  const dir = scratch();
  try {
    const template = join(dir, "template.json");
    writeFileSync(template, TEMPLATE_BODY);
    body(dir, template);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

test("configHome uses an absolute GENTLE_PI_CONFIG_HOME", () => {
  assert.equal(configHome({ GENTLE_PI_CONFIG_HOME: "/x/cfg" }, "/home/u"), "/x/cfg");
});

test("configHome defaults to ~/.gentle-shell/gentle-ai", () => {
  assert.equal(configHome({}, "/home/u"), "/home/u/.gentle-shell/gentle-ai");
  assert.equal(configHome({ GENTLE_PI_CONFIG_HOME: "" }, "/home/u"), "/home/u/.gentle-shell/gentle-ai");
});

test("configHome ignores a relative GENTLE_PI_CONFIG_HOME", () => {
  assert.equal(configHome({ GENTLE_PI_CONFIG_HOME: "rel/cfg" }, "/home/u"), "/home/u/.gentle-shell/gentle-ai");
});

test("overlayTarget is agent-overlays.d/oasis.json under the config home", () => {
  assert.equal(overlayTarget("/x/cfg"), "/x/cfg/agent-overlays.d/oasis.json");
});

test("overlayState: missing, outdated, current, formatting-only difference and invalid JSON", () => {
  withScratch((dir, template) => {
    const target = join(dir, "cfg", "agent-overlays.d", "oasis.json");
    assert.equal(overlayState(template, target), "missing");
    mkdirSync(join(dir, "cfg", "agent-overlays.d"), { recursive: true });
    writeFileSync(target, '{"gentle-ai-worker": {"add": ["other"]}}');
    assert.equal(overlayState(template, target), "outdated");
    writeFileSync(target, TEMPLATE_BODY);
    assert.equal(overlayState(template, target), "current");
    writeFileSync(target, '{"gentle-ai-worker":{"add":["odoo19_test_module"]}}');
    assert.equal(overlayState(template, target), "current");
    writeFileSync(target, "{not json");
    assert.equal(overlayState(template, target), "outdated");
  });
});

test("installOverlay creates the directory with mode 0700 and the template bytes", () => {
  withScratch((dir, template) => {
    const overlays = join(dir, "cfg", "agent-overlays.d");
    const target = join(overlays, "oasis.json");
    assert.deepEqual(installOverlay(template, target), { state: "created" });
    assert.equal(readFileSync(target, "utf8"), TEMPLATE_BODY);
    assert.equal(statSync(overlays).mode & 0o777, 0o700);
    assert.deepEqual(readdirSync(overlays), ["oasis.json"]);
    assert.equal(overlayState(template, target), "current");
  });
});

test("installOverlay updates an outdated target and leaves siblings untouched", () => {
  withScratch((dir, template) => {
    const overlays = join(dir, "cfg", "agent-overlays.d");
    mkdirSync(overlays, { recursive: true });
    const target = join(overlays, "oasis.json");
    const sibling = join(overlays, "other.json");
    writeFileSync(target, "{}");
    writeFileSync(sibling, '{"a": {"add": ["b"]}}');
    assert.deepEqual(installOverlay(template, target), { state: "updated" });
    assert.equal(readFileSync(target, "utf8"), TEMPLATE_BODY);
    assert.equal(readFileSync(sibling, "utf8"), '{"a": {"add": ["b"]}}');
    assert.deepEqual(readdirSync(overlays).sort(), ["oasis.json", "other.json"]);
  });
});

test("installOverlay leaves a current target's bytes and mtime unchanged", () => {
  withScratch((dir, template) => {
    const overlays = join(dir, "cfg", "agent-overlays.d");
    mkdirSync(overlays, { recursive: true });
    const target = join(overlays, "oasis.json");
    const formatted = '{"gentle-ai-worker":{"add":["odoo19_test_module"]}}';
    writeFileSync(target, formatted);
    const past = new Date("2020-01-01T00:00:00Z");
    utimesSync(target, past, past);
    assert.deepEqual(installOverlay(template, target), { state: "unchanged" });
    assert.equal(readFileSync(target, "utf8"), formatted);
    assert.equal(statSync(target).mtimeMs, past.getTime());
    assert.deepEqual(readdirSync(overlays), ["oasis.json"]);
  });
});

test("installOverlay refuses a symlink target and leaves the file it points to unchanged", () => {
  withScratch((dir, template) => {
    const overlays = join(dir, "cfg", "agent-overlays.d");
    mkdirSync(overlays, { recursive: true });
    const pointed = join(dir, "elsewhere.json");
    writeFileSync(pointed, "{}");
    const target = join(overlays, "oasis.json");
    symlinkSync(pointed, target);
    assert.throws(() => installOverlay(template, target), /symlink/);
    assert.equal(readFileSync(pointed, "utf8"), "{}");
    assert.deepEqual(readdirSync(overlays), ["oasis.json"]);
  });
});

test("installOverlay refuses a directory target", () => {
  withScratch((dir, template) => {
    const target = join(dir, "cfg", "agent-overlays.d", "oasis.json");
    mkdirSync(target, { recursive: true });
    assert.throws(() => installOverlay(template, target), /directory/);
    assert.deepEqual(readdirSync(target), []);
  });
});

// S7: the overlay is read only by Gentle Shell's subagents. Its launcher sets
// PI_PROGRAM_STATUS_APP=gentle-shell; an absolute GENTLE_PI_CONFIG_HOME names its config home.
const GENTLE_SHELL = { PI_PROGRAM_STATUS_APP: "gentle-shell" };

function fakeUi(answers: boolean[] = []) {
  const notices: { message: string; level: string | undefined }[] = [];
  const confirms: string[] = [];
  return {
    notices, confirms,
    ui: {
      notify: (message: string, level?: "info" | "warning" | "error") => notices.push({ message, level }),
      confirm: async (_title: string, message: string) => {
        confirms.push(message);
        assert.ok(answers.length > 0, `unexpected confirm: ${message}`);
        return answers.shift() as boolean;
      },
    },
  };
}

function tree(dir: string): string[] {
  return readdirSync(dir, { recursive: true }).map(String).sort();
}

test("gentleShellHost: the launcher marker or an absolute GENTLE_PI_CONFIG_HOME", () => {
  assert.equal(gentleShellHost(GENTLE_SHELL), true);
  assert.equal(gentleShellHost({ GENTLE_PI_CONFIG_HOME: "/x/cfg" }), true);
  assert.equal(gentleShellHost({}), false);
  assert.equal(gentleShellHost({ PI_PROGRAM_STATUS_APP: "" }), false);
  assert.equal(gentleShellHost({ PI_PROGRAM_STATUS_APP: "pi" }), false);
  assert.equal(gentleShellHost({ GENTLE_PI_CONFIG_HOME: "rel/cfg" }), false);
  assert.equal(gentleShellHost({ GENTLE_SHELL_CONFIG_HOME: "/x/cfg" }), false);
});

test("runSetup outside Gentle Shell says the overlay is Gentle Shell only and writes nothing", async () => {
  const dir = scratch();
  try {
    const template = join(dir, "template.json");
    writeFileSync(template, TEMPLATE_BODY);
    const home = join(dir, "home");
    mkdirSync(home);
    // Even a leftover ~/.gentle-shell/gentle-ai does not make a vanilla Pi session Gentle Shell.
    mkdirSync(join(home, ".gentle-shell", "gentle-ai"), { recursive: true });
    const before = tree(dir);
    const run = fakeUi();
    await runSetup({ env: {}, homedir: home, template, ui: run.ui });
    assert.deepEqual(run.notices, [{ message: NOT_GENTLE_SHELL, level: "info" }]);
    assert.equal(NOT_GENTLE_SHELL,
      "oasis setup: the subagent overlay applies only to Gentle Shell, and this session is not running in it; nothing written.");
    assert.deepEqual(run.confirms, []);
    assert.deepEqual(tree(dir), before);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("runSetup in Gentle Shell still asks, then creates the overlay under the config home", async () => {
  const dir = scratch();
  try {
    const template = join(dir, "template.json");
    writeFileSync(template, TEMPLATE_BODY);
    const home = join(dir, "home");
    const target = join(home, ".gentle-shell", "gentle-ai", "agent-overlays.d", "oasis.json");
    const run = fakeUi([true]);
    await runSetup({ env: GENTLE_SHELL, homedir: home, template, ui: run.ui });
    assert.deepEqual(run.confirms, [`Create ${target} so gentle-ai-worker and gentle-ai-verify get the oasis tools?`]);
    assert.deepEqual(run.notices, [{
      message: `oasis setup: subagent overlay created at ${target}. Start a new session or /reload for subagents to use it.`,
      level: "info",
    }]);
    assert.equal(readFileSync(target, "utf8"), TEMPLATE_BODY);
    const again = fakeUi();
    await runSetup({ env: GENTLE_SHELL, homedir: home, template, ui: again.ui });
    assert.deepEqual(again.notices, [{ message: `oasis setup: subagent overlay is up to date (${target})`, level: "info" }]);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("runSetup in Gentle Shell writes nothing when the user declines", async () => {
  const dir = scratch();
  try {
    const template = join(dir, "template.json");
    writeFileSync(template, TEMPLATE_BODY);
    const before = tree(dir);
    const run = fakeUi([false]);
    await runSetup({ env: { GENTLE_PI_CONFIG_HOME: join(dir, "cfg") }, homedir: join(dir, "home"), template, ui: run.ui });
    assert.equal(run.confirms.length, 1);
    assert.deepEqual(run.notices, [{ message: "oasis setup: nothing changed.", level: "info" }]);
    assert.deepEqual(tree(dir), before);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("overlayReminder: none outside Gentle Shell; missing, outdated or none in it", () => {
  withScratch((dir, template) => {
    const home = join(dir, "home");
    const target = join(home, ".gentle-shell", "gentle-ai", "agent-overlays.d", "oasis.json");
    assert.equal(overlayReminder({ env: {}, homedir: home, template }), null);
    assert.equal(overlayReminder({ env: GENTLE_SHELL, homedir: home, template }),
      "oasis: subagents do not have the oasis tools yet; run /oasis setup");
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, "{}");
    assert.equal(overlayReminder({ env: {}, homedir: home, template }), null);
    assert.equal(overlayReminder({ env: GENTLE_SHELL, homedir: home, template }),
      "oasis: overlay is outdated; run /oasis setup");
    writeFileSync(target, TEMPLATE_BODY);
    assert.equal(overlayReminder({ env: GENTLE_SHELL, homedir: home, template }), null);
  });
});
