import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { CoreResult } from "../lib/tools.ts";
import type { MenuEntry } from "../lib/menu.ts";
import { actionPanel, type ExecPurpose, type PanelContext, type PanelEffects } from "../lib/panel.ts";

// The panel's decisions with every Pi effect faked: what it runs, asks, notifies and records.
const CATALOG = readFileSync(new URL("./fixtures/catalog.json", import.meta.url), "utf8");
const ROOT = "/work/a project";
const ENTRY = "/opt/oasis/oasis --project '/work/a project'";
const CATALOG_ARGV = ["python3", "-B", "/opt/oasis/oasis", "--project", ROOT, "menu", "--catalog"];
const NOT_PROJECT = "no .odoo19-agent.toml or oasis-workspace.toml at or above /elsewhere";
const NON_TUI = "warning: oasis menu: the action panel needs the interactive terminal UI; run `oasis menu` in a terminal.";

type Exec = (argv: string[], purpose: ExecPurpose) => Promise<CoreResult>;

/** Lets pending promises settle until `ready` holds (bounded, so a wrong flow fails instead of hanging). */
async function until(ready: () => boolean): Promise<void> {
  for (let turn = 0; turn < 100 && !ready(); turn += 1) await new Promise((resolve) => setImmediate(resolve));
  assert.ok(ready(), "the flow never reached the awaited step");
}

interface Setup {
  pick?: string | undefined;
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
    readLog: () => "",
    appendEntry: (entry) => entries.push(entry),
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
        return catalog.actions.find((action) => action.id === options.pick);
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
  return { open: actionPanel(effects), context, events, entries, headers, serverRoots, left: () => answers.length };
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
  const { open, context, events, entries } = harness({
    pick: "server.status",
    exec: async () => ({ code: 0, stdout: "server: stopped\n", stderr: "" }),
  });
  await open(context());
  assert.deepEqual(events.slice(1), [
    "pick",
    `info: oasis menu: running ${ENTRY} status`,
    "status oasis: Show the server and database service status",
    `exec run in ${ROOT}: /opt/oasis/oasis --project ${ROOT} status`,
    "status -",
  ]);
  assert.deepEqual(entries, [{
    label: "Show the server and database service status", command: `${ENTRY} status`, exit: 0, output: "server: stopped",
  }]);
});

test("a command that cannot be started leaves an entry with the attempted command and the error", async () => {
  const { open, context, events, entries } = harness({
    pick: "server.status",
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
    pick: "server.status",
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

test("the picker header shows the server state of the checkout from runtime_state", async () => {
  for (const [server, header] of [
    [{ server: { pid: 4242, port: 8070 } }, "server: running on port 8070 (pid 4242)"],
    [{ server: null }, "server: stopped"],
    [{ serverError: "ERROR: Runtime state directory is a symlink: /run/x" },
      "server: unknown (Runtime state directory is a symlink: /run/x)"],
    [new Error("spawn python3 ENOENT"), "server: unknown (spawn python3 ENOENT)"],
  ] as const) {
    const { open, context, events, headers, serverRoots, entries } = harness({ pick: undefined, server });
    await open(context());
    assert.deepEqual(headers, [header]);
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
    pick: "server.restart", answers: ["(skip: to keep the database of the running server)"],
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
