import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { findModules, formatModules, loadModules, parseManifest } from "../lib/modules.ts";

test("parseManifest reads name, summary and category strings without evaluating the file", () => {
  const manifest = `# -*- coding: utf-8 -*-
{
    'name': 'Mass Production Order',
    "summary"  :
        "Plan the day's production in one order",
    'category' :'Manufacturing/Manufacturing',
    'version': '19.0.1.0.0',
    'depends': ['mrp'],
    'assets': {'web.assets_backend': ['oa_x/static/src/**/*']},
}
`;
  assert.deepEqual(parseManifest(manifest), {
    name: "Mass Production Order",
    summary: "Plan the day's production in one order",
    category: "Manufacturing/Manufacturing",
  });
  assert.deepEqual(parseManifest(`{'name': 'It\\'s "quoted"'}`), { name: `It's "quoted"` });
  assert.deepEqual(parseManifest("{'depends': ['base']}"), {});
});

const MODULES = [
  { technical: "oa_mrp_daily_report", name: "Daily Report", category: "Reporting" },
  { technical: "oa_mrp_mass_production_order", name: "Mass Production Order", summary: "Group production orders" },
  { technical: "oa_sale_margin", name: "Sale Margin" },
  { technical: "coffee_mass" },
];

test("findModules ranks by distinct query tokens found and keeps partial matches", () => {
  const { matches, total } = findModules(MODULES, "daily mass production", 10);
  assert.deepEqual(
    matches.map((module) => module.technical),
    ["oa_mrp_mass_production_order", "coffee_mass", "oa_mrp_daily_report"],
  );
  assert.equal(total, 3);
});

test("findModules sorts equal scores by technical name, cuts to the limit and ignores non-matches", () => {
  const { matches, total } = findModules(MODULES, "MRP!", 1);
  assert.deepEqual(matches.map((module) => module.technical), ["oa_mrp_daily_report"]);
  assert.equal(total, 2);
  assert.deepEqual(findModules(MODULES, "inventory", 10), { matches: [], total: 0 });
  assert.deepEqual(findModules(MODULES, "  --  ", 10), { matches: [], total: 0 });
  assert.equal(findModules(Array.from({ length: 12 }, (_, i) => ({ technical: `m_${i}` })), "m").matches.length, 10);
});

test("formatModules puts the match count first and the manifest name after a dash", () => {
  const { matches, total } = findModules(MODULES, "daily mass production", 2);
  assert.equal(
    formatModules(matches, total),
    "matches: 2/3\noa_mrp_mass_production_order — Mass Production Order\ncoffee_mass",
  );
  assert.equal(formatModules([], 0), "matches: 0/0");
});

test("loadModules reads each manifest under the addons roots and keeps the first duplicate", () => {
  const root = mkdtempSync(join(tmpdir(), "oasis-pi-"));
  try {
    const first = join(root, "addons");
    const second = join(root, "vendor");
    for (const [dir, module, manifest] of [
      [first, "coffee", "{'name': 'Coffee'}"],
      [first, "notes", "not a dict"],
      [second, "coffee", "{'name': 'Vendor Coffee'}"],
      [second, "roast", "{'name': 'Roast', 'category': 'Manufacturing'}"],
    ]) {
      mkdirSync(join(dir, module), { recursive: true });
      writeFileSync(join(dir, module, "__manifest__.py"), manifest);
    }
    mkdirSync(join(first, "static"));
    assert.deepEqual(loadModules([first, second, join(root, "missing")]), [
      { technical: "coffee", name: "Coffee" },
      { technical: "notes" },
      { technical: "roast", name: "Roast", category: "Manufacturing" },
    ]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
