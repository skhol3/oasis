// The action panel's TUI pieces, on the public Pi extension API only: the group and action picker
// shown with ctx.ui.custom as an overlay, and the renderer of the result entries. The logic they
// show (rows, selection, scrolling, entry lines) is in lib/menu.ts, tested without Pi.
import type { EntryRenderer, KeybindingsManager, Theme } from "@earendil-works/pi-coding-agent";
import { Box, type Component, type Keybinding, Text, truncateToWidth, type TUI, visibleWidth } from "@earendil-works/pi-tui";
import {
  type Catalog, type CatalogAction, entryLines, type MenuEntry, moveSelection, type PickerRow, pickerRows,
  shellJoin, terminalCommand, visibleStart,
} from "../lib/menu.ts";

export const MENU_ENTRY = "oasis-menu-result";
const PREVIEW_LINES = 20;
// Border, title, blank line, command preview, hint and border around the list.
const CHROME_ROWS = 7;

/** What the highlighted action would run, as the panel shows it under the list. */
function preview(action: CatalogAction): string {
  if (action.kind === "log") return shellJoin(action.argv.filter((token): token is string => typeof token === "string"));
  return terminalCommand(action);
}

/** The group and action picker: up/down/page keys move, enter chooses, escape closes. */
export class MenuPanel implements Component {
  private readonly catalog: Catalog;
  private readonly tui: TUI;
  private readonly theme: Theme;
  private readonly keybindings: KeybindingsManager;
  private readonly done: (action: CatalogAction | undefined) => void;
  private readonly rows: PickerRow[];
  private selected: number;
  private start = 0;
  private cache: { width: number; lines: string[] } | undefined;

  constructor(
    catalog: Catalog, tui: TUI, theme: Theme, keybindings: KeybindingsManager,
    done: (action: CatalogAction | undefined) => void,
  ) {
    this.catalog = catalog;
    this.tui = tui;
    this.theme = theme;
    this.keybindings = keybindings;
    this.done = done;
    this.rows = pickerRows(catalog);
    this.selected = moveSelection(this.rows, 0, 0);
  }

  private listHeight(): number {
    return Math.max(5, Math.floor(this.tui.terminal.rows * 0.9) - CHROME_ROWS);
  }

  handleInput(data: string): void {
    const page = this.listHeight();
    const moves: [Keybinding, number][] = [
      ["tui.select.up", -1], ["tui.select.down", 1], ["tui.select.pageUp", -page], ["tui.select.pageDown", page],
    ];
    if (this.keybindings.matches(data, "tui.select.confirm")) {
      this.done(this.rows[this.selected]?.action);
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
    const action = this.rows[this.selected]?.action;
    lines.push(frame(""));
    lines.push(frame(theme.fg("dim", action ? `$ ${preview(action)}` : "")));
    const position = `${this.rows.slice(0, this.selected + 1).filter((row) => row.kind === "action").length}/` +
      `${this.catalog.actions.length}`;
    lines.push(frame(theme.fg("dim", `↑↓ move · enter choose · esc close · ${position}`)));
    lines.push(theme.fg("border", `╰${"─".repeat(inner + 2)}╯`));
    this.cache = { width, lines };
    return lines;
  }

  invalidate(): void {
    this.cache = undefined;
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
