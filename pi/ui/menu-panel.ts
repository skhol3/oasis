// The action panel's TUI pieces, on the public Pi extension API only: the group and action picker,
// the start / restart form and the live server log view, shown with ctx.ui.custom as overlays, and
// the renderer of the result entries. The logic they show (rows, selection, scrolling, form steps
// and lines, entry lines, log lines, header) is in lib/menu.ts, tested without Pi.
import type { EntryRenderer, KeybindingsManager, Theme } from "@earendil-works/pi-coding-agent";
import {
  Box, type Component, decodeKittyPrintable, type Keybinding, Text, truncateToWidth, type TUI, visibleWidth,
} from "@earendil-works/pi-tui";
import {
  type Answers, type Catalog, type CatalogAction, entryLines, fillTemplate, type FormLine, lastLines, logView,
  type MenuEntry, moveSelection, type PickerChoice, type PickerRow, pickerRows, type RunForm, shellJoin,
  terminalCommand, visibleStart,
} from "../lib/menu.ts";

export const MENU_ENTRY = "oasis-menu-result";
const PREVIEW_LINES = 20;
// Border, title, blank line, command preview, hint and border around the list and the header lines.
const CHROME_ROWS = 6;
// The start / restart form: border with title, hint and border around its lines.
const FORM_CHROME_ROWS = 3;
// The live log view: border with title, blank line, hint and border around the lines.
const LOG_CHROME_ROWS = 5;
/** How often the live log view reads the end of the log again while it is open. */
export const LOG_REFRESH_MS = 1000;

/** What the highlighted action would run, as the panel shows it under the list (filled for Repeat). */
function preview(action: CatalogAction, answers?: Answers): string {
  if (action.kind === "log") return shellJoin(action.argv.filter((token): token is string => typeof token === "string"));
  if (answers) return shellJoin(fillTemplate(action, answers, true));
  return terminalCommand(action);
}

/** The group and action picker: up/down/page keys move, enter chooses, escape closes. */
export class MenuPanel implements Component {
  private readonly catalog: Catalog;
  private readonly header: string;
  private readonly tui: TUI;
  private readonly theme: Theme;
  private readonly keybindings: KeybindingsManager;
  private readonly done: (choice: PickerChoice | undefined) => void;
  private readonly rows: PickerRow[];
  private selected: number;
  private start = 0;
  private cache: { width: number; lines: string[] } | undefined;

  constructor(
    catalog: Catalog, header: string, tui: TUI, theme: Theme, keybindings: KeybindingsManager,
    done: (choice: PickerChoice | undefined) => void,
  ) {
    this.catalog = catalog;
    this.header = header;
    this.tui = tui;
    this.theme = theme;
    this.keybindings = keybindings;
    this.done = done;
    this.rows = pickerRows(catalog);
    this.selected = moveSelection(this.rows, 0, 0);
  }

  private listHeight(): number {
    return Math.max(5, Math.floor(this.tui.terminal.rows * 0.9) - CHROME_ROWS - this.header.split("\n").length);
  }

  handleInput(data: string): void {
    const page = this.listHeight();
    const moves: [Keybinding, number][] = [
      ["tui.select.up", -1], ["tui.select.down", 1], ["tui.select.pageUp", -page], ["tui.select.pageDown", page],
    ];
    if (this.keybindings.matches(data, "tui.select.confirm")) {
      const row = this.rows[this.selected];
      this.done(row?.action ? { action: row.action, ...(row.answers ? { answers: row.answers } : {}) } : undefined);
      return;
    }
    if (this.keybindings.matches(data, "tui.select.cancel")) {
      this.done(undefined);
      return;
    }
    const move = moves.find(([binding]) => this.keybindings.matches(data, binding));
    if (!move) return;
    this.selected = moveSelection(this.rows, this.selected, move[1]);
    this.invalidate();
    this.tui.requestRender();
  }

  render(width: number): string[] {
    if (this.cache?.width === width) return this.cache.lines;
    const theme = this.theme;
    const inner = Math.max(1, width - 4);
    const frame = (content: string) => {
      const fitted = truncateToWidth(content, inner);
      const pad = " ".repeat(Math.max(0, inner - visibleWidth(fitted)));
      return `${theme.fg("border", "│")} ${fitted}${pad} ${theme.fg("border", "│")}`;
    };
    const height = this.listHeight();
    this.start = visibleStart(this.rows.length, this.selected, height, this.start);
    const title = truncateToWidth(`─ oasis menu: ${this.catalog.project} `, inner + 2);
    const lines = [theme.fg("border", `╭${title}${"─".repeat(Math.max(0, inner + 2 - visibleWidth(title)))}╮`)];
    for (const line of this.header.split("\n")) {
      lines.push(frame(theme.fg(line.startsWith("server: running") ? "success" : "muted", line)));
    }
    for (const [offset, row] of this.rows.slice(this.start, this.start + height).entries()) {
      if (row.kind === "group") {
        lines.push(frame(theme.fg("accent", theme.bold(row.text))));
        continue;
      }
      const chosen = this.start + offset === this.selected;
      const tag = row.tag ? theme.fg(row.tag === "confirm" ? "warning" : "muted", ` (${row.tag})`) : "";
      const label = chosen ? theme.fg("accent", `› ${row.text}`) : `  ${row.text}`;
      lines.push(frame(`${label}${tag}`));
    }
    const row = this.rows[this.selected];
    lines.push(frame(""));
    lines.push(frame(theme.fg("dim", row?.action ? `$ ${preview(row.action, row.answers)}` : "")));
    const position = `${this.rows.slice(0, this.selected + 1).filter((entry) => entry.kind === "action").length}/` +
      `${this.rows.filter((entry) => entry.kind === "action").length}`;
    lines.push(frame(theme.fg("dim", `↑↓ move · enter choose · esc close · ${position}`)));
    lines.push(theme.fg("border", `╰${"─".repeat(inner + 2)}╯`));
    this.cache = { width, lines };
    return lines;
  }

  invalidate(): void {
    this.cache = undefined;
  }
}

const FORM_STYLES: Record<FormLine["style"], (theme: Theme, text: string) => string> = {
  header: (theme, text) => theme.fg(text.startsWith("server: running") ? "success" : "muted", text),
  answer: (_theme, text) => text,
  warning: (theme, text) => theme.fg("warning", text),
  question: (theme, text) => theme.fg("accent", theme.bold(text)),
  option: (_theme, text) => text,
  selected: (theme, text) => theme.fg("accent", text),
  typed: (theme, text) => theme.fg("accent", `${text}▏`),
  error: (theme, text) => theme.fg("error", text),
  command: (theme, text) => theme.fg("dim", text),
  plain: (_theme, text) => text,
};

/**
 * The start / restart form: one overlay asking database, dev mode and port, then Run / Cancel,
 * with the filled command as its last lines (wrapped, never truncated), drawn again after every
 * answer. Up/down move, enter chooses or accepts the typed value, typing and backspace edit it,
 * escape cancels (nothing runs).
 */
export class RunFormPanel implements Component {
  private readonly form: RunForm;
  private readonly tui: TUI;
  private readonly theme: Theme;
  private readonly keybindings: KeybindingsManager;
  private readonly done: (answers: Answers | undefined) => void;
  private cache: { width: number; lines: string[] } | undefined;

  constructor(form: RunForm, tui: TUI, theme: Theme, keybindings: KeybindingsManager,
    done: (answers: Answers | undefined) => void) {
    this.form = form;
    this.tui = tui;
    this.theme = theme;
    this.keybindings = keybindings;
    this.done = done;
  }

  handleInput(data: string): void {
    const form = this.form;
    if (this.keybindings.matches(data, "tui.select.cancel")) {
      form.cancel();
    } else if (this.keybindings.matches(data, "tui.select.confirm")) {
      form.submit();
    } else if (form.typing && this.keybindings.matches(data, "tui.editor.deleteCharBackward")) {
      form.backspace();
    } else if (form.typing) {
      // Printable keys only: an escape sequence (arrows, function keys) is not text.
      const text = decodeKittyPrintable(data) ?? (data.includes("\x1b") ? undefined : data);
      if (text) form.type(text);
    } else if (this.keybindings.matches(data, "tui.select.up")) {
      form.move(-1);
    } else if (this.keybindings.matches(data, "tui.select.down")) {
      form.move(1);
    } else {
      return;
    }
    if (form.finished) {
      this.done(form.result);
      return;
    }
    this.invalidate();
    this.tui.requestRender();
  }

  render(width: number): string[] {
    if (this.cache?.width === width) return this.cache.lines;
    const theme = this.theme;
    const inner = Math.max(1, width - 4);
    const frame = (content: string) => {
      const fitted = truncateToWidth(content, inner);
      const pad = " ".repeat(Math.max(0, inner - visibleWidth(fitted)));
      return `${theme.fg("border", "│")} ${fitted}${pad} ${theme.fg("border", "│")}`;
    };
    const title = truncateToWidth(`─ oasis: ${this.form.spec.action.label} `, inner + 2);
    const lines = [theme.fg("border", `╭${title}${"─".repeat(Math.max(0, inner + 2 - visibleWidth(title)))}╮`)];
    const body = this.form.lines(inner);
    // Too tall for the terminal: the header and earlier answers go first, never the command.
    const room = Math.max(5, Math.floor(this.tui.terminal.rows * 0.9) - FORM_CHROME_ROWS);
    for (const line of body.slice(Math.max(0, body.length - room))) lines.push(frame(FORM_STYLES[line.style](theme, line.text)));
    const hint = this.form.typing ? "type · enter accept · esc cancel" : "↑↓ move · enter choose · esc cancel";
    lines.push(frame(theme.fg("dim", hint)));
    lines.push(theme.fg("border", `╰${"─".repeat(inner + 2)}╯`));
    this.cache = { width, lines };
    return lines;
  }

  invalidate(): void {
    this.cache = undefined;
  }
}

/**
 * The live server log view: the last lines of the log that fit, read again every LOG_REFRESH_MS while
 * it is open (the timer stops when Pi disposes it); escape or enter closes it.
 */
export class LogPanel implements Component {
  private readonly title: string;
  private readonly read: () => string;
  private readonly tui: TUI;
  private readonly theme: Theme;
  private readonly keybindings: KeybindingsManager;
  private readonly done: () => void;
  private readonly timer: ReturnType<typeof setInterval>;
  private text: string;
  private cache: { width: number; lines: string[] } | undefined;

  constructor(title: string, read: () => string, tui: TUI, theme: Theme, keybindings: KeybindingsManager,
    done: () => void) {
    this.title = title;
    this.read = read;
    this.tui = tui;
    this.theme = theme;
    this.keybindings = keybindings;
    this.done = done;
    this.text = read();
    this.timer = setInterval(() => this.refresh(), LOG_REFRESH_MS);
  }

  private refresh(): void {
    const text = this.read();
    if (text === this.text) return;
    this.text = text;
    this.invalidate();
    this.tui.requestRender();
  }

  private height(): number {
    return Math.max(5, Math.floor(this.tui.terminal.rows * 0.9) - LOG_CHROME_ROWS);
  }

  handleInput(data: string): void {
    if (this.keybindings.matches(data, "tui.select.cancel") || this.keybindings.matches(data, "tui.select.confirm")) {
      this.dispose();
      this.done();
    }
  }

  render(width: number): string[] {
    if (this.cache?.width === width) return this.cache.lines;
    const theme = this.theme;
    const inner = Math.max(1, width - 4);
    const frame = (content: string) => {
      const fitted = truncateToWidth(content, inner);
      const pad = " ".repeat(Math.max(0, inner - visibleWidth(fitted)));
      return `${theme.fg("border", "│")} ${fitted}${pad} ${theme.fg("border", "│")}`;
    };
    const height = this.height();
    const title = truncateToWidth(`─ oasis: ${this.title} (live) `, inner + 2);
    const lines = [theme.fg("border", `╭${title}${"─".repeat(Math.max(0, inner + 2 - visibleWidth(title)))}╮`)];
    for (const line of logView(lastLines(this.text, height), height)) lines.push(frame(line));
    lines.push(frame(""));
    lines.push(frame(theme.fg("dim", `esc close · refreshes every ${LOG_REFRESH_MS / 1000} s`)));
    lines.push(theme.fg("border", `╰${"─".repeat(inner + 2)}╯`));
    this.cache = { width, lines };
    return lines;
  }

  invalidate(): void {
    this.cache = undefined;
  }

  dispose(): void {
    clearInterval(this.timer);
  }
}

/** Result entries: title, command and output; the last lines until the user expands tool output. */
export const renderMenuEntry: EntryRenderer<MenuEntry> = (entry, options, theme) => {
  const data = entry.data;
  if (!data) return undefined;
  const lines = entryLines(data, options.expanded, PREVIEW_LINES);
  const failed = data.exit !== undefined && data.exit !== 0;
  const [title, command, ...output] = lines;
  // entryLines put the "… N earlier lines" marker first.
  const hidden = !options.expanded && data.output.split("\n").length > PREVIEW_LINES;
  if (hidden) output[0] = `${output[0]} (${options.keyHint("app.tools.expand", "to expand")})`;
  const box = new Box(1, 1, (text) => theme.bg("customMessageBg", text));
  box.addChild(new Text(theme.fg(failed ? "error" : "accent", theme.bold(title)), 0, 0));
  box.addChild(new Text(theme.fg("dim", command), 0, 0));
  if (output.length > 0) box.addChild(new Text(output.join("\n"), 0, 0));
  return box;
};
