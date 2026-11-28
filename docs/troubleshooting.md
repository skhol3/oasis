# Troubleshooting

## Tool-manager side effects

Before diagnostics, account for executable shims managed by tools such as mise. A version probe such as `uv --version` can trigger a tool-manager download/install before uv starts; `UV_OFFLINE=1` does not constrain mise. Do not call such a probe as strictly read-only unless the underlying executable is already available without automatic installation, or the exact tool-manager action has separate human authorization. The project cleanup verification encountered mise installing uv 0.13.7 this way; no automatic rollback was attempted. This also applies to `doctor --environment --quick` through the global entry point.

## Headless Chromium aborts in browser tests

When the browser tests of a module fail because headless Chromium aborts at startup (one SIGABRT core per
browser test), the path of its singleton socket is too long and Chromium aborts on purpose:

```
FATAL:chrome/browser/process_singleton_posix.cc:313] Socket path too long:
/tmp/gpB6f7cC/gachADTC/tmp.bumyjLXJec/tmp/tmp5uwjifu1_chrome_odoo/org.chromium.Chromium.B3vxqV/SingletonSocket
```

The path of a Unix socket (`sun_path`) holds at most 107 bytes plus the NUL; that one, seen on 19.0 in November
2026, is 110. Odoo builds the `*_chrome_odoo` profile under `tempfile`, that is, under `$TMPDIR`, so a deeply nested
`TMPDIR` (the temporary directory of an agent or a sandbox) is the likely cause. To read the message of a core:
`coredumpctl dump <pid> --output=<file>`, then `strings <file> | grep FATAL`, and delete the core when done.
Test runs now give the Odoo test process a short private `TMPDIR` (see
[Ports, temporary directory and browser evidence](testing.md#ports-temporary-directory-and-browser-evidence)).
