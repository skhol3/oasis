// Module lookup by manifest metadata: map functional names to technical module names. No Pi imports.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { listModules } from "./status.ts";

export const DEFAULT_LIMIT = 10;
const KEYS = ["name", "summary", "category"] as const;
// Short query tokens must match a word exactly; longer ones may match a word prefix ("prod" -> "production").
const PREFIX_MIN = 3;

export interface ManifestInfo {
  name?: string;
  summary?: string;
  category?: string;
}

export interface ModuleInfo extends ManifestInfo {
  technical: string;
}

function unescape(body: string): string {
  return body.replace(/\\(.)/gs, (_, char: string) => (char === "n" ? "\n" : char === "t" ? "\t" : char));
}

/** String values of `name`, `summary` and `category` in a __manifest__.py dict literal (first occurrence). */
export function parseManifest(text: string): ManifestInfo {
  const info: ManifestInfo = {};
  for (const key of KEYS) {
    const pattern = new RegExp(
      `['"]${key}['"]\\s*:\\s*(?:'''([\\s\\S]*?)'''|"""([\\s\\S]*?)"""|'((?:[^'\\\\\\n]|\\\\.)*)'|"((?:[^"\\\\\\n]|\\\\.)*)")`,
    );
    const match = pattern.exec(text);
    if (!match) continue;
    const body = match.slice(1).find((group) => group !== undefined) ?? "";
    info[key] = unescape(body).replace(/\s+/g, " ").trim();
  }
  return info;
}

/** Modules with their manifest metadata under the given addons roots; the first root wins on duplicates. */
export function loadModules(addonsRoots: string[]): ModuleInfo[] {
  const seen = new Set<string>();
  const modules: ModuleInfo[] = [];
  for (const root of addonsRoots) {
    for (const technical of listModules(root)) {
      if (seen.has(technical)) continue;
      seen.add(technical);
      let manifest: ManifestInfo = {};
      try {
        manifest = parseManifest(readFileSync(join(root, technical, "__manifest__.py"), "utf8"));
      } catch {
        // Unreadable manifest: keep the technical name only.
      }
      modules.push({ technical, ...manifest });
    }
  }
  return modules;
}

function tokens(text: string): string[] {
  return text.toLowerCase().match(/[a-z0-9]+/g) ?? [];
}

/**
 * Rank modules by the number of distinct query tokens found in the technical name (split on `_`),
 * manifest name, summary and category. Score 0 is dropped; ties sort by technical name.
 */
export function findModules(
  modules: ModuleInfo[],
  query: string,
  limit: number = DEFAULT_LIMIT,
): { matches: ModuleInfo[]; total: number } {
  const wanted = [...new Set(tokens(query))];
  if (!wanted.length) return { matches: [], total: 0 };
  const scored: { module: ModuleInfo; score: number }[] = [];
  for (const module of modules) {
    const words = new Set(
      [module.technical, module.name, module.summary, module.category].flatMap((text) => tokens(text ?? "")),
    );
    const score = wanted.filter((token) =>
      words.has(token) || (token.length >= PREFIX_MIN && [...words].some((word) => word.startsWith(token))),
    ).length;
    if (score > 0) scored.push({ module, score });
  }
  scored.sort((a, b) => b.score - a.score || (a.module.technical < b.module.technical ? -1 : 1));
  return { matches: scored.slice(0, Math.max(0, limit)).map(({ module }) => module), total: scored.length };
}

/** `matches: shown/total` then one `technical — name` line per match (no dash without a name). */
export function formatModules(matches: ModuleInfo[], total: number): string {
  return [
    `matches: ${matches.length}/${total}`,
    ...matches.map((module) => (module.name ? `${module.technical} — ${module.name}` : module.technical)),
  ].join("\n");
}
