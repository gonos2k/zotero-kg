#!/usr/bin/env python3
"""Add arXiv/DOI papers to a LOCAL Zotero library via the connector API (no web API key needed).

Why the connector API: in local-only Zotero (ZOTERO_LOCAL=true, no web API key) the data API
(POST /api/users/<id>/items) is READ-ONLY and returns HTTP 400 "Endpoint does not support method".
The connector endpoint that the browser "Save to Zotero" button uses IS read-write and saves into
the running Zotero. Caveat: it can only ADD items, never edit/delete existing ones.

arXiv metadata comes from export.arxiv.org over HTTPS via curl (slow, ~12s/call, and it rate-limits
on rapid repeats — urllib's http->https redirect also tends to time out). Results are cached to
/tmp/zotero_add_cache.json so reruns and dry-runs don't refetch.

Usage:
  python zotero_add.py --arxiv 2505.22954 2509.19349 [--doi 10.1038/...] [--tag code-evolution] [--dry-run]
  python zotero_add.py --input papers.json        # [{"arxiv":"..."}|{"doi":"..."}]
"""
import argparse, json, os, re, html, subprocess, time
import urllib.request, urllib.error, urllib.parse
import xml.etree.ElementTree as ET  # input is the trusted arXiv/CrossRef API; swap for defusedxml if hardening

BASE = "http://localhost:23119"
NS = {"a": "http://www.w3.org/2005/Atom"}
CACHE = "/tmp/zotero_add_cache.json"


def curl(url):
    r = subprocess.run(
        ["curl", "-s", "-m", "35", "--retry", "3", "--retry-delay", "4", "-A", "zotero-kg/1.0", "--", url],
        capture_output=True, timeout=180)
    return r.stdout


def split_name(full):
    full = " ".join(full.split())
    if "," in full:
        last, first = full.split(",", 1)
        return first.strip(), last.strip()
    parts = full.split(" ")
    return ("", parts[0]) if len(parts) == 1 else (" ".join(parts[:-1]), parts[-1])


def creators(names):
    return [{"creatorType": "author", "firstName": split_name(n)[0], "lastName": split_name(n)[1]}
            for n in names if n and n.strip()]


def load_cache():
    return json.load(open(CACHE)) if os.path.exists(CACHE) else {}


def save_cache(c):
    json.dump(c, open(CACHE, "w"))


def fetch_arxiv(aid, cache, tag):
    aid = re.sub(r"^arxiv:", "", aid.strip(), flags=re.I)
    aid = re.sub(r"v[0-9]+$", "", aid)            # normalize: drop any version the user pasted (e.g. 2505.22954v1)
    key = f"arxiv:{aid}"
    if key in cache:
        return cache[key]
    e = ET.fromstring(curl(f"https://export.arxiv.org/api/query?id_list={aid}&max_results=1")).find("a:entry", NS)
    if e is None:
        raise RuntimeError(f"no entry for {aid} (invalid ID, or arXiv timeout/rate-limit)")
    idu = e.find("a:id", NS).text.strip()
    title = " ".join((e.find("a:title", NS).text or "").split())
    # arXiv answers a bad ID with an entry titled exactly "Error" that echoes the requested id in <id>,
    # so an id-substring check passes for junk — the reliable signal is the title.
    if title == "Error":
        raise RuntimeError(f"arXiv has no paper '{aid}' (error response)")
    m = re.search(r"(v[0-9]+)$", idu)
    ver = m.group(1) if m else ""
    item = {"itemType": "preprint", "title": title,
            "creators": creators([a.find("a:name", NS).text for a in e.findall("a:author", NS)]),
            "abstractNote": " ".join((e.find("a:summary", NS).text or "").split()), "repository": "arXiv",
            "archiveID": f"arXiv:{aid}", "date": (e.find("a:updated", NS).text or "")[:10],
            "url": f"https://arxiv.org/abs/{aid}{ver}", "DOI": f"10.48550/arXiv.{aid}",
            "libraryCatalog": "arXiv.org", "extra": f"arXiv:{aid}{ver}"}
    if tag:
        item["tags"] = [{"tag": tag}]
    cache[key] = item
    save_cache(cache)
    return item


def fetch_doi(doi, cache, tag):
    key = f"doi:{doi}"
    if key in cache:
        return cache[key]
    msg = json.loads(curl(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"))["message"]
    names = [f"{a.get('given','')} {a.get('family','')}".strip() for a in msg.get("author", [])]
    dp = (msg.get("published") or msg.get("published-print") or msg.get("published-online") or {})
    parts = (dp.get("date-parts") or [[]])[0]
    abstract = re.sub("<[^>]+>", "", html.unescape(msg.get("abstract", ""))).strip()
    item = {"itemType": "journalArticle", "title": (msg.get("title") or ["?"])[0], "creators": creators(names),
            "abstractNote": abstract, "publicationTitle": (msg.get("container-title") or [""])[0],
            "volume": msg.get("volume", ""), "issue": msg.get("issue", ""), "pages": msg.get("page", ""),
            "date": "-".join(str(p) for p in parts), "DOI": doi, "url": f"https://doi.org/{doi}",
            "libraryCatalog": "CrossRef"}
    if tag:
        item["tags"] = [{"tag": tag}]
    cache[key] = item
    save_cache(cache)
    return item


def save_to_zotero(item):
    payload = {"sessionID": os.urandom(8).hex(), "uri": item.get("url", "https://example.org"), "items": [item]}
    req = urllib.request.Request(BASE + "/connector/saveItems", data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-Zotero-Connector-API-Version": "3",
                 "User-Agent": "zotero-kg/1.0"})
    try:
        return urllib.request.urlopen(req, timeout=45).status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except urllib.error.URLError as e:
        return 0, f"connection failed ({e.reason}) — is Zotero running with the connector up?"


def existing_idents():
    """archiveIDs (arXiv:..) + DOIs already in the library, lowercased, for dedup. Best-effort, paginated.
    No itemType filter: the API's `-attachment || note` parses as OR and filters nothing, and anyway
    notes/attachments carry no archiveID/DOI so they contribute nothing here."""
    seen, start = set(), 0
    try:
        for _ in range(100):  # hard page cap (~10k items) so a misbehaving API can't loop forever
            url = BASE + f"/api/users/0/items?format=json&limit=100&start={start}"
            batch = json.loads(urllib.request.urlopen(url, timeout=20).read())
            if not batch:
                break
            for it in batch:
                d = it.get("data", {})
                if d.get("archiveID"):
                    seen.add(d["archiveID"].lower())
                if d.get("DOI"):
                    seen.add(d["DOI"].lower())
            if len(batch) < 100:
                break
            start += 100
    except Exception as e:
        print(f"(dedup check skipped — could not read library: {e})")
    return seen


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arxiv", nargs="*", default=[], help="arXiv IDs (without version)")
    ap.add_argument("--doi", nargs="*", default=[], help="DOIs")
    ap.add_argument("--tag", default=None, help="topic tag attached to every added item")
    ap.add_argument("--input", default=None, help="JSON file: [{'arxiv':..}|{'doi':..}]")
    ap.add_argument("--dry-run", action="store_true", help="build + print, do not save")
    a = ap.parse_args()

    arxiv, doi = list(a.arxiv), list(a.doi)
    if a.input:
        for rec in json.load(open(a.input)):
            if rec.get("arxiv"):
                arxiv.append(rec["arxiv"])
            if rec.get("doi"):
                doi.append(rec["doi"])

    cache, built = load_cache(), []
    for aid in arxiv:
        try:
            built.append(fetch_arxiv(aid, cache, a.tag)); print(f"fetched arxiv {aid}")
        except Exception as e:
            print(f"!! arxiv {aid}: {e}")
        time.sleep(3)
    for d in doi:
        try:
            built.append(fetch_doi(d, cache, a.tag)); print(f"fetched doi {d}")
        except Exception as e:
            print(f"!! doi {d}: {e}")

    print(f"\n{len(built)} items built. tag={a.tag}")
    for it in built:
        print(f"  - [{it['itemType']:14s}] {it['title'][:66]}  {it.get('url','')}")
    if a.dry_run:
        print("\n[dry-run] nothing saved. Re-run without --dry-run to write.")
        return

    seen = existing_idents()
    print()
    ok = skipped = 0
    for it in built:
        # an arXiv item carries BOTH archiveID and DOI; check either against the library so a
        # translator-added item that only has one of them still dedups (rerun-safe).
        idents = [v.lower() for v in (it.get("archiveID", ""), it.get("DOI", "")) if v]
        if idents and any(i in seen for i in idents):
            print(f"  [SKIP dup ] {it['title'][:58]}")
            skipped += 1
            continue
        code, err = save_to_zotero(it)
        good = 200 <= code < 300                           # connector returns 201 (Zotero 9); accept any 2xx
        print(f"  [{('OK ' + str(code)) if good else ('ERR ' + str(code))}] {it['title'][:58]} {err}")
        if good:
            ok += 1
            seen.update(idents)                            # also dedup within this same batch
        time.sleep(1.5)
    print(f"\nSaved {ok}/{len(built)} (skipped {skipped} dupes). Next: ZOTERO_LOCAL=true zotero-mcp update-db")


if __name__ == "__main__":
    main()
