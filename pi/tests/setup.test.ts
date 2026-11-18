import { test } from "node:test";
import assert from "node:assert/strict";
import {
  mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, symlinkSync, utimesSync, writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { configHome, installOverlay, overlayState, overlayTarget } from "../lib/setup.ts";

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
