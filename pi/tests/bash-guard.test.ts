import { test } from "node:test";
import assert from "node:assert/strict";
import { blockedEverywhere, blockedProgram, blockReason } from "../lib/bash-guard.ts";

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
    "worktree-init creates links to environment files; ask the user to run /oasis worktree <feature> " +
      "<branch> in Gentle Shell or the command in a terminal.",
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
    "tools/menu",
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
