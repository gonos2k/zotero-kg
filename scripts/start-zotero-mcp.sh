#!/usr/bin/env bash
# Launcher for the bundled `zotero` MCP server.
#
# Why this exists: Claude Code may spawn MCP servers with a MINIMAL PATH (e.g. when launched as a
# macOS GUI app) that excludes ~/.local/bin — exactly where `uv tool install` / `pipx` put the
# `zotero-mcp` binary. A bare `command: "zotero-mcp"` then fails with ENOENT and the server silently
# never appears in /mcp. This script resolves the binary from PATH first, then the common install
# dirs, and fails LOUDLY with an actionable message if it genuinely isn't installed.
set -euo pipefail

BIN=""
if command -v zotero-mcp >/dev/null 2>&1; then
  BIN="$(command -v zotero-mcp)"
else
  for d in \
    "$HOME/.local/bin" \
    "$HOME/.local/share/uv/tools/zotero-mcp-server/bin" \
    "$HOME/Library/Application Support/pipx/venvs/zotero-mcp-server/bin" \
    "/opt/homebrew/bin" \
    "/usr/local/bin"; do
    if [ -x "$d/zotero-mcp" ]; then BIN="$d/zotero-mcp"; break; fi
  done
fi

if [ -z "$BIN" ]; then
  echo "zotero-kg: 'zotero-mcp' binary not found on PATH or in common install dirs." >&2
  echo "  Install it:  uv tool install \"zotero-mcp-server[semantic]\"" >&2
  echo "  Then verify: command -v zotero-mcp   (see https://github.com/54yyyu/zotero-mcp)" >&2
  exit 127
fi

exec "$BIN" serve
