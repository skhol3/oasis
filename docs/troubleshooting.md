# Troubleshooting

## Tool-manager side effects

Before diagnostics, account for executable shims managed by tools such as mise. A version probe such as `uv --version` can trigger a tool-manager download/install before uv starts; `UV_OFFLINE=1` does not constrain mise. Do not call such a probe as strictly read-only unless the underlying executable is already available without automatic installation, or the exact tool-manager action has separate human authorization. The project cleanup verification encountered mise installing uv 0.13.7 this way; no automatic rollback was attempted. This also applies to `doctor --environment --quick` (and its deprecated alias `check-environment --quick`) through the global entry point.

## Headless Chromium aborts in browser tests

When the browser tests of a module fail because headless Chromium aborts at startup, the path of
its socket is too long; see [Headless Chromium aborts because of its socket path](odoo19-chromium-socket-path-too-long.md).
Test runs now give the Odoo test process a short private `TMPDIR` (see
[Ports, temporary directory and browser evidence](testing.md#ports-temporary-directory-and-browser-evidence)).
