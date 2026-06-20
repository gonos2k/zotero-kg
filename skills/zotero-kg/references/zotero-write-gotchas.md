# Zotero local-mode write gotchas

Hard-won lessons from writing to a local Zotero library (Zotero 9, local mode, no web API key). Read
before changing stage-2 behavior — every one of these cost a failed attempt to discover.

## 1. The local DATA API is READ-ONLY

`GET http://localhost:23119/api/users/0/items` works, but `POST`/`PATCH`/`DELETE` return
**HTTP 400 "Endpoint does not support method"**. There is no keyless way to edit or delete existing
items through this API. `OPTIONS` returning 200 is misleading — it does not imply write support.

Consequence: the Zotero MCP tools `zotero_add_by_*` and `zotero_update_item` refuse in local-only mode
("fails in local-only mode"); they need a web API key (hybrid mode).

## 2. Writes go through the CONNECTOR API (add-only)

The connector server (the thing the browser "Save to Zotero" button talks to) IS read-write:

```
POST http://localhost:23119/connector/saveItems
Content-Type: application/json
X-Zotero-Connector-API-Version: 3
{ "sessionID": "<random hex>", "uri": "<source url>",
  "items": [ { "itemType": "preprint", "title": "...",
              "creators": [{"creatorType":"author","firstName":"..","lastName":".."}],
              "tags": [{"tag":"..."}], "abstractNote":"...", "url":"...", "DOI":"...", ... } ] }
```

→ HTTP 201, item lands in the running Zotero's currently-selected collection. **Add-only**: there is no
connector endpoint to edit or delete existing items.

Two distinct servers share port 23119: the **connector** (always on; `/connector/ping` → "Zotero is
running") and the **data API** (`/api/...`, gated by the Settings → Advanced checkbox). A live connector
does NOT mean the data API is enabled.

## 3. Enabling the data API

Settings → Advanced → "Allow other applications on this computer to communicate with Zotero". Until it's
ticked, `/api/...` returns **403 "Local API is not enabled"** (even though the port is listening). No app
restart needed after ticking. Symptom of forgetting it: SQLite-backed reads work but anything hitting
`/api/` (incl. `zotero-mcp update-db`) 403s.

## 4. "Replace with latest version" ≠ in-place update, without a key

- *New* arXiv adds: store `url=https://arxiv.org/abs/<id>vN` + `date` of the latest version. Done.
- *Existing* item: the connector can't modify it. Options:
  1. Add the latest as a new item; user merges old/new in Zotero's **Duplicate Items** view (keep latest
     as master). This is the only no-key automation.
  2. Get a Zotero **Web API key** (zotero.org/settings/keys) → hybrid mode → real in-place PATCH, plus the
     MCP write tools start working. Offer this when the user wants edits/deletes automated.

## 5. arXiv API is slow and rate-limits

`export.arxiv.org/api/query` takes ~12s/call and starts timing out under rapid repeated calls. urllib's
http→https redirect compounds it (read timeouts). Mitigations the scripts use:

- call `https://export.arxiv.org/...` **directly** (no http→https redirect) via **curl** with `--retry`;
- **space** calls out (~3s) and fetch per-ID rather than hammering;
- **cache** every fetch to `/tmp/zotero_add_cache.json` so dry-runs and reruns never refetch.

Never trust LLM-recalled arXiv IDs/versions — always confirm against the API; the `<id>` field returns the
current latest `vN`.

**Invalid IDs don't error — they "succeed" with junk.** A bad/nonexistent ID returns a feed whose single
`<entry>` has `<title>Error</title>` and *echoes the requested id back* into `<id>` (e.g.
`http://arxiv.org/abs/garbage123`). So an id-substring check passes for junk — detect the failure by
`title == "Error"`, not by matching the id. Also normalize user input first: strip a leading `arXiv:` and any
trailing `vN`, or you build URLs like `.../abs/2505.22954v1v3`.

## 6. Semantic search is a separate, manual index

`zotero-mcp update-db` (incremental) rebuilds the embedding DB; it is **not** automatic. Run it after every
add. Needs the `[semantic]` extra (`zotero-mcp db-status` reports if missing). It reads via the `/api/`
data API, so the data-API checkbox (gotcha #3) must be on or it 403s with 0 items processed.

## 7. Pipefail / exit-code traps when scripting this

`cmd | tail` reports tail's exit code, masking cmd's failure — and a background job's "exit 0" can be a lie.
Inspect actual output, not just status, when an arXiv fetch or a POST might have failed.

## 8. userID alias

All local reads can use `http://localhost:23119/api/users/0/...` — `0` is the local-user library alias, so
you never need the real numeric library id. The real id still appears in each item's `library.id` if needed.
