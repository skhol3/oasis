import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { CoreResult } from "../lib/tools.ts";
import type { Answers, MenuEntry } from "../lib/menu.ts";
import type { FormSpec } from "../lib/menu.ts";
import { actionPanel, type ExecPurpose, type PanelContext, type PanelEffects } from "../lib/panel.ts";

// The panel's decisions with every Pi effect faked: what it runs, asks, notifies and records.
const CATALOG = readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8");
const ROOT = "/work/a project";
const ENTRY = "/opt/oasis/oasis --project '/work/a project'";
const CATALOG_ARGV = ["python3", "-B", "/opt/oasis/oasis", "--project", ROOT, "menu", "--catalog"];
const NOT_PROJECT = "no oasis-workspace.toml at or above /elsewhere";
const NATIVE = "/home/dev/env/bin/python /home/dev/odoo/odoo-bin -c '/work/a project/odoo.conf' -d cc_dev_coffee";
const NON_TUI = "warning: oasis menu: the action panel needs the interactive terminal UI; run `oasis menu` in a terminal.";

type Exec = (argv: string[], purpose: ExecPurpose) => Promise<CoreResult>;

/** Lets pending promises settle until `ready` holds (bounded, so a wrong flow fails instead of hanging). */
async function until(ready: () => boolean): Promise<void> {
  for (let turn = 0; turn < 100 && !ready(); turn += 1) await new Promise((resolve) => setImmediate(resolve));
  assert.ok(ready(), "the flow never reached the awaited step");
}

interface Setup {
  pick?: string | undefined;
  /** The picker's Repeat row: the picked action comes with these answers. */
  repeat?: Answers;
  /** What the start / restart form returns (default: cancelled). */
  form?: Answers;
  /** remember rejects with this error. */
  rememberError?: Error;
  answers?: (string | boolean | undefined)[];
  /** The catalog command (default: prints the fixture catalog). */
  catalog?: Exec;
  /** list-databases and the action's command (default: prints "done"). */
  exec?: Exec;
  exists?: boolean;
  root?: string | null;
  /** What runtime_state reads for the header (default: stopped), or the error the read throws. */
  server?: Awaited<ReturnType<PanelEffects["serverState"]>> | Error;
}

function harness(options: Setup = {}) {
  const events: string[] = [];
  const entries: MenuEntry[] = [];
  const headers: string[] = [];
  const serverRoots: string[] = [];
  const forms: FormSpec[] = [];
  const remembered: string[] = [];
  const answers = [...(options.answers ?? [])];
  const catalog: Exec = options.catalog ?? (async () => ({ code: 0, stdout: CATALOG, stderr: "" }));
  const exec: Exec = options.exec ?? (async () => ({ code: 0, stdout: "done\n", stderr: "" }));
  const effects: PanelEffects = {
    projectRoot: async () => (options.root === undefined ? ROOT : options.root),
    notProject: () => NOT_PROJECT,
    catalogArgv: (root) => ["python3", "-B", "/opt/oasis/oasis", "--project", root, "menu", "--catalog"],
    exec: async (argv, cwd, purpose) => {
      events.push(`exec ${purpose} in ${cwd}: ${argv.join(" ")}`);
      return (purpose === "catalog" ? catalog : exec)(argv, purpose);
    },
    exists: () => options.exists ?? true,
    home: "/home/dev",
    readLog: () => "",
    appendEntry: (entry) => entries.push(entry),
    remember: async (root, id, answers) => {
      remembered.push(`${root}: ${id} ${JSON.stringify(answers)}`);
      if (options.rememberError) throw options.rememberError;
    },
    serverState: async (root) => {
      serverRoots.push(root);
      const server = options.server ?? { server: null };
      if (server instanceof Error) throw server;
      return server;
    },
  };
  const next = () => {
    assert.ok(answers.length > 0, `unexpected prompt after ${events.join(" | ")}`);
    return answers.shift();
  };
  const context = (mode = "tui"): PanelContext => ({
    mode,
    cwd: "/work/a project/addons",
    ui: {
      pick: async (catalog, header) => {
        events.push("pick");
        headers.push(header);
        const action = catalog.actions.find((item) => item.id === options.pick);
        return action && { action, ...(options.repeat ? { answers: options.repeat } : {}) };
      },
      form: async (spec) => {
        events.push(`form ${spec.action.id}`);
        forms.push(spec);
        return options.form;
      },
      follow: async (path, title) => {
        events.push(`follow ${path} (${title})`);
      },
      select: async (title) => {
        events.push(`select ${title}`);
        return next() as string | undefined;
      },
      input: async (title) => {
        events.push(`input ${title.split("\n")[0]}`);
        return next() as string | undefined;
      },
      confirm: async (title) => {
        events.push(`confirm ${title}`);
        return next() as boolean;
      },
      notify: (message, level) => events.push(`${level}: ${message}`),
      setStatus: (text) => events.push(`status ${text ?? "-"}`),
    },
  });
  return {
    open: actionPanel(effects), context, events, entries, headers, serverRoots, forms, remembered,
    left: () => answers.length,
  };
}

test("outside the interactive TUI the panel refuses and runs nothing", async () => {
  const { open, context, events, entries } = harness({ pick: "server.status" });
  await open(context("rpc"));
  assert.deepEqual(events, [NON_TUI]);
  assert.deepEqual(entries, []);
});

test("outside an Odoo project the panel says so and reads no catalog", async () => {
  const { open, context, events, entries } = harness({ root: null });
  await open(context());
  assert.deepEqual(events, [`warning: Not an Odoo project: ${NOT_PROJECT}`, "status -"]);
  assert.deepEqual(entries, []);
});

test("a failing catalog command is reported and nothing is picked or run", async () => {
  const { open, context, events, entries } = harness({
    catalog: async () => ({ code: 2, stdout: "", stderr: "ERROR: unreadable profile\n" }),
  });
  await open(context());
  assert.deepEqual(events, [
    `exec catalog in ${ROOT}: ${CATALOG_ARGV.join(" ")}`,
    "error: oasis menu: ERROR: unreadable profile",
    "status -",
  ]);
  assert.deepEqual(entries, []);
  const silent = harness({ catalog: async () => ({ code: 3, stdout: "", stderr: "" }) });
  await silent.open(silent.context());
  assert.equal(silent.events[1], "error: oasis menu: exit 3");
  const malformed = harness({ catalog: async () => ({ code: 0, stdout: "{", stderr: "" }) });
  await malformed.open(malformed.context());
  assert.match(malformed.events[1], /^error: oasis menu failed: the catalog is not JSON: /);
  assert.equal(malformed.events.length, 3);
});

test("closing the picker runs nothing", async () => {
  const { open, context, events, entries } = harness({ pick: undefined });
  await open(context());
  assert.deepEqual(events.slice(1), ["pick", "status -"]);
  assert.deepEqual(entries, []);
});

test("a terminal-only action is shown as an entry with its command and never run", async () => {
  const { open, context, events, entries } = harness({ pick: "modules.init_dev" });
  await open(context());
  assert.deepEqual(events.slice(1), ["pick", "status -"]);
  assert.deepEqual(entries, [{
    label: "Create a development database with role accounts",
    command: `${ENTRY} init-dev-database [--with-demo] <module> <database>`,
    note: "terminal only: run it in a terminal, or use oasis menu there",
    output: "",
  }]);
});

test("the server log action says when there is no log yet", async () => {
  const { open, context, events, entries } = harness({ pick: "server.logs", exists: false });
  await open(context());
  assert.deepEqual(events.slice(1), [
    "pick", "warning: oasis menu: no server log yet: /work/a project/dev/logs/odoo19/server.log", "status -",
  ]);
  assert.deepEqual(entries, []);
});

test("cancelling an input runs nothing", async () => {
  const { open, context, events, entries, left } = harness({ pick: "modules.status", answers: [undefined] });
  await open(context());
  assert.deepEqual(events.slice(1), ["pick", "select Module", "info: oasis menu: nothing ran.", "status -"]);
  assert.deepEqual(entries, []);
  assert.equal(left(), 0);
});

test("a destructive action that is not confirmed runs nothing", async () => {
  const { open, context, events, entries } = harness({
    pick: "maintenance.drop_database", answers: ["(type a name)", "cc_dev_x", "No", "cc_dev_y"],
    exec: async () => ({ code: 0, stdout: "", stderr: "" }),
  });
  await open(context());
  assert.deepEqual(events.filter((event) => event.startsWith("exec run")), []);
  assert.deepEqual(events.slice(-2), ["info: oasis menu: not confirmed, nothing ran.", "status -"]);
  assert.deepEqual(entries, []);
});

test("a confirmed action runs its filled command in the project root and records command and output", async () => {
  const { open, context, events, entries, remembered } = harness({
    pick: "server.status", answers: [true],
    exec: async () => ({ code: 0, stdout: "server: stopped\n", stderr: "" }),
  });
  await open(context());
  assert.deepEqual(events.slice(1), [
    "pick",
    "confirm Show the server and database service status",
    `info: oasis menu: running ${ENTRY} status`,
    "status oasis: Show the server and database service status",
    `exec run in ${ROOT}: /opt/oasis/oasis --project ${ROOT} status`,
    "status -",
  ]);
  assert.deepEqual(entries, [{
    label: "Show the server and database service status", command: `${ENTRY} status`, exit: 0, output: "server: stopped",
  }]);
  // v0.12.0 (S6): the action and its answers are remembered for Repeat.
  assert.deepEqual(remembered, [`${ROOT}: server.status {}`]);
});

test("a command that cannot be started leaves an entry with the attempted command and the error", async () => {
  const { open, context, events, entries } = harness({
    pick: "server.status", answers: [true],
    exec: async () => {
      throw new Error("spawn /opt/oasis/oasis ENOENT");
    },
  });
  await open(context());
  assert.deepEqual(entries, [{
    label: "Show the server and database service status", command: `${ENTRY} status`,
    note: "could not run", output: "spawn /opt/oasis/oasis ENOENT",
  }]);
  assert.deepEqual(events.slice(-2), [
    `error: oasis menu: could not run ${ENTRY} status: spawn /opt/oasis/oasis ENOENT`, "status -",
  ]);
});

test("a catalog or database listing that cannot be started is recorded the same way", async () => {
  const catalog = harness({ catalog: async () => { throw new Error("spawn python3 ENOENT"); } });
  await catalog.open(catalog.context());
  assert.deepEqual(catalog.entries, [{
    label: "Read the action catalog", command: CATALOG_ARGV.map((word) => word.includes(" ") ? `'${word}'` : word).join(" "),
    note: "could not run", output: "spawn python3 ENOENT",
  }]);
  assert.deepEqual(catalog.events.slice(1, -1), [
    `error: oasis menu: could not run ${catalog.entries[0].command}: spawn python3 ENOENT`,
  ]);
  const listing = harness({
    pick: "modules.status", answers: ["coffee"],
    exec: async () => {
      throw new Error("spawn /opt/oasis/oasis EACCES");
    },
  });
  await listing.open(listing.context());
  assert.deepEqual(listing.entries, [{
    label: "List the databases", command: `${ENTRY} list-databases`, note: "could not run",
    output: "spawn /opt/oasis/oasis EACCES",
  }]);
  assert.deepEqual(listing.events.filter((event) => event.startsWith("error:")), [
    `error: oasis menu: could not run ${ENTRY} list-databases: spawn /opt/oasis/oasis EACCES`,
  ]);
  assert.equal(listing.events.at(-1), "status -");
});

test("one panel action at a time: a second open while one runs says what is in progress", async () => {
  let finish: (result: CoreResult) => void = () => {};
  let runs = 0;
  const { open, context, events, entries } = harness({
    pick: "server.status", answers: [true, true],
    // The first run waits until the test finishes it; later runs end at once.
    exec: () => runs++ === 0
      ? new Promise((resolve) => { finish = resolve; })
      : Promise.resolve({ code: 0, stdout: "", stderr: "" }),
  });
  const first = open(context());
  await until(() => events.some((event) => event.startsWith("exec run")));
  await open(context());
  assert.ok(events.includes(`info: oasis menu: ${ENTRY} status is still in progress.`), events.join("\n"));
  finish({ code: 0, stdout: "", stderr: "" });
  await first;
  assert.equal(entries.length, 1);
  events.length = 0;
  await open(context());
  assert.ok(events.includes("pick"), "the lock is released after the run");
  assert.equal(entries.length, 2);
});

test("while the picker or a question is open, a second open says the panel is in progress", async () => {
  let release: (value: string | undefined) => void = () => {};
  const { open, context, events } = harness({ pick: "modules.status" });
  const ctx = context();
  ctx.ui.select = () => new Promise((resolve) => { release = resolve; });
  const first = open(ctx);
  await until(() => events.includes("pick"));
  await open(context());
  assert.ok(events.includes("info: oasis menu: the panel is still in progress."), events.join("\n"));
  release(undefined);
  await first;
});

test("an unexpected error is reported and releases the lock", async () => {
  const { open, context, events } = harness({ pick: "server.status" });
  const ctx = context();
  ctx.ui.pick = async () => { throw new Error("overlay failed"); };
  await open(ctx);
  assert.deepEqual(events.slice(1), ["error: oasis menu failed: overlay failed", "status -"]);
  events.length = 0;
  await open(context());
  assert.ok(events.includes("pick"));
});

test("the picker header shows the checkout, its server state from runtime_state and the default database", async () => {
  for (const [server, header] of [
    [{ server: { pid: 4242, port: 8070 } }, "server: running on port 8070 (pid 4242)"],
    [{ server: null }, "server: stopped"],
    [{ serverError: "ERROR: Runtime state directory is a symlink: /run/x" },
      "server: unknown (Runtime state directory is a symlink: /run/x)"],
    [new Error("spawn python3 ENOENT"), "server: unknown (spawn python3 ENOENT)"],
  ] as const) {
    const { open, context, events, headers, serverRoots, entries } = harness({ pick: undefined, server });
    await open(context());
    assert.deepEqual(headers, [`checkout: main\n${header}\ndefault database: cc_dev_coffee`]);
    assert.deepEqual(serverRoots, [ROOT]);
    assert.deepEqual(events.slice(1), ["pick", "status -"]);
    assert.deepEqual(entries, []);
  }
});

test("following the server log opens the live view of server.log and runs nothing", async () => {
  const { open, context, events, entries } = harness({ pick: "server.follow" });
  await open(context());
  assert.deepEqual(events.slice(1), [
    "pick", "follow /work/a project/dev/logs/odoo19/server.log (Follow the server log)", "status -",
  ]);
  assert.deepEqual(entries, []);
  const missing = harness({ pick: "server.follow", exists: false });
  await missing.open(missing.context());
  assert.deepEqual(missing.events.slice(1), [
    "pick", "warning: oasis menu: no server log yet: /work/a project/dev/logs/odoo19/server.log", "status -",
  ]);
});

test("restart runs with the optional database and records its output", async () => {
  const { open, context, events, entries, left } = harness({
    pick: "server.restart", answers: ["(skip: to keep the database of the running server)", true],
    exec: async () => ({ code: 0, stdout: "Stopped Odoo for this checkout: pid 1, port 8069.\npid=2 port=8069 log=/l\n",
      stderr: "" }),
  });
  await open(context());
  assert.equal(left(), 0);
  assert.ok(events.includes(`exec run in ${ROOT}: /opt/oasis/oasis --project ${ROOT} restart`), events.join("\n"));
  assert.deepEqual(entries, [{
    label: "Restart the server", command: `${ENTRY} restart`, exit: 0,
    output: "Stopped Odoo for this checkout: pid 1, port 8069.\npid=2 port=8069 log=/l",
  }]);
});

test("a non-destructive action that is not confirmed runs nothing and is not remembered", async () => {
  const { open, context, events, entries, remembered } = harness({ pick: "server.status", answers: [false] });
  await open(context());
  assert.deepEqual(events.slice(1), [
    "pick", "confirm Show the server and database service status", "info: oasis menu: not confirmed, nothing ran.",
    "status -",
  ]);
  assert.deepEqual([entries, remembered], [[], []]);
});

test("user-run actions are not remembered; a memory that cannot be written is only a notice", async () => {
  const worktree = harness({ pick: "maintenance.worktree", answers: ["shop", "shop", true] });
  await worktree.open(worktree.context());
  assert.equal(worktree.entries.length, 1);
  assert.deepEqual(worktree.remembered, []);
  const failing = harness({ pick: "server.status", answers: [true], rememberError: new Error("ERROR: no state") });
  await failing.open(failing.context());
  assert.equal(failing.entries.length, 1);
  assert.deepEqual(failing.events.slice(-2), [
    "warning: oasis menu: could not remember this action: ERROR: no state", "status -",
  ]);
});

test("start / restart lists the databases, then asks everything in one form that also confirms", async () => {
  const answers = { database: "cc_dev_coffee", dev: "all", port: "" };
  const { open, context, events, entries, forms, remembered } = harness({
    pick: "server.run", form: answers,
    exec: async (argv) => ({
      code: 0, stderr: "",
      stdout: argv.includes("list-databases") ? "cc_dev_coffee\n"
        : argv.includes("--print-command") ? `${NATIVE}\n` : "pid=1\n",
    }),
  });
  await open(context());
  assert.deepEqual(events.slice(1), [
    "pick",
    "status Listing databases (this may start the database service)...",
    "info: Listing databases (this may start the database service)...",
    `exec list in ${ROOT}: /opt/oasis/oasis --project ${ROOT} list-databases`,
    "status -",
    "form server.run",
    // S4: the native line of the chosen answers, asked before the run (the form asks it while open).
    `exec print in ${ROOT}: /opt/oasis/oasis --project ${ROOT} start --print-command -d cc_dev_coffee --dev all`,
    `info: oasis menu: running ${ENTRY} start --detach -d cc_dev_coffee --dev all`,
    "status oasis: Start / restart the server",
    `exec run in ${ROOT}: /opt/oasis/oasis --project ${ROOT} start --detach -d cc_dev_coffee --dev all`,
    "status -",
  ]);
  assert.deepEqual([forms[0].databases, forms[0].answers, forms[0].header],
    [["cc_dev_coffee"], undefined, "checkout: main\nserver: stopped\ndefault database: cc_dev_coffee"]);
  assert.deepEqual(entries.map((entry) => [entry.command, entry.native]),
    [[`${ENTRY} start --detach -d cc_dev_coffee --dev all`, NATIVE]]);
  assert.equal(forms[0].home, "/home/dev");
  assert.ok(forms[0].native);
  assert.deepEqual(remembered, [`${ROOT}: server.run ${JSON.stringify(answers)}`]);
  const cancelled = harness({ pick: "server.run" });
  await cancelled.open(cancelled.context());
  assert.deepEqual(cancelled.events.slice(-3), ["form server.run", "info: oasis menu: nothing ran.", "status -"]);
  assert.deepEqual([cancelled.entries, cancelled.remembered], [[], []]);
});

test("Repeat runs the remembered answers after the same preview and confirmation", async () => {
  const update = harness({ pick: "modules.update", repeat: { module: "coffee", database: "cc_dev_x" }, answers: [true] });
  await update.open(update.context());
  assert.deepEqual(update.events.slice(1, 3), ["pick", "confirm Update a module"]);
  assert.deepEqual(update.entries.map((entry) => entry.command), [`${ENTRY} update-module --compact coffee cc_dev_x`]);
  const declined = harness({ pick: "maintenance.drop_database", repeat: { database: "cc_dev_x", terminate: false },
    answers: ["cc_dev_y"] });
  await declined.open(declined.context());
  assert.deepEqual(declined.events.slice(1), ["pick", "input Move a database to the trash",
    "info: oasis menu: not confirmed, nothing ran.", "status -"]);
  // The start / restart form opens at its confirmation: no database listing.
  const run = { database: "", dev: "", port: "8070" };
  const restart = harness({ pick: "server.run", repeat: run, form: run });
  await restart.open(restart.context());
  assert.deepEqual(restart.events.slice(1, 3), ["pick", "form server.run"]);
  assert.deepEqual(restart.forms[0].answers, run);
  assert.deepEqual(restart.entries.map((entry) => entry.command), [`${ENTRY} start --detach --http-port 8070`]);
});

test("a native line lookup that rejects keeps the run's entry and the Repeat memory (S4)", async () => {
  const answers = { database: "", dev: "", port: "8070" };
  const { open, context, events, entries, remembered } = harness({
    pick: "server.run", repeat: answers, form: answers,
    // A print result without stdout makes the lookup itself reject (parseNativeLine throws).
    exec: async (argv) => (argv.includes("--print-command") ? { code: 0 } as CoreResult
      : { code: 0, stdout: "pid=1\n", stderr: "" }),
  });
  await open(context());
  assert.deepEqual(entries, [{
    label: "Start / restart the server", command: `${ENTRY} start --detach --http-port 8070`, exit: 0, output: "pid=1",
  }]);
  assert.deepEqual(remembered, [`${ROOT}: server.run ${JSON.stringify(answers)}`]);
  assert.deepEqual(events.filter((event) => event.startsWith("error:") || event.startsWith("warning:")), []);
  assert.equal(events.at(-1), "status -");
});

test("start / restart still runs when its native line cannot be read; the entry then has none (S4)", async () => {
  for (const print of [
    async () => ({ code: 2, stdout: "", stderr: "start: unknown option --print-command\n" }),
    async () => {
      throw new Error("spawn python3 ENOENT");
    },
  ]) {
    const answers = { database: "", dev: "", port: "8070" };
    const { open, context, events, entries } = harness({
      pick: "server.run", repeat: answers, form: answers,
      exec: async (argv) => (argv.includes("--print-command") ? print() : { code: 0, stdout: "pid=1\n", stderr: "" }),
    });
    await open(context());
    assert.deepEqual(events.slice(1), [
      "pick", "form server.run",
      `exec print in ${ROOT}: /opt/oasis/oasis --project ${ROOT} start --print-command --http-port 8070`,
      `info: oasis menu: running ${ENTRY} start --detach --http-port 8070`,
      "status oasis: Start / restart the server",
      `exec run in ${ROOT}: /opt/oasis/oasis --project ${ROOT} start --detach --http-port 8070`,
      "status -",
    ]);
    assert.deepEqual(entries, [{
      label: "Start / restart the server", command: `${ENTRY} start --detach --http-port 8070`, exit: 0, output: "pid=1",
    }]);
  }
});
