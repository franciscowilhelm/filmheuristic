"""Classify a Letterboxd watchlist export as H (Hollywood) or A (Alternative)."""

import argparse
import csv
import random
import sys
from pathlib import Path

from .classify import classify
from .sources import Cache, Client

FIELDS = ["title", "year", "verdict", "reason", "confidence", "majors",
          "budget_usd_today", "budget_wikipedia_today", "budget_tmdb_today",
          "budget_straddles", "budget_raw", "budget_source", "countries",
          "non_us", "companies", "company_source", "wikipedia", "wikidata",
          "tmdb", "notes"]


def gather(client: Client, title: str, year: int | None) -> dict:
    """Merge the sources, preferring the most reliable one per field.

    For step 1 the ordering matters a lot. Wikipedia's infobox separates
    |studio= from |distributor=, so it alone answers "who made and paid for
    it". Wikidata's P272 and TMDB's production_companies both leak
    distributors -- TMDB credits Universal on *Red Rock West*, which would
    wrongly make it H -- so they are fallbacks, used only when Wikipedia has
    nothing to say.
    """
    meta = {"companies": [], "countries": [], "budget_raw": None,
            "wikipedia": None, "wikidata": None, "tmdb": None,
            "resolved": False, "company_source": None, "budget_source": None}

    wd = client.find_film(title, year)
    wp = {}
    if wd:
        meta["resolved"] = True
        meta["wikidata"] = f"https://www.wikidata.org/wiki/{wd['qid']}"
        meta["countries"] = list(wd["countries"])
        if wd.get("enwiki"):
            meta["wikipedia"] = "https://en.wikipedia.org/wiki/" + \
                wd["enwiki"].replace(" ", "_")
            wp = client.infobox(wd["enwiki"])

    # Wikidata's entity search misses films with common-word titles entirely.
    # Wikipedia's full-text search finds them, and the infobox it reaches is
    # the best source for both steps, so it is worth a second look.
    if not meta["wikipedia"]:
        page = client.find_wikipedia_page(title, year)
        if page:
            meta["resolved"] = True
            meta["wikipedia"] = ("https://en.wikipedia.org/wiki/"
                                 + page.replace(" ", "_"))
            wp = client.infobox(page)

    t = client.tmdb(title, year)
    if t:
        meta["resolved"] = True
        meta["tmdb"] = f"https://www.themoviedb.org/movie/{t['id']}"

    # Step 1 input: production companies, best source first.
    for companies, src in ((wp.get("companies"), "wikipedia:studio"),
                           (wd["companies"] if wd else None, "wikidata:P272"),
                           (t["companies"] if t else None, "tmdb")):
        if companies:
            meta["companies"] = list(companies)
            meta["company_source"] = src
            break

    # Step 2 input: keep both figures. They disagree often enough to matter
    # near the threshold (Grand Budapest: $25M on Wikipedia, $30M on TMDB),
    # so the rule runs on their average and we report the spread.
    meta["budgets"] = {
        "wikipedia": wp.get("budget") or None,
        "tmdb": f"${t['budget']}" if t and t.get("budget") else None,
    }

    meta["release_date"] = (t or {}).get("release_date")
    meta["status"] = (t or {}).get("status")
    if not meta["countries"]:
        meta["countries"] = wp.get("countries") or (t["countries"] if t else [])
    return meta


def read_watchlist(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("watchlist", type=Path)
    ap.add_argument("-n", "--sample", type=int, default=0,
                    help="classify N random entries instead of all")
    ap.add_argument("-r", "--recent", type=int, default=0,
                    help="classify the N most recently released entries")
    ap.add_argument("--seed", type=int, default=20260920)
    ap.add_argument("-o", "--out", type=Path, default=Path("out/verdicts.csv"))
    ap.add_argument("--cache", type=Path, default=Path("data/cache.json"))
    args = ap.parse_args(argv)

    rows = read_watchlist(args.watchlist)
    if args.recent:
        rows = sorted(rows, key=lambda r: int(r["Year"]) if r.get("Year", "").isdigit() else -1,
                      reverse=True)[:args.recent]
    if args.sample:
        random.seed(args.seed)
        rows = random.sample(rows, min(args.sample, len(rows)))

    client = Client(Cache(args.cache))
    if not client.tmdb_key:
        print("note: TMDB_API_KEY unset -- using Wikidata + Wikipedia only\n",
              file=sys.stderr)

    verdicts = []
    for i, row in enumerate(rows, 1):
        title = row["Name"]
        year = int(row["Year"]) if row.get("Year", "").isdigit() else None
        try:
            meta = gather(client, title, year)
            v = classify(title, year, meta)
        except Exception as e:      # keep the run going, but never fake an "A"
            from .classify import Verdict
            v = Verdict(title=title, year=year, verdict="?",
                        reason=f"lookup failed: {type(e).__name__}: {e}",
                        confidence="none")
        verdicts.append(v)
        print(f"{i:3}/{len(rows)}  {v.verdict}  {title} ({year})  -- {v.reason}",
              flush=True)   # progress must be visible when piped to a file

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for v in verdicts:
            w.writerow(v.as_row())

    h = sum(1 for v in verdicts if v.verdict == "H")
    a = sum(1 for v in verdicts if v.verdict == "A")
    unknown = sum(1 for v in verdicts if v.verdict == "?")
    low = sum(1 for v in verdicts if v.confidence == "low")
    print(f"\nH: {h}   A: {a}   unresolved: {unknown}   (low confidence: {low})")
    print(f"quota: {h} H films means {2 * h} A films owed")
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
