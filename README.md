# zotero-kg

A [Claude Code](https://docs.claude.com/en/docs/claude-code) skill that turns a research topic into
entries in your **local Zotero library** — and, optionally, into pages in a personal knowledge-graph wiki.

It exists to solve one specific pain: **writing to a local-only Zotero library**. In local mode (no Web API
key) Zotero's data API is read-only, so the usual "add by arXiv/DOI" tools fail. This skill uses Zotero's
**connector API** (the same endpoint the browser "Save to Zotero" button uses) to add papers without a key,
always at the paper's **latest arXiv version**.

## What it does

Three stages — runnable end-to-end or one at a time:

1. **Research** — web + arXiv API search to produce a *verified* list of papers (no hallucinated IDs).
2. **Reflect into Zotero** — add each paper (arXiv id / DOI) via the connector API, tagged, then refresh
   `zotero-mcp`'s semantic-search index.
3. **Ingest into a kg wiki** *(optional)* — export the tagged items to staging markdown and hand them to a
   knowledge-graph wiki. **This stage requires the separate `kg` skill suite** (see Prerequisites). Without
   it, the pipeline still produces the staging markdown for you to use however you like.

## Prerequisites

- **Zotero 7+ (tested on 9.0.4)** running, with the local API enabled:
  Settings → Advanced → "Allow other applications on this computer to communicate with Zotero" (port 23119).
- **[zotero-mcp](https://github.com/54yyyu/zotero-mcp)** installed (`zotero-mcp` CLI on PATH), registered in
  Claude Code in local mode. For semantic re-index, install its `[semantic]` extra.
- **Python 3.8+** and **curl** (both standard on macOS/Linux; Windows 10+ ships `curl.exe`). No pip installs —
  the scripts are pure stdlib + curl.
- *Optional, for Stage 3 only:* a `kg` skill suite providing `/kg-init`, `/kg-ingest`, `/kg-update`.

## Install

This is a Claude Code **plugin**. Add the marketplace and install:

```text
/plugin marketplace add gonos2k/zotero-kg
/plugin install zotero-kg@zotero-kg
```

The plugin bundles the skill **and** auto-registers the `zotero` MCP server (local mode). You still need the
`zotero-mcp` binary installed (see Prerequisites) and Zotero running with the local API enabled.

> The bundled MCP server is started via `scripts/start-zotero-mcp.sh`, which resolves `zotero-mcp` from your
> PATH or the common install dirs (`~/.local/bin`, uv/pipx venvs, Homebrew) — this is deliberate, because
> Claude Code may spawn MCP servers with a minimal PATH that omits `~/.local/bin`. If it still can't find the
> binary, the `zotero` server just won't appear in `/mcp` (the bundled CLI scripts work regardless). On
> Windows, ensure `zotero-mcp` is on PATH or run under WSL.

The bundled scripts can also be run directly from the installed plugin, e.g.:

```bash
python <plugin-dir>/skills/zotero-kg/scripts/zotero_add.py --arxiv 2505.22954 --tag my-topic --dry-run
```

## Usage

Just ask in natural language — e.g. *"research the main LLM agent memory papers, add them to my Zotero at
the latest version, and ingest them into my wiki."* The skill walks the three stages. See `SKILL.md` for the
full workflow and `references/zotero-write-gotchas.md` for the local-mode write details.

## Known limitations

- **Connector writes are add-only.** Editing/deleting an existing item (a true in-place version replace,
  batch-tagging, merging duplicates) needs a Zotero **Web API key** (hybrid mode) or a manual step in
  Zotero's UI. The skill surfaces this honestly and offers the API-key path.
- New items land in Zotero's **currently-selected collection** (the connector can't target one by key).
- Stage-3 ingest is **abstract-only** (no PDF fulltext); abstract-less items make thin wiki pages.
- Semantic search re-index (`zotero-mcp update-db`) is **manual** — run it after adding papers.
- The arXiv API is slow/rate-limited; the scripts cache and retry accordingly.

## Credits

Orchestrates **[54yyyu/zotero-mcp](https://github.com/54yyyu/zotero-mcp)** for the underlying Zotero MCP
server. Stage 3 targets a knowledge-graph wiki workflow.

## License

[MIT](./LICENSE).
