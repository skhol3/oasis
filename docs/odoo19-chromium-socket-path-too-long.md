# Odoo19: headless Chromium aborts because of its socket path

Date: 2026-11-10

The browser tests of the global `odoo19` bundle fail because headless Chromium aborts at startup: the path of its socket is 110 bytes long and the maximum is 107. The fix is to run the tests with a short `TMPDIR`.

## What happened

On 10 November 2026, between 21:40:47 and 21:43:46, systemd-coredump recorded 18 identical SIGABRTs of `/usr/lib/chromium/chromium`, one every ~10 seconds. Each one was a headless Chromium launched by an Odoo browser test (tour).

| Item | Value |
| --- | --- |
| Process chain | `verify-module` → `install-module` → `odoo-bin` (bundle `~/.agents/skills/odoo19/tools/`) |
| Database | `acme_test_acme_update` |
| Chromium | 155.0.8059.84-1 |
| Example PID | 2574356 |
| Stack | `ChromeMain` → `abort`, main thread, at startup |

Impact: every browser test of that run failed, so that `verify-module` result is not valid. No data was lost: the profiles were temporary.

## Cause

Chromium cannot create its singleton socket because the path is too long, and it aborts on purpose. The message came from the core's memory:

```
FATAL:chrome/browser/process_singleton_posix.cc:313] Socket path too long:
/tmp/gpB6f7cC/gachADTC/tmp.bumyjLXJec/tmp/tmp5uwjifu1_chrome_odoo/org.chromium.Chromium.B3vxqV/SingletonSocket
```

- **Proven:** that path is 110 bytes long. The path of a Unix socket (`sun_path`) holds at most 107 plus the NUL.
- **Inferred, not confirmed:** Odoo builds the `*_chrome_odoo` profile under `tempfile`, that is, under `$TMPDIR`. The session that ran the tests had a deeply nested `TMPDIR` (`/tmp/gpB6f7cC/gachADTC/tmp.bumyjLXJec/tmp`), probably the temp directory of an agent or sandbox. The process had already ended and its environment could not be read.

## Ruled out

- **Out of memory:** RAM was tight (474Mi free, 18Gi of swap in use), but the journal shows no OOM kill.
- **Omarchy flags** (`~/.config/chromium-flags.conf`): they add `--ozone-platform=wayland` and `--load-extension` to this run. With the same flags and a short path, Chromium started fine.
- **An Omarchy or Chromium bug:** it is not one, so there is nothing to report upstream.

## How to fix it

No change has been applied yet. Suggested steps:

- [ ] Run the tests again with a short temp directory: `TMPDIR=/tmp verify-module --compact <modules>`
- [ ] Confirm that no new Chromium cores appear with `coredumpctl list --since "10 min ago"`
- [ ] To keep it from happening again, export `TMPDIR=/tmp` in `~/.agents/skills/odoo19/tools/common.sh` (or shorten the `TMPDIR` of the agent that launches the tests)
- [ ] Save this finding in Engram, project `odoo19`, topic `odoo19/browser-tests/chromium-socket-path-too-long`

Quick diagnosis if it happens again: `coredumpctl dump <pid> --output=<file>`, then `strings <file> | grep FATAL`, and delete the core when done.
