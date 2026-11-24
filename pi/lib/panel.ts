// The action panel's flow (S6): every decision between opening it and recording the result, with
// the Pi effects injected (pi.exec, the dialogs, the overlay, appendEntry), so it is tested without
// Pi. pi/extensions/oasis.ts only adapts ctx.ui and pi to these interfaces. No Pi imports.
import { withHeartbeat } from "./heartbeat.ts";
import {
  type Answers, askInputs, type Catalog, confirmRun, fillTemplate, type FormSpec, type MenuEntry, menuHeader, menuOutput,
  parseCatalog, type PickerChoice, type Prompter, RUN_ACTION, type ServerState, serverLine, shellJoin, sources,
  terminalCommand,
} from "./menu.ts";
import { nativeCommands, printCommandArgv } from "./native.ts";
import type { CoreResult } from "./tools.ts";

const HEARTBEAT_MS = 15 * 1000;
const NON_TUI = "oasis menu: the action panel needs the interactive terminal UI; run `oasis menu` in a terminal.";
const TERMINAL_ONLY = "terminal only: run it in a terminal, or use oasis menu there";
const NOT_RUN = "could not run";

/** What a command is run for: the timeout the adapter gives it ("print": the native odoo-bin line, S4). */
export type ExecPurpose = "catalog" | "list" | "print" | "run";

/** The panel's dialogs: the Prompter questions plus the overlays (picker, live log) and the footer status. */
export interface PanelUi extends Prompter {
  /** The picker; `header` is the checkout, its server line (serverLine) and the default database (menuHeader). */
  pick(catalog: Catalog, header: string): Promise<PickerChoice | undefined>;
  /** The start / restart form (RunForm): its answers once the user chose Run, undefined otherwise. */
  form(spec: FormSpec): Promise<Answers | undefined>;
  /** The live view of the server log at `path`, refreshed while open; resolves when the user closes it. */
  follow(path: string, title: string): Promise<void>;
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
  /** The home directory the start / restart form shows as `~` in the native line. */
  home?: string;
  /** Records a result as a custom session entry (shown to the user, never sent to the model). */
  appendEntry(entry: MenuEntry): void;
  /** This checkout's server record (`runtime_state.py show`); may reject when it cannot be read. */
  serverState(root: string): Promise<ServerState>;
  /** Remembers the action that ran with its answers, for Repeat (`runtime_state.py remember`); may reject. */
  remember(root: string, action: string, answers: Answers): Promise<void>;
  heartbeatMs?: number;
}

/** A failure already shown to the user (entry and notice): stops the flow without another notice. */
class Reported extends Error {}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * The panel, opened by the shortcut and `/oasis menu`: one action at a time. It reads the catalog,
 * lets the user pick an action (or Repeat the last one), asks its inputs (the start / restart flow
 * in one form) and confirmation with the filled command, runs it in the project root, records the
 * command with its output as an entry and remembers the action. A command that cannot be started is
 * recorded the same way, with the error as output. The start / restart form shows the native
 * odoo-bin line (`start --print-command`, read in the background, S4); a read line also goes to
 * the run's entry, and a line that cannot be read changes nothing else.
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
    let server: string;
    try {
      server = serverLine(await effects.serverState(root));
    } catch (error) {
      server = serverLine({ serverError: message(error) });
    }
    const header = menuHeader(catalog, server);
    const picked = await ui.pick(catalog, header);
    if (!picked) return;
    const { action, answers: repeated } = picked;
    if (action.terminal_only) {
      effects.appendEntry({ label: action.label, command: terminalCommand(action), note: TERMINAL_ONLY, output: "" });
      return;
    }
    if (action.kind === "log" && !effects.exists(catalog.server_log)) {
      ui.notify(`oasis menu: no server log yet: ${catalog.server_log}`, "warning");
      return;
    }
    if (action.follow) {
      // A live view, not a run: nothing is executed or recorded.
      await ui.follow(catalog.server_log, action.label);
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
    let answers: Answers | null | undefined;
    // The native lines the start / restart form shows; never an entry or a notice of their own.
    const native = action.id === RUN_ACTION ? nativeCommands((argv) => effects.exec(argv, root, "print")) : undefined;
    if (native) {
      // One form asks, previews and confirms; a repeat opens it at the confirmation.
      const databases = repeated ? [] : await choices("databases");
      answers = await ui.form({
        catalog, action, header, databases, native, ...(effects.home ? { home: effects.home } : {}),
        ...(repeated ? { answers: repeated } : {}),
      });
    } else {
      answers = repeated ? { ...repeated } : await askInputs(action, ui, choices);
    }
    if (!answers) {
      ui.notify("oasis menu: nothing ran.", "info");
      return;
    }
    // The panel wants compact output: menuOutput summarizes the run logs it names.
    const argv = fillTemplate(action, answers, true);
    const command = shellJoin(argv);
    if (action.id !== RUN_ACTION && !(await confirmRun(action, answers, command, ui, catalog))) {
      ui.notify("oasis menu: not confirmed, nothing ran.", "info");
      return;
    }
    // The native line of these answers, asked before the run (the form usually has it already).
    const nativeArgv = native ? printCommandArgv(action.command, argv) : null;
    const nativeLine = native && nativeArgv ? native.settled(nativeArgv) : Promise.resolve(null);
    setBusy(command);
    ui.notify(`oasis menu: running ${command}`, "info");
    ui.setStatus(`oasis: ${action.label}`);
    const result = await withHeartbeat(
      () => attempt(action.label, argv, root, "run", ui),
      (seconds) => ui.setStatus(`oasis: ${action.label} (${seconds} s)`),
      effects.heartbeatMs ?? HEARTBEAT_MS,
    );
    const nativeShown = await nativeLine;
    effects.appendEntry({
      label: action.label, command, exit: result.code, ...(nativeShown ? { native: nativeShown } : {}),
      output: menuOutput(action, answers, result, effects.readLog),
    });
    // Repeat (S6): never a user-run action (terminal-only and the live log never get here).
    if (!action.user_run) {
      try {
        await effects.remember(root, action.id, answers);
      } catch (error) {
        ui.notify(`oasis menu: could not remember this action: ${message(error)}`, "warning");
      }
    }
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
