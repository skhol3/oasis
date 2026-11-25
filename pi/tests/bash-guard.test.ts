import { test } from "node:test";
import assert from "node:assert/strict";
import { blockedEverywhere, blockedProgram, blockReason, classifyBash } from "../lib/bash-guard.ts";
import { readFileSync } from "node:fs";

test("blocks odoo-bin, dropdb and psql in command position", () => {
  const blocked: [string, string][] = [
    ["odoo-bin -c dev/odoo.conf -d cc_dev_x -u coffee", "odoo-bin"],
    ["/opt/odoo/community/odoo-bin shell -d cc_dev_x", "odoo-bin"],
    ["python3 community/odoo-bin -d x --test-tags /coffee", "odoo-bin"],
    [".venv/bin/python -B ../odoo/odoo-bin -i coffee", "odoo-bin"],
    ["dropdb cc_test_coffee", "dropdb"],
    ["psql -U odoo -c 'DROP DATABASE x'", "psql"],
    ["cd dev && PGPASSWORD=x psql -h localhost", "psql"],
    ["ls; sudo -u postgres dropdb x", "dropdb"],
    ["echo ok || /usr/bin/psql x", "psql"],
    ["cat dump.sql | psql cc_dev_x", "psql"],
    ["env FOO=1 time nohup odoo-bin -d x", "odoo-bin"],
    ["docker compose -f dev/compose.yaml exec -T db psql -U odoo", "psql"],
    ["docker exec -it corpus-db dropdb -U odoo x", "dropdb"],
    ["bash -c 'psql -l'", "psql"],
    ["echo $(psql -Atc 'select 1')", "psql"],
  ];
  for (const [command, program] of blocked) {
    assert.equal(blockedProgram(command), program, command);
  }
});

test("allows guarded tools, reading and searching that only mention the names", () => {
  const allowed = [
    "~/.agents/skills/odoo19/odoo19 --project /p test-module coffee",
    "~/.agents/skills/odoo19/oasis --project /p test-module coffee",
    "dev/scripts/test-module coffee",
    "grep -rn psql tools/",
    "rg odoo-bin README.md",
    "cat docs/dropdb-notes.md",
    "echo 'run psql later'",
    "git log --grep=dropdb",
    "python3 -m unittest tests.test_lifecycle",
    "ls community/odoo-bin",
    "pg_dump --help",
  ];
  for (const command of allowed) {
    assert.equal(blockedProgram(command), null, command);
  }
});

test("blockReason names the program and redirects to the guarded commands", () => {
  const reason = blockReason("psql", "/work/coffee");
  assert.match(reason, /psql/);
  assert.match(reason, /`oasis --project \/work\/coffee <command>`/);
  assert.match(reason, /oasis_test_module/);
  assert.ok(!reason.includes("odoo19"), reason);
});

test("blocks combined shell flags, control keywords, eval and launchers", () => {
  const blocked: [string, string][] = [
    ["bash -lc 'psql -l'", "psql"],
    ["sh -ec 'dropdb x'", "dropdb"],
    ["if true; then psql; fi", "psql"],
    ["for d in a; do dropdb $d; done", "dropdb"],
    ["while true; do odoo-bin -d x; done", "odoo-bin"],
    ["! psql", "psql"],
    ["eval psql", "psql"],
    ["eval 'dropdb x'", "dropdb"],
    ["watch -n 5 psql -c 'select 1'", "psql"],
    ["find . -name '*.sql' -exec psql -f {} \\;", "psql"],
  ];
  for (const [command, program] of blocked) {
    assert.equal(blockedProgram(command), program, command);
  }
});

test("blocks agents from running worktree-init through any launcher, dry run included", () => {
  const blocked = [
    "~/.agents/skills/odoo19/odoo19 --project /p worktree-init feat feature/x",
    "python3 -B /opt/oasis/odoo19 --project /p worktree-init feat feature/x --dry-run",
    "cd /p && odoo19 --project /p worktree-init feat x",
    "env A=1 python3 odoo19 --project /p worktree-init feat x",
    "tools/worktree-init feat x",
    "bash ~/.agents/skills/odoo19/tools/worktree-init feat x",
    "python3 -I -B tools/worktree_init.py feat x",
    "bash -c 'odoo19 --project /p worktree-init feat x'",
    "echo $(odoo19 --project /p worktree-init feat x --dry-run)",
    "~/.agents/skills/odoo19/oasis --project /p worktree-init feat feature/x",
    "python3 -B /opt/oasis/oasis --project /p worktree-init feat feature/x --dry-run",
    "cd /p && oasis --project /p worktree-init feat x",
    "env A=1 python3 oasis --project /p worktree-init feat x",
    "bash -c 'oasis --project /p worktree-init feat x'",
    "echo $(oasis --project /p worktree-init feat x --dry-run)",
    "timeout 60 oasis --project /p worktree-init feat x",
  ];
  for (const command of blocked) {
    assert.equal(blockedProgram(command), "worktree-init", command);
  }
});

test("allows other oasis and odoo19 commands and reading or testing worktree-init", () => {
  const allowed = [
    "odoo19 --project /p status",
    "python3 -B odoo19 --project /p test-module coffee",
    "oasis --project /p status",
    "python3 -B oasis --project /p test-module coffee",
    "grep -n worktree-init oasis",
    "grep -n worktree-init README.md",
    "cat tools/worktree_init.py",
    "python3 -B -m unittest tests.test_worktree_init",
    "bash tools/test-module coffee",
    "git log --grep=worktree-init",
  ];
  for (const command of allowed) {
    assert.equal(blockedProgram(command), null, command);
  }
});

test("blockReason for worktree-init sends the user to /oasis worktree", () => {
  assert.equal(
    blockReason("worktree-init", "/work/coffee"),
    "worktree-init adds a git worktree and branch for the user; ask the user to run /oasis worktree " +
      "<feature> <branch> in Gentle Shell or the command in a terminal.",
  );
});

test("blocks agents from running migrate through the entry points or its tool, dry run included", () => {
  const blocked = [
    "oasis --project /p migrate",
    "oasis --project /p migrate --apply",
    "oasis --project=/p migrate --workspace /w",
    "~/.agents/skills/odoo19/oasis --project /p migrate --apply",
    "~/.agents/skills/odoo19/odoo19 --project /p migrate",
    "python3 -B /opt/oasis/oasis --project /p migrate --apply",
    "python3 -B /opt/oasis/odoo19 --project /p migrate",
    "cd /p && odoo19 --project /p migrate --apply",
    "env A=1 python3 oasis --project /p migrate",
    "bash -c 'oasis --project /p migrate --apply'",
    "echo $(odoo19 --project /p migrate)",
    "timeout 60 oasis --project /p migrate --apply",
    "tools/migrate --apply",
    "bash ~/.agents/skills/odoo19/tools/migrate --apply",
    "python3 -I -B ~/.agents/skills/odoo19/tools/migrate.py --apply",
  ];
  for (const command of blocked) {
    assert.equal(blockedProgram(command), "migrate", command);
  }
});

test("allows other commands that only mention migrate", () => {
  const allowed = [
    "oasis --project /p test-module migrate_tools",
    "oasis --project /p model-info x.y --field migrate",
    "odoo19 --project /p status",
    "python3 manage.py migrate",
    "npx prisma migrate dev",
    "./migrate.sh",
    "grep -n migrate tools/migrate.py",
    "cat tools/migrate.py",
    "python3 -B -m unittest tests.test_migrate",
    "git log --grep=migrate",
  ];
  for (const command of allowed) {
    assert.equal(blockedProgram(command), null, command);
  }
});

test("blockReason for migrate sends the user to /oasis migrate", () => {
  assert.equal(
    blockReason("migrate", "/work/coffee"),
    "migrate rewrites the project's configuration files; ask the user to run /oasis migrate in Gentle Shell " +
      "or the command in a terminal. To read the plan without changing anything, run it with only --plan.",
  );
});

test("text that bash would not run is not a command", () => {
  const allowed = [
    "git commit -m 'docs: explain `psql` usage'",
    "gh pr create --body 'run $(dropdb x) never'",
    "git commit -m 'docs: mention `oasis --project /p migrate`'",
    "cat > scripts/backup.sh <<'EOF'\npsql -l\nEOF",
    "cat >> README.md <<EOF\nodoo-bin shell -d x\nEOF",
    "cat <<-'END' > notes.md\n\tdropdb x\n\tEND\necho done",
    "echo \"it's fine\" && echo 'ok'",
    "git commit -m 'fix #12: explain `psql`'",
    "cat > notes.md <<'EOF'\n# psql notes\ndropdb is dangerous\nEOF",
    "sudo tee /etc/motd <<'EOF'\npsql -l\nEOF",
    "git add . && git commit -F - <<'EOF'\npsql is now guarded\nEOF",
    "git commit -m 'fix sh' -F - <<'EOF'\npsql -l\nEOF",
    "cat > notes.md <<'EOF' \\\n  2>/dev/null\npsql -l\nEOF",
    "git commit -m \"fix ssh\" -F - <<'EOF'\ndropdb x\nEOF",
    "gh pr create --title su --body-file - <<'EOF'\npsql -l\nEOF",
    "oasis --project /p migrate --help",
    "oasis --project /p migrate --plan",
    "odoo19 --project /p migrate --plan --workspace /work/coffee",
    "oasis --project /p migrate --workspace=/work/coffee --plan 2>&1 | tail -40",
    "python3 tools/migrate.py --plan",
    "oasis migrate -h 2>&1 | head -20",
    "python3 tools/migrate.py --help",
    "./tools/worktree-init --help",
    "oasis --project /p worktree-init -h",
  ];
  for (const command of allowed) {
    assert.equal(blockedProgram(command), null, command);
  }
});

test("text that bash does run stays blocked", () => {
  const blocked: [string, string][] = [
    ["git commit -m \"docs: `psql -l`\"", "psql"],
    ["echo \"it's $(dropdb x)\"", "dropdb"],
    ["bash <<'EOF'\npsql -l\nEOF", "psql"],
    ["sudo sh <<EOF\ndropdb x\nEOF", "dropdb"],
    ["cat <<EOF\n$(psql -Atc 'select 1')\nEOF", "psql"],
    ["cat > f <<'EOF'\ntext\nEOF\npsql -l", "psql"],
    ["echo 'a' ; psql -l", "psql"],
    ["bash<<EOF\npsql -l\nEOF", "psql"],
    ["sh<<'EOF'\ndropdb x\nEOF", "dropdb"],
    ["source /dev/stdin <<'EOF'\ndropdb x\nEOF", "dropdb"],
    ["ssh host <<'EOF'\npsql -l\nEOF", "psql"],
    ["echo hi # don't stop\necho $(psql -l)", "psql"],
    ["true # <<EOF\npsql -l\nEOF", "psql"],
    ["echo $'it\\'s' $(dropdb x)", "dropdb"],
    ["echo hi;# don't\necho $(psql -l)", "psql"],
    ["true &&# don't\necho $(dropdb x)", "dropdb"],
    ["echo a\\ #$(psql -l)", "psql"],
    ["echo ${#items} $(psql -l)", "psql"],
    ["bash \\\n<<'EOF'\npsql -l\nEOF", "psql"],
    ["cat <<'EOF' |\npsql -l\nEOF\nsh", "psql"],
    ["ksh <<'EOF'\ndropdb x\nEOF", "dropdb"],
    ["fish <<'EOF'\npsql -l\nEOF", "psql"],
    ["docker exec -i db sh <<'EOF'\npsql -l\nEOF", "psql"],
    ["cat <<'EOF' | bash\ndropdb x\nEOF", "dropdb"],
    ["xargs -I{} {} <<'EOF'\npsql -l\nEOF", "psql"],
    ["cat <<'EOF' \\\n| sh\npsql -l\nEOF", "psql"],
    ["cat <<'EOF' | \\\nsh\ndropdb x\nEOF", "dropdb"],
    ["kubectl exec -i pod -- sh <<'EOF'\npsql -l\nEOF", "psql"],
    ["podman exec -i db bash <<'EOF'\ndropdb x\nEOF", "dropdb"],
    ["setsid sh <<'EOF'\npsql -l\nEOF", "psql"],
    ["oasis --project /p migrate --apply --help", "migrate"],
    ["oasis --project /p migrate --plan --apply", "migrate"],
    ["oasis --project /p migrate --apply --plan", "migrate"],
    ["oasis --project /p migrate --apply # --plan", "migrate"],
    ["oasis --project /p migrate --plan $EXTRA", "migrate"],
    ["oasis --project /p migrate --plan --workspace $HOME/x", "migrate"],
    ["oasis --project /p migrate --plan --workspace relative/dir", "migrate"],
    ["oasis --project /p migrate --workspace --plan --apply", "migrate"],
    ["oasis --project /p migrate --plan --plan", "migrate"],
    ["oasis --project /p migrate --plan; oasis --project /p migrate --apply", "migrate"],
    ["oasis --project /p migrate --plan > plan.txt", "migrate"],
    ["oasis --project /p worktree-init --plan", "worktree-init"],
    ["setsid psql -l", "psql"],
    ["stdbuf -o L dropdb x", "dropdb"],
    ["ionice -c 3 odoo-bin -d x", "odoo-bin"],
    ["doas -u postgres psql", "psql"],
    ["sudo ssh host <<'EOF'\npsql -l\nEOF", "psql"],
    ["time su postgres <<'EOF'\ndropdb x\nEOF", "dropdb"],
    ["env A=1 source /dev/stdin <<'EOF'\npsql -l\nEOF", "psql"],
    ["{ ssh host; } <<'EOF'\npsql -l\nEOF", "psql"],
    ["if true; then eval \"$(cat)\"; fi <<'EOF'\ndropdb x\nEOF", "dropdb"],
    ["doas su - postgres <<'EOF'\npsql -l\nEOF", "psql"],
    ["oasis --project /p migrate", "migrate"],
    ["./tools/worktree-init shop feature/x --help", "worktree-init"],
  ];
  for (const [command, program] of blocked) {
    assert.equal(blockedProgram(command), program, command);
  }
});

test("command -v / -V and which only look up the program", () => {
  for (const command of ["command -v psql", "command -V odoo-bin", "which dropdb", "type psql"]) {
    assert.equal(blockedProgram(command), null, command);
  }
});

test("blocks agents from running the menu through the entry points or its tool, --catalog included", () => {
  const blocked = [
    "oasis --project /p menu",
    "oasis --project /p menu --catalog",
    "oasis --project=/p menu",
    "~/.agents/skills/odoo19/oasis --project /p menu",
    "~/.agents/skills/odoo19/odoo19 --project /p menu --catalog",
    "python3 -B /opt/oasis/oasis --project /p menu",
    "cd /p && odoo19 --project /p menu",
    "env A=1 python3 oasis --project /p menu",
    "bash -c 'oasis --project /p menu'",
    "echo $(oasis --project /p menu --catalog)",
    "timeout 60 oasis --project /p menu",
    "setsid oasis --project /p menu",
    "oasis --project /p menu --help --catalog",
    "oasis --project /p menu --catalog > catalog.json",
    "~/.agents/skills/odoo19/tools/menu",
    "/home/u/.agents/skills/odoo19/tools/actions.py --catalog",
    "bash ~/.agents/skills/odoo19/tools/menu --catalog",
    "python3 -I -B ~/.agents/skills/odoo19/tools/actions.py",
  ];
  for (const command of blocked) {
    assert.equal(blockedProgram(command), "menu", command);
  }
});

test("allows the menu's help and commands that only mention menu", () => {
  const allowed = [
    "oasis --project /p menu --help",
    "odoo19 --project /p menu -h 2>&1 | head -20",
    "./tools/menu --help",
    "oasis --project /p test-module menu",
    "oasis --project /p model-info menu.item",
    "grep -n menu tools/actions.py",
    "cat tools/menu",
    "python3 -B -m unittest tests.test_menu",
    "./menu.sh",
    "python3 actions.py",
    "git log --grep=menu",
  ];
  for (const command of allowed) {
    assert.equal(blockedProgram(command), null, command);
  }
});

test("blockReason for menu sends the user to the terminal menu or the panel", () => {
  assert.equal(
    blockReason("menu", "/work/coffee"),
    "menu is the user's interactive action menu; ask the user to run `oasis --project <root> menu` in a " +
      "terminal or to open the oasis panel in Gentle Shell.",
  );
});

test("user-run programs are blocked in every session, the others only in Odoo projects", () => {
  for (const program of ["migrate", "worktree-init", "menu"]) assert.equal(blockedEverywhere(program), true, program);
  for (const program of ["psql", "dropdb", "odoo-bin"]) assert.equal(blockedEverywhere(program), false, program);
});

test("menu's script forms are blocked only in the installed bundle, not in unrelated projects", () => {
  const allowed = [
    "./tools/menu",
    "tools/menu --catalog",
    "bash /work/shop/tools/menu",
    "python3 tools/actions.py",
    "python3 -B /work/shop/tools/actions.py --catalog",
    "/opt/oasis/tools/menu",
  ];
  for (const command of allowed) {
    assert.equal(blockedProgram(command), null, command);
  }
  const blocked = [
    "oasis menu",
    "odoo19 menu",
    "~/.agents/skills/odoo19/oasis --project /p menu",
    "~/.agents/skills/odoo19/tools/menu",
    "sh /home/u/.agents/skills/odoo19/tools/menu",
    "python3 -I -B ~/.agents/skills/odoo19/tools/actions.py --catalog",
  ];
  for (const command of blocked) {
    assert.equal(blockedProgram(command), "menu", command);
  }
});

test("migrate and worktree-init script forms stay blocked in any tools directory (unchanged)", () => {
  const blocked: [string, string][] = [
    ["./tools/migrate --apply", "migrate"],
    ["bash /work/shop/tools/migrate", "migrate"],
    ["python3 /opt/oasis/tools/migrate.py --apply", "migrate"],
    ["./tools/worktree-init feat x", "worktree-init"],
    ["python3 /work/shop/worktree_init.py feat x", "worktree-init"],
  ];
  for (const [command, program] of blocked) {
    assert.equal(blockedProgram(command), program, command);
  }
  for (const command of ["./migrate --apply", "python3 migrate.py"]) {
    assert.equal(blockedProgram(command), null, command);
  }
});

// A fake file system for the menu script checks: the installed bundle, an oasis source checkout and
// an unrelated project that happens to have tools/menu and tools/actions.py.
const HOME = "/home/u";
const BUNDLE = `${HOME}/.agents/skills/odoo19`;
const SOURCE = "/work/oasis";
const FILES = new Set([
  ...[BUNDLE, SOURCE].flatMap((root) => [`${root}/oasis`, `${root}/tools/actions.py`, `${root}/tools/menu`]),
  "/work/shop/tools/menu",
  "/work/shop/tools/actions.py",
]);
const at = (cwd: string) => ({ cwd, home: HOME, exists: (path: string) => FILES.has(path) });

test("menu scripts are blocked by what they resolve to, also relative or after a literal cd", () => {
  const blocked: [string, string][] = [
    ["/work/shop", "cd ~/.agents/skills/odoo19 && tools/menu"],
    ["/work/shop", "cd ~/.agents/skills/odoo19/tools && ./menu --catalog"],
    ["/work/shop", "cd ~/.agents/skills/odoo19/tools; python3 actions.py"],
    [BUNDLE, "python3 tools/actions.py"],
    [BUNDLE, "python3 -I -B tools/actions.py --catalog"],
    [`${BUNDLE}/tools`, "./menu"],
    [SOURCE, "tools/menu"],
    [SOURCE, "bash tools/menu --catalog"],
    ["/tmp", "cd /work/oasis; python3 -B tools/actions.py"],
    ["/work/shop", "cd /work && cd oasis && tools/menu"],
    ["/work/shop", "cd ../oasis && ./tools/menu"],
    ["/work/shop", "/work/oasis/tools/menu"],
    ["/work/shop", "~/.agents/skills/odoo19/tools/menu"],
    ["/work/shop", "cd ~ && .agents/skills/odoo19/tools/menu"],
    ["/work/shop", "cd && .agents/skills/odoo19/tools/menu"],
    ["/work/shop", "pushd /work/oasis && tools/menu"],
    [BUNDLE, "bash -c 'tools/menu'"],
    [BUNDLE, "echo $(tools/menu --catalog)"],
    [BUNDLE, "timeout 60 tools/menu"],
    // Unknown targets: blocked when the word is tools/menu or tools/actions.py and the session
    // works inside an oasis tree.
    [SOURCE, "cd $DIR && tools/menu"],
    [`${SOURCE}/docs`, "$OASIS/tools/actions.py"],
    [BUNDLE, "cd $(mktemp -d) && tools/menu"],
  ];
  for (const [cwd, command] of blocked) {
    assert.equal(blockedProgram(command, at(cwd)), "menu", `${cwd}: ${command}`);
  }
});

test("an unresolved path spelled like the installed bundle stays blocked from any directory", () => {
  for (const command of [
    "$HOME/.agents/skills/odoo19/tools/menu",
    "${HOME}/.agents/skills/odoo19/tools/menu --catalog",
    "python3 $HOME/.agents/skills/odoo19/tools/actions.py",
    "~other/.agents/skills/odoo19/tools/menu",
  ]) {
    assert.equal(blockedProgram(command, at("/work/shop")), "menu", command);
  }
});

test("unrelated tools/menu scripts stay allowed with the session context", () => {
  const allowed: [string, string][] = [
    ["/work/shop", "./tools/menu"],
    ["/work/shop", "tools/menu --catalog"],
    ["/work/shop", "python3 tools/actions.py"],
    ["/work/shop", "bash tools/menu"],
    ["/work/shop", "/work/shop/tools/menu"],
    [BUNDLE, "cd /work/shop && tools/menu"],
    ["/work/shop", "cd $DIR && tools/menu"],
    [SOURCE, "cd $DIR && ./menu"],
    ["/work/shop", "cd ~/.agents/skills/odoo19 && ./menu"],
    [BUNDLE, "tools/menu --help"],
    [BUNDLE, "cat tools/menu"],
    [BUNDLE, "grep -n menu tools/actions.py"],
    [SOURCE, "python3 -B -m unittest tests.test_menu"],
  ];
  for (const [cwd, command] of allowed) {
    assert.equal(blockedProgram(command, at(cwd)), null, `${cwd}: ${command}`);
  }
});

test("with the session context the entry points, migrate and worktree-init are unchanged", () => {
  const cases: [string, string | null][] = [
    ["oasis menu", "menu"],
    ["odoo19 --project /p menu --catalog", "menu"],
    ["~/.agents/skills/odoo19/oasis --project /p menu", "menu"],
    ["oasis --project /p menu --help", null],
    ["./tools/migrate --apply", "migrate"],
    ["python3 /opt/oasis/tools/migrate.py --apply", "migrate"],
    ["oasis --project /p migrate --plan", null],
    ["tools/worktree-init feat x", "worktree-init"],
    ["oasis --project /p worktree-init feat x", "worktree-init"],
    ["psql -l", "psql"],
  ];
  for (const cwd of ["/work/shop", BUNDLE, SOURCE]) {
    for (const [command, program] of cases) {
      assert.equal(blockedProgram(command, at(cwd)), program, `${cwd}: ${command}`);
    }
  }
});

test("the extension passes the session cwd, the home directory and a file check to the guard", () => {
  // The extension gives the gates (lib/destructive.ts) its home and file check; toolCallRouter gives
  // each call its cwd (pi/tests/destructive.test.ts proves it by behaviour). The gate classifies with them.
  const source = readFileSync(new URL("../extensions/oasis.ts", import.meta.url), "utf8");
  assert.match(source, /const gateEffects: GateEffects = \{[^]*?home: homedir\(\),\s+exists: existsSync,/);
  assert.match(source, /const routeToolCall = toolCallRouter\(gateEffects\);/);
  const gate = readFileSync(new URL("../lib/destructive.ts", import.meta.url), "utf8");
  assert.match(gate,
    /classifyBash\(command, \{\s+cwd: ctx\.cwd, home: effects\.home, exists: effects\.exists, settingFile: settingFiles\(effects, ctx\.cwd\),\s+\}\)/);
});

// S3 tiers: the ask commands (drop-database, stop --database, gc --apply --trash) through the entry
// points and the oasis tools, judged like the deny tier's commands.
const DROP = (database: string | null) => ({ command: "drop-database", database });
const STOP = { command: "stop --database" };
const PURGE = { command: "gc --apply --trash" };
// An ask command with the project it targets: the entry point's --project, a tool script's
// OASIS_PROJECT_ROOT or ODOO19_PROJECT_ROOT; null when the text does not tell it.
const AT = (action: object, project: string | null) => ({ ...action, project });

test("classifyBash finds the ask commands through the entry points and their launchers", () => {
  const cases: [string, object[]][] = [
    ["oasis --project /p drop-database cc_dev_x", [AT(DROP("cc_dev_x"), "/p")]],
    ["odoo19 --project /p drop-database cc_test_x --terminate", [AT(DROP("cc_test_x"), "/p")]],
    ["oasis --project=/p drop-database 'cc_dev_x'", [AT(DROP("cc_dev_x"), "/p")]],
    ["~/.agents/skills/odoo19/oasis --project /p drop-database cc_dev_x 2>&1 | tail -5", [AT(DROP("cc_dev_x"), "/p")]],
    ["python3 -B /opt/oasis/oasis --project /p drop-database cc_dev_x", [AT(DROP("cc_dev_x"), "/p")]],
    ["cd /p && timeout 60 oasis --project /p drop-database cc_dev_x", [AT(DROP("cc_dev_x"), "/p")]],
    ["bash -c 'odoo19 --project /p drop-database cc_dev_x'", [AT(DROP("cc_dev_x"), "/p")]],
    ["echo $(oasis --project /p drop-database cc_dev_x)", [AT(DROP("cc_dev_x"), "/p")]],
    ["oasis --project /p drop-database $DB", [AT(DROP(null), "/p")]],
    ["oasis --project /p drop-database \"$(cat name)\"", [AT(DROP(null), "/p")]],
    ["oasis --project /p drop-database", [AT(DROP(null), "/p")]],
    ["oasis --project /p drop-database --terminate", [AT(DROP(null), "/p")]],
    ["oasis --project /p stop --database", [AT(STOP, "/p")]],
    ["env A=1 python3 odoo19 --project /p stop --database", [AT(STOP, "/p")]],
    ["oasis --project /p gc --apply --trash", [AT(PURGE, "/p")]],
    ["oasis --project /p gc --trash --older-than 0 --apply", [AT(PURGE, "/p")]],
    ["sudo -u me odoo19 --project /p gc --apply --trash --older-than 3", [AT(PURGE, "/p")]],
    ["oasis --project /p drop-database a_dev_x && oasis --project /p stop --database", [AT(DROP("a_dev_x"), "/p"), AT(STOP, "/p")]],
  ];
  for (const [command, asks] of cases) {
    assert.deepEqual(classifyBash(command), { program: null, programs: [], asks }, command);
  }
});

test("classifyBash names the project an ask command targets, as the entry point and the tools read it", () => {
  const OTHER = "/work/other";
  const cases: [string, object[]][] = [
    ["oasis --project /work/other drop-database cc_dev_x", [AT(DROP("cc_dev_x"), OTHER)]],
    ["odoo19 --project=/work/other stop --database", [AT(STOP, OTHER)]],
    // argparse takes an unambiguous prefix of --project, and the last one given.
    ["oasis --proj /work/other gc --apply --trash", [AT(PURGE, OTHER)]],
    ["oasis --p=/work/other drop-database cc_dev_x", [AT(DROP("cc_dev_x"), OTHER)]],
    ["oasis --project /work/shop --project /work/other stop --database", [AT(STOP, OTHER)]],
    ["oasis --project /work/other/./addons/.. stop --database", [AT(STOP, OTHER)]],
    ["oasis --project ~/shop stop --database", [AT(STOP, "/home/u/shop")]],
    ["oasis --project $P drop-database cc_dev_x", [AT(DROP("cc_dev_x"), null)]],
    ["oasis --project \"$(pwd)\" stop --database", [AT(STOP, null)]],
    ["oasis --project=~/shop stop --database", [AT(STOP, null)]],
    ["oasis --project", []],
    ["oasis stop --database", [STOP]],
    ["ODOO19_PROJECT_ROOT=/work/other ~/.agents/skills/odoo19/tools/drop-database cc_dev_x", [AT(DROP("cc_dev_x"), OTHER)]],
    ["env OASIS_PROJECT_ROOT=/work/other ~/.agents/skills/odoo19/tools/stop --database", [AT(STOP, OTHER)]],
    ["OASIS_PROJECT_ROOT= ODOO19_PROJECT_ROOT=/work/other bash ~/.agents/skills/odoo19/tools/gc --apply --trash",
      [AT(PURGE, OTHER)]],
    ["ODOO19_PROJECT_ROOT=/work/shop OASIS_PROJECT_ROOT=/work/other ~/.agents/skills/odoo19/tools/stop --database",
      [AT(STOP, OTHER)]],
    ["OASIS_PROJECT_ROOT=\"$P\" ~/.agents/skills/odoo19/tools/stop --database", [AT(STOP, null)]],
    ["OASIS_PROJECT_ROOT=../other ~/.agents/skills/odoo19/tools/stop --database", [AT(STOP, OTHER)]],
    ["~/.agents/skills/odoo19/tools/drop-database cc_dev_x", [DROP("cc_dev_x")]],
  ];
  for (const [command, asks] of cases) {
    assert.deepEqual(classifyBash(command, at("/work/shop")), { program: null, programs: [], asks }, command);
  }
});

test("without --project an entry point targets the directory it runs in: the session's, a literal cd, else unknown", () => {
  // v0.14.0 S8: the entry point then takes the git top level of its current directory. Absent: the
  // session's own directory; null: a directory the text does not tell.
  const OTHER = "/work/other";
  const cases: [string, object[]][] = [
    ["oasis drop-database cc_dev_x", [DROP("cc_dev_x")]],
    ["odoo19 stop --database", [STOP]],
    ["cd /work/shop && oasis gc --apply --trash", [PURGE]],
    ["cd /work/other && oasis drop-database cc_dev_x", [AT(DROP("cc_dev_x"), OTHER)]],
    ["cd ../other; odoo19 stop --database", [AT(STOP, OTHER)]],
    ["pushd /work/other && oasis gc --apply --trash", [AT(PURGE, OTHER)]],
    ["cd addons && oasis stop --database", [AT(STOP, "/work/shop/addons")]],
    ["cd && oasis stop --database", [AT(STOP, "/home/u")]],
    ["cd $DIR && oasis stop --database", [AT(STOP, null)]],
    ["cd - && oasis stop --database", [AT(STOP, null)]],
    ["pushd /work/other; popd; oasis stop --database", [AT(STOP, null)]],
    // Wrappers that change the directory of the command they run.
    ["env -C /work/other oasis stop --database", [AT(STOP, OTHER)]],
    ["env --chdir=/work/other oasis stop --database", [AT(STOP, OTHER)]],
    ["env --chdir /work/other A=1 oasis stop --database", [AT(STOP, OTHER)]],
    ["sudo -D /work/other oasis stop --database", [AT(STOP, OTHER)]],
    ["sudo --chdir=/work/other odoo19 stop --database", [AT(STOP, OTHER)]],
    ["env -C $D oasis stop --database", [AT(STOP, null)]],
    // A shell command starts where the line is; a substitution on a line that changes directory is unknown.
    ["cd /work/other && bash -c 'oasis stop --database'", [AT(STOP, OTHER)]],
    ["bash -c 'cd /work/other && oasis stop --database'", [AT(STOP, OTHER)]],
    ["cd /work/other && echo $(oasis stop --database)", [AT(STOP, null)]],
    ["echo $(oasis stop --database)", [STOP]],
    // --project still names the target, wherever the line runs.
    ["cd /work/other && oasis --project /work/shop stop --database", [AT(STOP, "/work/shop")]],
    ["env -C /work/shop oasis --project /work/other stop --database", [AT(STOP, OTHER)]],
    // A tool script reads its root variable, not the directory: unchanged.
    ["cd /work/other && ~/.agents/skills/odoo19/tools/stop --database", [STOP]],
  ];
  for (const [command, asks] of cases) {
    assert.deepEqual(classifyBash(command, at("/work/shop")), { program: null, programs: [], asks }, command);
  }
});

test("a directory change the guard cannot follow makes the target of an entry point without --project unknown", () => {
  // L7 R1-guard-cd-variants: never the session's project after a change the text does not tell.
  const OTHER = "/work/other";
  const unknown: string[] = [
    "builtin cd /work/other && oasis stop --database",
    "command cd /work/other && oasis stop --database",
    "command -p cd /work/other; odoo19 stop --database",
    // L10 R3-001: `--` ends the runner's options; the forms with it change the directory too.
    "command -- cd /work/other && oasis stop --database",
    "builtin -- cd /work/other && oasis stop --database",
    "command -p -- cd /work/other; oasis stop --database",
    "time -p cd /work/other && oasis stop --database",
    "time -p -- cd /work/other && oasis stop --database",
    "command -- popd; oasis stop --database",
    // Only command's own options look a program up: a later -v is cd's argument (a directory).
    "command cd -- -v && oasis stop --database",
    "command -- cd -- -V; oasis stop --database",
    "builtin pushd /work/other && oasis stop --database",
    "command popd; oasis stop --database",
    "time cd /work/other && oasis stop --database",
    "eval cd /work/other && oasis stop --database",
    "eval \"cd /work/other\"; oasis stop --database",
    "eval \"$GO\" && oasis stop --database",
    "source ./go.sh && oasis stop --database",
    ". ./go.sh; oasis stop --database",
    "$CD /work/other && oasis stop --database",
    "\"$(echo cd)\" /work/other && oasis stop --database",
    "c? /work/other && oasis stop --database",
    "if builtin cd /work/other; then oasis stop --database; fi",
    "A=1 builtin cd /work/other && oasis stop --database",
    // A substitution on a line with such a change does not know where it runs either.
    "builtin cd /work/other && echo $(oasis stop --database)",
  ];
  for (const command of unknown) {
    assert.deepEqual(classifyBash(command, at("/work/shop")), { program: null, programs: [], asks: [AT(STOP, null)] }, command);
  }
  // Unchanged: what the guard follows, what only looks a program up, and --project.
  const kept: [string, object[]][] = [
    ["command -v oasis && oasis stop --database", [STOP]],
    ["command -pv cd && oasis stop --database", [STOP]],
    ["command -p -V cd; oasis stop --database", [STOP]],
    ["[ -d addons ] && oasis stop --database", [STOP]],
    ["[[ -d addons ]] && oasis stop --database", [STOP]],
    ["echo cd /work/other && oasis stop --database", [STOP]],
    ["eval \"cd /work/other && oasis stop --database\"", [AT(STOP, OTHER)]],
    ["builtin cd /work/other && oasis --project /work/shop stop --database", [AT(STOP, "/work/shop")]],
    ["eval cd /x; oasis --project /work/other stop --database", [AT(STOP, OTHER)]],
    ["cd /work/other && oasis drop-database cc_dev_x", [AT(DROP("cc_dev_x"), OTHER)]],
  ];
  for (const [command, asks] of kept) {
    assert.deepEqual(classifyBash(command, at("/work/shop")), { program: null, programs: [], asks }, command);
  }
  // The deny tier is unchanged by an unknown directory.
  assert.deepEqual(classifyBash("builtin cd /p && oasis migrate --apply", at("/work/shop")).programs, ["migrate"]);
});

test("the entry point's --project abbreviations do not hide its command from either tier", () => {
  for (const [command, programs] of [
    ["oasis --proj /p migrate --apply", ["migrate"]],
    ["odoo19 --pro=/p menu", ["menu"]],
    ["oasis --p /p menu --catalog", ["menu"]],
    // The plan of migrate stays readable, as with --project.
    ["oasis --proj /p migrate --plan", []],
  ] as const) {
    assert.deepEqual(classifyBash(command).programs, programs, command);
  }
  assert.deepEqual(classifyBash("oasis --proj /p drop-database cc_dev_x").asks, [AT(DROP("cc_dev_x"), "/p")]);
  // Other options are not --project: their next word is the command, as before.
  assert.deepEqual(classifyBash("oasis -v menu").programs, ["menu"]);
});

test("classifyBash finds the ask commands through the oasis tool scripts, judged like the menu's", () => {
  const cases: [string, string, object[]][] = [
    ["/work/shop", "~/.agents/skills/odoo19/tools/drop-database cc_dev_x", [DROP("cc_dev_x")]],
    ["/work/shop", "bash ~/.agents/skills/odoo19/tools/stop --database", [STOP]],
    ["/work/shop", "$HOME/.agents/skills/odoo19/tools/gc --apply --trash", [PURGE]],
    ["/work/shop", "cd ~/.agents/skills/odoo19 && tools/drop-database cc_dev_x", [DROP("cc_dev_x")]],
    [BUNDLE, "./tools/stop --database", [STOP]],
    [SOURCE, "bash tools/gc --apply --trash", [PURGE]],
    [`${SOURCE}/tools`, "./drop-database cc_dev_x", [DROP("cc_dev_x")]],
  ];
  for (const [cwd, command, asks] of cases) {
    assert.deepEqual(classifyBash(command, at(cwd)), { program: null, programs: [], asks }, `${cwd}: ${command}`);
  }
  // Without the session context only the installed bundle's spelling counts, as for the menu.
  assert.deepEqual(classifyBash("~/.agents/skills/odoo19/tools/stop --database"), { program: null, programs: [], asks: [STOP] });
  assert.deepEqual(classifyBash("./tools/stop --database"), { program: null, programs: [], asks: [] });
});

test("classifyBash allows every other oasis command, help alone and unrelated scripts", () => {
  const allowed: [string, string][] = [
    ["/work/shop", "oasis --project /p test-module coffee"],
    ["/work/shop", "oasis --project /p verify-module coffee"],
    ["/work/shop", "oasis --project /p gc"],
    ["/work/shop", "oasis --project /p gc --apply"],
    ["/work/shop", "oasis --project /p gc --apply --all-checkouts"],
    ["/work/shop", "oasis --project /p gc --trash"],
    ["/work/shop", "oasis --project /p gc --trash --older-than 0"],
    ["/work/shop", "oasis --project /p stop"],
    // S6: the checkout's own server, in the allow tier.
    ["/work/shop", "oasis --project /p stop --force"],
    ["/work/shop", "oasis --project /p restart"],
    ["/work/shop", "odoo19 --project /p restart -d cc_dev_x --workers=0"],
    ["/work/shop", "oasis --project /p restart --database cc_dev_x"],
    ["/work/shop", "oasis --project /p status"],
    ["/work/shop", "~/.agents/skills/odoo19/tools/stop --force"],
    ["/work/shop", "~/.agents/skills/odoo19/tools/restart --http-port=8070"],
    ["/work/shop", "oasis --project /p install-module coffee cc_dev_x"],
    ["/work/shop", "oasis --project /p update-module coffee cc_dev_x"],
    ["/work/shop", "oasis --project /p create-database cc_dev_x"],
    ["/work/shop", "oasis --project /p trash"],
    ["/work/shop", "oasis --project /p trash restore cc_dev_x_trash_20261124_101500"],
    ["/work/shop", "oasis --project /p start --detach"],
    ["/work/shop", "oasis --project /p drop-database --help"],
    ["/work/shop", "oasis --project /p stop -h"],
    ["/work/shop", "odoo19 --project /p gc --help 2>&1 | head"],
    ["/work/shop", "oasis --project /p test-module drop-database"],
    ["/work/shop", "oasis --project /p model-info stop.database --field gc"],
    ["/work/shop", "grep -n drop-database tools/drop-database"],
    ["/work/shop", "cat ~/.agents/skills/odoo19/tools/gc"],
    ["/work/shop", "git commit -m 'oasis drop-database cc_dev_x'"],
    ["/work/shop", "tools/stop --database"],
    ["/work/shop", "./tools/gc --apply --trash"],
    ["/work/shop", "docker compose stop db"],
    ["/work/shop", "~/.agents/skills/odoo19/tools/drop-database --help"],
  ];
  for (const [cwd, command] of allowed) {
    assert.deepEqual(classifyBash(command, at(cwd)), { program: null, programs: [], asks: [] }, `${cwd}: ${command}`);
  }
});

test("agents may run start and restart --print-command: neither tier blocks or asks (v0.12.1 S5)", () => {
  for (const command of [
    "oasis --project /p start --print-command",
    "oasis --project /p start --print-command --detach -d cc_dev_x --dev xml",
    "odoo19 --project /p start --print-command --stop-after-init -u coffee",
    "oasis --project /p restart --print-command",
    "odoo19 --project /p restart --print-command -d cc_dev_x --http-port 8070",
    "~/.agents/skills/odoo19/tools/start --print-command --workers=0",
    "~/.agents/skills/odoo19/tools/restart --print-command",
    "oasis --project /p start --print-command -w secret 2>&1 | head -1",
  ]) {
    for (const context of [undefined, at("/work/shop")]) {
      assert.deepEqual(classifyBash(command, context), { program: null, programs: [], asks: [] }, command);
      assert.equal(blockedProgram(command, context), null, command);
    }
  }
});

test("the deny tier is unchanged: blockedProgram ignores the ask commands and still finds the denied ones", () => {
  for (const command of [
    "oasis --project /p drop-database cc_dev_x",
    "oasis --project /p stop --database",
    "oasis --project /p gc --apply --trash",
    "~/.agents/skills/odoo19/tools/drop-database cc_dev_x",
  ]) {
    assert.equal(blockedProgram(command), null, command);
    assert.equal(blockedProgram(command, at("/work/shop")), null, command);
  }
  const denied: [string, string][] = [
    ["oasis --project /p drop-database cc_dev_x; psql -l", "psql"],
    ["oasis --project /p migrate --apply && oasis --project /p stop --database", "migrate"],
    ["dropdb x; oasis --project /p menu", "dropdb"],
    ["oasis --project /p gc --apply --trash | oasis --project /p worktree-init f b", "worktree-init"],
  ];
  for (const [command, program] of denied) {
    assert.equal(blockedProgram(command), program, command);
    assert.equal(classifyBash(command).program, program, command);
  }
  assert.deepEqual(classifyBash("oasis --project /p drop-database cc_dev_x; psql -l").asks, [AT(DROP("cc_dev_x"), "/p")]);
});

test("classifyBash lists every denied program of a line, in order; program stays the first", () => {
  const cases: [string, string[]][] = [
    ["psql -l; oasis --project /p migrate --apply", ["psql", "migrate"]],
    ["dropdb x && oasis --project /p menu", ["dropdb", "menu"]],
    ["echo $(oasis --project /p worktree-init f b); odoo-bin -d x", ["worktree-init", "odoo-bin"]],
    ["oasis --project /p drop-database cc_dev_x; psql -l | psql x", ["psql", "psql"]],
    ["psql -l", ["psql"]],
    ["oasis --project /p migrate --apply", ["migrate"]],
    ["git status", []],
  ];
  for (const [command, programs] of cases) {
    const found = classifyBash(command);
    assert.deepEqual(found.programs, programs, command);
    assert.equal(found.program, programs[0] ?? null, command);
    assert.equal(blockedProgram(command), programs[0] ?? null, command);
  }
});

// S4 hole: the files that hold [tooling].agent_destructive. The extension decides which paths those
// are (lib/destructive.ts); here a fixed check stands in for it.
const SETTING_FILES = new Set(["/work/shop/oasis-workspace.toml", "/work/shop/.odoo19-agent.toml"]);
const SETTING_NAMES = new Set(["oasis-workspace.toml", ".odoo19-agent.toml"]);
const guarded = (cwd: string) => ({
  ...at(cwd),
  settingFile: (path: string | null, word: string) =>
    path === null ? (SETTING_NAMES.has(word.slice(word.lastIndexOf("/") + 1)) ? word : null)
      : SETTING_FILES.has(path) ? path : null,
});
const EDIT = (file: string) => ({ command: "edit", file });

test("classifyBash finds bash writes to the setting files: redirection, tee, sed -i, mv and cp onto them", () => {
  const workspace = EDIT("/work/shop/oasis-workspace.toml");
  const profile = EDIT("/work/shop/.odoo19-agent.toml");
  const cases: [string, object[]][] = [
    ["echo \"agent_destructive = 'allow'\" >> ../oasis-workspace.toml", [workspace]],
    ["printf x >/work/shop/.odoo19-agent.toml", [profile]],
    ["cat a 2>/dev/null > /work/shop/oasis-workspace.toml", [workspace]],
    ["echo x &> /work/shop/oasis-workspace.toml", [workspace]],
    ["echo x >| /work/shop/oasis-workspace.toml", [workspace]],
    ["tee -a /work/shop/oasis-workspace.toml < new.toml", [workspace]],
    ["cat new | sudo tee ../.odoo19-agent.toml >/dev/null", [profile]],
    ["sed -i \"s/ask/allow/\" ../oasis-workspace.toml", [workspace]],
    ["sed -i.bak -e s/ask/allow/ /work/shop/.odoo19-agent.toml", [profile]],
    ["sed --in-place s/a/b/ ../oasis-workspace.toml", [workspace]],
    ["mv /tmp/x /work/shop/oasis-workspace.toml", [workspace]],
    ["cp -f /tmp/oasis-workspace.toml /work/shop/", [workspace]],
    ["cp -t /work/shop /tmp/.odoo19-agent.toml", [profile]],
    ["cd .. && echo x > oasis-workspace.toml", [workspace]],
    ["bash -c 'echo x > /work/shop/oasis-workspace.toml'", [workspace]],
    ["echo x > $ROOT/oasis-workspace.toml", [EDIT("$ROOT/oasis-workspace.toml")]],
    ["oasis --project /p stop --database > ../oasis-workspace.toml", [AT(STOP, "/p"), workspace]],
  ];
  for (const [command, asks] of cases) {
    assert.deepEqual(classifyBash(command, guarded("/work/shop/addons")), { program: null, programs: [], asks }, command);
  }
  for (const command of [
    "cat ../oasis-workspace.toml",
    "grep agent_destructive ../oasis-workspace.toml > /tmp/found",
    "sed -n 1p ../oasis-workspace.toml",
    "cp ../oasis-workspace.toml /tmp/copy.toml",
    "echo x > /tmp/oasis-workspace.toml.bak",
    "git diff ../oasis-workspace.toml",
    "echo x > notes.md 2>&1",
    "tee -a log.txt < ../oasis-workspace.toml",
  ]) {
    assert.deepEqual(classifyBash(command, guarded("/work/shop/addons")), { program: null, programs: [], asks: [] }, command);
  }
  // Without the extension's check nothing is a setting file.
  assert.deepEqual(classifyBash("echo x > /work/shop/oasis-workspace.toml", at("/work/shop")).asks, []);
});

// v0.14.0 S1, L12: agents may read the plan of `oasis setup`; `setup --apply` writes configuration.
test("allows setup's plan through the entry points and blocks setup --apply", () => {
  const allowed = [
    "oasis setup",
    "oasis setup --plan",
    "odoo19 --project /p setup --community /src/odoo --no-enterprise",
    "~/.agents/skills/odoo19/oasis --project=/p setup --series 19.0 --workspace /w --name acme 2>&1 | tail -40",
    "cd /p && oasis setup --enterprise /src/enterprise",
    "oasis setup --help",
    "python3 setup.py install",
    "python setup.py --apply",
    "./setup --apply",
  ];
  for (const command of allowed) assert.equal(blockedProgram(command), null, command);
  const blocked = [
    "oasis setup --apply",
    "oasis setup --apply --help",
    "odoo19 --project /p setup --community /src/odoo --apply",
    "~/.agents/skills/odoo19/oasis setup --no-enterprise --apply",
    "python3 -B /opt/oasis/oasis --project /p setup --apply",
    "bash -c 'oasis setup --apply'",
    "echo $(oasis setup --apply)",
    "oasis setup --plan; oasis setup --apply",
    "oasis setup --apply=yes",
    "oasis setup --appl",
    "oasis setup $ARGS",
    "oasis setup --community $SRC",
    "oasis setup `echo --apply`",
    "~/.agents/skills/odoo19/tools/setup --apply",
    "python3 -I -B ~/.agents/skills/odoo19/tools/setup.py --apply",
  ];
  for (const command of blocked) assert.equal(blockedProgram(command), "setup", command);
});

test("setup's tool scripts count only in an oasis tree", () => {
  const context = {
    cwd: "/src/oasis", home: "/home/u",
    exists: (path: string) => path === "/src/oasis/oasis" || path === "/src/oasis/tools/actions.py",
  };
  assert.equal(blockedProgram("tools/setup --apply", context), "setup");
  assert.equal(blockedProgram("python3 tools/setup.py --apply", context), "setup");
  assert.equal(blockedProgram("tools/setup", context), null);
  assert.equal(blockedProgram("python3 /work/app/tools/setup.py --apply", context), null);
});

test("setup is user-run everywhere and its block reason sends the user to a terminal", () => {
  assert.equal(blockedEverywhere("setup"), true);
  assert.equal(
    blockReason("setup", "/work/coffee"),
    "setup --apply writes the project's and the machine's configuration and creates the environment; ask the " +
      "user to run `oasis setup --apply` in a terminal. To read the plan without changing anything, run it " +
      "without --apply.",
  );
});
