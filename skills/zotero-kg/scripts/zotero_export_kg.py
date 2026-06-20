#!/usr/bin/env python3
"""Export Zotero items (by tag / collection) to staging markdown for /kg-ingest.

Reads via the local DATA API, which is read-only — perfectly fine here. Uses userID alias 0, which
the Zotero local API treats as "the local user library", so no numeric library id is needed.

Each item becomes one markdown file with metadata + abstract and, crucially, the Zotero item KEY, so
the wiki source page /kg-ingest creates can point back to the exact library entry (closing the loop
between reference manager and knowledge graph).

Usage:
  python zotero_export_kg.py --tag code-evolution --out /tmp/zotero-kg-staging
  python zotero_export_kg.py --collection 9SU943GB --out /tmp/zotero-kg-staging
Then:
  /kg-ingest /tmp/zotero-kg-staging
"""
import argparse, json, os, re, urllib.request, urllib.parse

BASE = "http://localhost:23119/api/users/0"


def slug(s):
    s = re.sub(r"[^a-zA-Z0-9가-힣]+", "-", (s or "").strip().lower()).strip("-")
    return s[:60] or "item"


def fetch_all(path, params, cap):
    """Paginate through all matching items (100/page) up to `cap`. Returns (items, truncated?)."""
    items, start = [], 0
    while True:
        p = dict(params, limit=100, start=start)
        batch = json.loads(urllib.request.urlopen(f"{BASE}/{path}?" + urllib.parse.urlencode(p), timeout=25).read())
        items += batch
        if len(batch) < 100:
            return items, False
        start += 100
        if len(items) >= cap:
            return items[:cap], True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", default=None, help="export items carrying this tag")
    ap.add_argument("--collection", default=None, help="export items in this collection key")
    ap.add_argument("--out", default="/tmp/zotero-kg-staging", help="staging dir for /kg-ingest")
    ap.add_argument("--limit", type=int, default=500, help="safety cap on items exported")
    a = ap.parse_args()

    if not a.tag and not a.collection:
        print(f"WARNING: no --tag or --collection given — exporting the ENTIRE library (up to --limit "
              f"{a.limit}) into {a.out}. Pass --tag or --collection to scope this to a paper set.")

    # No API itemType filter: Zotero parses `-attachment || note` as OR and filters nothing, so
    # attachments/notes are dropped python-side in the loop below instead.
    params = {"format": "json"}
    if a.tag:
        params["tag"] = a.tag
    path = f"collections/{a.collection}/items" if a.collection else "items"
    data, truncated = fetch_all(path, params, a.limit)
    if truncated:
        print(f"WARNING: hit --limit {a.limit}; more items may exist — raise --limit to export all.")

    os.makedirs(a.out, exist_ok=True)
    written, used = [], set()
    for it in data:
        d = it["data"]
        if d.get("itemType") in ("attachment", "note"):
            continue
        authors = ", ".join(f"{c.get('firstName','')} {c.get('lastName','')}".strip()
                            for c in d.get("creators", []) if c.get("creatorType") == "author")
        base = slug(d.get("title", "item"))
        name = base if base not in used else f"{base}-{d.get('key', 'x')}"  # disambiguate collisions w/ unique key
        used.add(name)
        fn = os.path.join(a.out, f"{name}.md")
        lines = [f"# {d.get('title','')}", "",
                 f"- Authors: {authors}",
                 f"- Date: {d.get('date','')}",
                 f"- Type: {d.get('itemType','')}"]
        if d.get("DOI"):
            lines.append(f"- DOI: {d['DOI']}")
        if d.get("url"):
            lines.append(f"- URL: {d['url']}")
        lines += [f"- Zotero key: {d.get('key','')}", "",
                  "## Abstract", "", (d.get("abstractNote") or "(no abstract)"), ""]
        with open(fn, "w") as f:
            f.write("\n".join(lines))
        written.append(fn)

    print(f"Wrote {len(written)} files to {a.out}")
    for w in written:
        print("  " + w)
    print(f"\nNext: /kg-ingest {a.out}")


if __name__ == "__main__":
    main()
