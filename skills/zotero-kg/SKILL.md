---
name: zotero-kg
description: >-
  Pipeline for getting research INTO a local Zotero library and from there into the kg wiki. Its
  scope is exactly three kinds of write: (1) ADDING papers to Zotero — from a research topic, or by
  arXiv id / DOI — including when the normal Zotero MCP add fails in local-only mode (the connector
  workaround is this skill's job); (2) UPDATING a Zotero arXiv item to its newer version (add-the-newer then merge; a true in-place edit needs a Zotero API key); and
  (3) INGESTING Zotero items / collections / tags into the kg knowledge-graph wiki. A run always
  ends with new or updated library items, or new wiki pages. Trigger for requests like "이 논문들
  Zotero에 추가/반영해줘", "조사해서 Zotero에 넣고 위키에 정리", "arxiv 항목 최신 버전으로 교체",
  or "Zotero 태그/컬렉션을 위키에 ingest". Do NOT trigger when none of those three writes happens:
  searching, reading, or merely checking a paper's metadata or whether it is already the latest
  version (Zotero MCP read tools); other library edits such as batch-tagging or merging duplicates
  (separate Zotero MCP write tools, not this pipeline); questions about existing wiki/graph content,
  even for papers previously ingested here (kg-query); ingesting a file PATH into the wiki — any path on
  disk, even a PDF under ~/Zotero/storage (plain /kg-ingest; this skill ingests Zotero library ITEMS by
  tag/collection/key, NOT file paths); summarizing or formatting a paper, e.g. as BibTeX, without saving it;
  or web research the user says they will not save yet. Pure zotero-mcp install/setup
  questions are out of scope. But update-db / semantic re-indexing IS part of this pipeline, so DO
  trigger when the user is stuck getting a paper INTO Zotero (local-mode add failing) OR wants to
  re-index / refresh semantic search right after adding papers.
---

# zotero-kg — Research → Zotero → Knowledge Graph

Three stages, runnable end-to-end or one at a time:

1. **Research** a topic → a verified list of papers (arXiv IDs / DOIs).
2. **Reflect into Zotero** → add each paper at its **latest arXiv version**, tagged, then refresh semantic search.
3. **Ingest into the kg wiki** → export the added items and hand them to `/kg-ingest`, then `/kg-update`.

The hard-won value of this skill is in stage 2: writing to a local Zotero library is full of non-obvious
traps (read-only data API, connector-only writes, arXiv rate limits, no in-place edits without an API
key). Those are encoded in `references/zotero-write-gotchas.md` and in the bundled scripts — read them
before improvising.

## When to use / when not

**Use when** the user wants to *grow their reference library or knowledge base from research* — any flavor
of "find papers about X and put them in Zotero (and maybe my wiki)", or "update my arXiv items to latest".

**Don't use for** pure reads — "search my Zotero for X", "what's the abstract of Y" — those are direct
`zotero_*` MCP tool calls, no pipeline needed. Pure wiki work with no Zotero involved → use the `kg` skills
directly.

## Preconditions

- **zotero-mcp installed** (`zotero-mcp` CLI on PATH) and registered — see the README / upstream
  [54yyyu/zotero-mcp](https://github.com/54yyyu/zotero-mcp) for setup.
- **Zotero app running** with **local API enabled** (Settings → Advanced → "Allow other applications on
  this computer to communicate with Zotero", port 23119). Confirm with:
  `curl -s -m5 "http://localhost:23119/api/users/0/items?limit=1&format=json"` → JSON, not 403.
  - 403 "Local API is not enabled" → ask the user to tick that checkbox (no app restart needed).
  - The connector server (`/connector/ping` → "Zotero is running") is always on; that alone is **not**
    enough — the `/api/` read endpoints need the checkbox.
- For the **wiki ingest step**: a `wiki/` must exist (kg initialized). If the request is end-to-end
  (research→Zotero→위키), verify `wiki/` **up front, before writing to Zotero**, and offer `/kg-init` first —
  so the user isn't told only after the library is already written. For an add-only request this check can
  wait until Stage 3. If `wiki/` is missing, stop the ingest stage and suggest `/kg-init`.
- All local reads use the **userID alias `0`** (= the local user library); you never need the numeric id.

## Stage 1 — Research

Goal: a *verified* list of papers, not a guess. LLM memory hallucinates arXiv IDs, so confirm every ID.

1. Run a few **WebSearch** queries to map the landscape (landmark works, open-source variants, surveys).
2. For each candidate, confirm the **exact arXiv ID and latest version** via the arXiv API — the `<id>`
   field comes back as `.../abs/<id>vN`, where `vN` is the current latest. Use the same curl path the
   scripts use (HTTPS direct, see gotchas) to avoid the urllib redirect timeout.
3. De-duplicate against what's already in Zotero so you don't re-add. Quick check:
   `curl -s "http://localhost:23119/api/users/0/items?q=<title-fragment>&format=json&limit=5"`.
4. Present the curated list (framework, arXiv id+version / DOI, one-line why) and let the user confirm
   scope before writing anything to their library — it's their personal data.

## Stage 2 — Reflect into Zotero

Add the confirmed papers with `scripts/zotero_add.py`. It fetches latest-version metadata (arXiv via curl
+ cache; DOI via CrossRef), builds proper Zotero items, and saves them through the **connector API**.

```bash
python scripts/zotero_add.py \
  --arxiv 2505.22954 2509.19349 2401.02051 \
  --doi 10.1038/s41586-023-06924-6 \
  --tag <topic-tag> --dry-run        # inspect first
python scripts/zotero_add.py --arxiv ... --doi ... --tag <topic-tag>   # then save
```

- A topic `--tag` (e.g. `code-evolution`) makes the new set findable as one group in Zotero and is the
  handle stage 3 uses to export them. Always set one.
- `--dry-run` builds + prints items without writing. Use it once to sanity-check titles/authors/versions.
- **Latest-version semantics**: arXiv items are stored with `url=https://arxiv.org/abs/<id>vN`, `date` =
  the latest version's date, `archiveID=arXiv:<id>`. That satisfies "최신 버전으로 교체" for *new* adds.
- **Refreshing an item that already exists** (true in-place "교체") is NOT possible via the connector —
  it only adds. Two honest options, surface both:
  - *No API key*: add the latest version as a new item with `--allow-duplicate` (every arXiv version shares
    `archiveID=arXiv:<id>`, so without that flag dedup skips it as a dup and nothing is added), then the user
    merges the old/new pair in Zotero's **Duplicate Items** view (keep the latest as master). A real write
    already re-fetches the latest version, so `--allow-duplicate` alone is enough. The add is all you can automate.
  - *With a Zotero Web API key (hybrid mode)*: real in-place PATCH becomes possible and the Zotero MCP
    write tools start working too. Offer this if the user wants edits/deletes automated going forward.

Then refresh semantic search so the new papers are retrievable by meaning:

```bash
ZOTERO_LOCAL=true zotero-mcp update-db    # incremental; only new/changed items
```

This is **manual** (auto-update is off by default). Re-run it after any add. Needs the `[semantic]` extra
installed; `zotero-mcp db-status` tells you if it's missing.

`update-db` prints `Added: N / Processed: N` — use that N as the re-index count in the output contract.
The connector writes **asynchronously**, so run `update-db` only after `zotero_add.py` reports its saves
done; if the indexed count looks short, wait a moment and re-run (it's incremental, so re-running is cheap).

> Note: if the live Zotero MCP server in the current session predates a `zotero-mcp` reinstall, its tools
> may be stale — but these CLI scripts use the fresh install directly, so the pipeline still works without
> restarting Claude Code. Restart is only needed to use the `zotero_*` MCP tools in-session.

## Stage 3 — Ingest into the kg wiki (optional)

> **Requires the `kg` skill suite** (`/kg-init`, `/kg-ingest`, `/kg-update`). If it isn't installed, the
> pipeline still runs Stages 1–2 and produces the staging markdown below — you can ingest that into any
> knowledge base you like; only the kg-specific steps are unavailable.

Export the freshly-tagged items to staging markdown, then ingest:

```bash
python scripts/zotero_export_kg.py --tag <topic-tag> --out /tmp/zotero-kg-staging
```

Each item becomes a markdown file (title, authors, date, DOI/URL, **Zotero key**, abstract). Ingest is
**abstract-only** — it never reads PDF fulltext, so a PDF-less item is fine *if* it has an abstract, but an
item with no abstract exports as a near-empty `(no abstract)` file that yields a thin wiki page; flag those
to the user. Export caps at `--limit` (default **500**; raise it for bigger tags). For a large set (many
dozens+), ingest in **chunks** rather than one giant `/kg-ingest` — kg-ingest's batch mode handles per-file
gates and chunking keeps the run recoverable if it stalls mid-way. Then run the kg ingest skill on the
folder — it builds `wiki/sources|concepts|entities` pages with `[[wikilinks]]` and provenance, preserving
contradictions as Tension callouts:

```
/kg-ingest /tmp/zotero-kg-staging
```

Follow kg-ingest's own confirmation gates (name collisions, class judgment, contradictions). When it
finishes, refresh the graph:

```
/kg-update
```

Provenance tip: the Zotero key in each staging file lets a wiki source page point back to the exact library
item, closing the loop between reference manager and knowledge graph.

## Bundled scripts

| Script | Purpose |
|---|---|
| `scripts/zotero_add.py` | Fetch latest-version metadata (arXiv/DOI) → add to Zotero via connector API. `--dry-run`, `--tag`, `--input papers.json`, `--allow-duplicate` (update→merge), `--force-without-dedup`. Caches dry-run fetches; real writes re-fetch the latest version. |
| `scripts/zotero_export_kg.py` | Export Zotero items (by `--tag` / `--collection`, `--limit` default 500) to staging markdown for `/kg-ingest`. Only ever deletes/overwrites its own marker-stamped files; `--force` to overwrite others. Warns if run with no selector (would export the whole library). |

Both default to `http://localhost:23119` and userID `0`. They're plain stdlib + curl — no pip installs.

## Gotchas

Read `references/zotero-write-gotchas.md` before changing stage-2 behavior. The short version:
local data API is read-only (POST→400); connector API is the only keyless write path and adds-only;
arXiv's API is slow and rate-limits rapid calls (cache + HTTPS-direct curl + spacing); semantic search is a
separate manual index.

**Known limitations (local mode, no API key):**
- New items land in Zotero's **currently-selected collection** — the connector cannot target a collection by
  key. If placement matters, have the user select the destination collection in Zotero first (or use a Web
  API key for precise filing). `--collection` on the *export* side reads a collection but the *add* side can't.
- `zotero_add.py` dedup is best-effort: it reads the library and skips items whose `arXiv:<id>` or DOI already
  exist (covers both connector- and Zotero-translator-added items). If the library can't be fully read it
  **aborts before any write** (so it never adds blind duplicates); pass `--force-without-dedup` to add anyway.
  To intentionally add a newer arXiv version of an item that already exists (the update→merge workflow), pass
  `--allow-duplicate`.
- Invalid arXiv IDs are rejected (arXiv answers with an entry titled "Error"); the script detects that and
  skips, so a bad ID never becomes a junk library item.

## Output contract

End an end-to-end run with:

```text
Research: <N papers confirmed> (scope approved: yes/no)
Zotero:   added <A> (tag=<tag>), skipped <S> dupes, failed <F>
          version-replace: <none | new-item+merge pending: keys | in-place via API key>
Semantic: re-indexed (<count> docs) | skipped (reason)
KG:       ingested via /kg-ingest → sources: [[...]], concepts: [[...]] ; /kg-update <run|suggested>
Manual follow-ups:
- <e.g., merge CodeEvolve v1/v5 in Duplicate Items; tag existing item; /kg-init needed>
```
