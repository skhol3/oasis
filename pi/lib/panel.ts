// The action panel's flow (S6): every decision between opening it and recording the result, with
// the Pi effects injected (pi.exec, the dialogs, the overlay, appendEntry), so it is tested without
// Pi. pi/extensions/oasis.ts only adapts ctx.ui and pi to these interfaces. No Pi imports.
import { withHeartbeat } from "./heartbeat.ts";
import {
  askInputs, type Catalog, type CatalogAction, confirmRun, fillTemplate, type MenuEntry, menuOutput, parseCatalog,
  type Prompter, shellJoin, sources, terminalCommand,
} from "./menu.ts";
import type { CoreResult } from "./tools.ts";

const HEARTBEAT_MS = 15 * 1000;
const NON_TUI = "oasis menu: the action panel needs the interactive terminal UI; run `oasis menu` in a terminal.";
const TERMINAL_ONLY = "terminal only: run it in a terminal, or use oasis menu there";
const NOT_RUN = "could not run";

/** What a command is run for: the timeout the adapter gives it. */
export type ExecPurpose = "catalog" | "list" | "run";

/** The panel's dialogs: the Prompter questions plus the overlay picker and the footer status. */
export interface PanelUi extends Prompter {
  pick(catalog: Catalog): Promise<CatalogAction | undefined>;
  setStatus(text: string | undefined): void;
}

export interface PanelContext {
  /** ctx.mode: the panel needs "tui" (overlays). */
  mode: string;
  cwd: string;
  ui: PanelUi;
}

export interface PanelEffects {
  projectRoot(cwd: string): Promise<string | null>;
  /** Why cwd is not an Odoo project (the extension's notProject text). */
  notProject(cwd: string): string;
  /** The command that prints the catalog (`oasis --project <root> menu --catalog`). */
  catalogArgv(root: string): string[];
  /** Runs argv without a shell in cwd; may reject when the program cannot be started. */
  exec(argv: string[], cwd: string, purpose: ExecPurpose): Promise<CoreResult>;
  exists(path: string): boolean;
  readLog(path: string): string;
  /** Records a result as a custom session entry (shown to the user, never sent to the model). */
  appendEntry(entry: MenuEntry): void;
  heartbeatMs?: number;
}

/** A failure already shown to the user (entry and notice): stops the flow without another notice. */
class Reported extends Error {}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * The panel, opened by the shortcut and `/oasis menu`: one action at a time. It reads the catalog,
 * lets the user pick an action, asks its inputs and confirmation, runs the filled command in the
 * project root and records the command with its output as an entry. A command that cannot be
 * started is recorded the same way, with the error as output.
 */
export function actionPanel(effects: PanelEffects): (ctx: PanelContext) => Promise<void> {
  let busy: string | null = null;

  async function attempt(
    label: string, argv: string[], root: string, purpose: ExecPurpose, ui: PanelUi,
  ): Promise<CoreResult> {
    try {
      return await effects.exec(argv, root, purpose);
    } catch (error) {
      const command = shellJoin(argv);
      effects.appendEntry({ label, command, note: NOT_RUN, output: message(error) });
      ui.notify(`oasis menu: ${NOT_RUN} ${command}: ${message(error)}`, "error");
      throw new Reported();
    }
  }

  async function flow(ctx: PanelContext, setBusy: (what: string) => void): Promise<void> {
    const ui = ctx.ui;
    const root = await effects.projectRoot(ctx.cwd);
    if (!root) {
      ui.notify(`Not an Odoo project: ${effects.notProject(ctx.cwd)}`, "warning");
      return;
    }
    const listed = await attempt("Read the action catalog", effects.catalogArgv(root), root, "catalog", ui);
    if (listed.code !== 0) {
      ui.notify(`oasis menu: ${listed.stderr.trim() || `exit ${listed.code}`}`, "error");
      return;
    }
    const catalog = parseCatalog(listed.stdout);
    const action = await ui.pick(catalog);
    if (!action) return;
    if (action.terminal_only) {
      effects.appendEntry({ label: action.label, command: terminalCommand(action), note: TERMINAL_ONLY, output: "" });
      return;
    }
    if (action.kind === "log" && !effects.exists(catalog.server_log)) {
      ui.notify(`oasis menu: no server log yet: ${catalog.server_log}`, "warning");
      return;
    }
    const choices = sources(catalog, {
      exec: (argv) => attempt("List the databases", argv, root, "list", ui),
      waiting: (text) => {
        ui.setStatus(text);
        if (text) ui.notify(text, "info");
      },
      notify: (text, level) => ui.notify(text, level),
    });
    const answers = await askInputs(action, ui, choices);
    if (!answers) {
      ui.notify("oasis menu: nothing ran.", "info");
      return;
    }
    // The panel wants compact output: menuOutput summarizes the run logs it names.
    const argv = fillTemplate(action, answers, true);
    const command = shellJoin(argv);
    if (!(await confirmRun(action, answers, command, ui))) {
      ui.notify("oasis menu: not confirmed, nothing ran.", "info");
      return;
    }
    setBusy(command);
    ui.notify(`oasis menu: running ${command}`, "info");
    ui.setStatus(`oasis: ${action.label}`);
    const result = await withHeartbeat(
      () => attempt(action.label, argv, root, "run", ui),
      (seconds) => ui.setStatus(`oasis: ${action.label} (${seconds} s)`),
      effects.heartbeatMs ?? HEARTBEAT_MS,
    );
    effects.appendEntry({
      label: action.label, command, exit: result.code, output: menuOutput(action, answers, result, effects.readLog),
    });
  }

  return async (ctx) => {
    if (ctx.mode !== "tui") {
      ctx.ui.notify(NON_TUI, "warning");
      return;
    }
    if (busy !== null) {
      ctx.ui.notify(`oasis menu: ${busy} is still in progress.`, "info");
      return;
    }
    busy = "the panel";
    try {
      await flow(ctx, (what) => {
        busy = what;
      });
    } catch (error) {
      if (!(error instanceof Reported)) ctx.ui.notify(`oasis menu failed: ${message(error)}`, "error");
    } finally {
      busy = null;
      ctx.ui.setStatus(undefined);
    }
  };
}
