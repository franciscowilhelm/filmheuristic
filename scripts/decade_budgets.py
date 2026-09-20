"""Median production budget of major-studio films, by decade, from TMDB.

Why this exists: step 2's "~$35M in today's money" is a single number pinned to
the present. Whether it is the *right* number for a 1975 film depends on what a
studio film cost in 1975, and the published series that answer that (the MPAA's
average negative cost) are averages, stop in 2007, and are not machine-readable.
So the figure is derived here instead, from the same source the classifier
already uses.

Method: for each decade, ask TMDB for films produced by one of the major
studios' own production companies (the step 1 list, resolved to TMDB company
IDs), take the reported budgets, and report the median in nominal dollars of
that decade.

Two biases worth knowing before trusting the output, both stated in the JSON:
  - TMDB records a budget for only some films, and the ones it records skew
    large and well known. The median is a median of *reported* budgets.
  - TMDB's company credits mix production and distribution, so a studio pickup
    can land in the sample. Step 1 avoids this by reading Wikipedia's
    |studio= field; there is no equivalent here.

    uv run python scripts/decade_budgets.py -o web/decade_budgets.json
"""

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from filmheuristic.sources import _key_from_dotenv  # noqa: E402

API = "https://api.themoviedb.org/3"

# The majors' own production arms, named as step 1 names them. Specialty labels
# (Searchlight, Focus, Sony Pictures Classics) are left out for the same reason
# step 1 leaves them out: they are not what a major-studio budget looks like.
MAJOR_COMPANIES = [
    "Walt Disney Pictures", "Touchstone Pictures", "Hollywood Pictures",
    "Pixar", "Marvel Studios", "Lucasfilm Ltd.",
    "20th Century Fox", "20th Century Studios",
    "Universal Pictures", "Illumination", "DreamWorks Animation",
    "Warner Bros. Pictures", "New Line Cinema",
    "Paramount Pictures",
    "Columbia Pictures", "TriStar Pictures", "Sony Pictures",
    "Metro-Goldwyn-Mayer", "United Artists",
    "RKO Radio Pictures",
]

DECADES = [1930, 1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020]

# The 2020s median measures below the 2010s, which cannot be a real fall in
# what a studio film costs. The decade is incomplete, COVID-era slates sit in
# the middle of it, and TMDB has no budget yet for a good share of 2025-26
# titles (216 of 240 sampled, against 240 of 240 for the 2010s). Some genuine
# pullback is in there -- streaming took the mid-budget slate -- but not a
# third. Rather than let that artifact set the line for every recent film, the
# 2010s figure is carried forward and the two decades share one baseline. The
# measured value is kept alongside as median_measured, so nothing is lost.
CARRY_FORWARD = {2020: 2010}
PAGES_PER_DECADE = 12          # 20 results a page; TMDB caps discover at 500
MIN_BUDGET = 10_000            # placeholder values ($1, $178) are not budgets


class Tmdb:
    def __init__(self, key: str):
        self.key = key
        self.v4 = key.startswith("eyJ")

    def get(self, path: str, **params) -> dict:
        headers = {}
        if self.v4:
            headers["Authorization"] = f"Bearer {self.key}"
        else:
            params["api_key"] = self.key
        url = f"{API}{path}?{urllib.parse.urlencode(params)}"
        for attempt in range(6):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(float(e.headers.get("Retry-After") or 1) + attempt)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError):
                time.sleep(1 + attempt)
        raise RuntimeError(f"gave up on {path}")


def resolve_companies(api: Tmdb) -> dict[str, int]:
    """Company name -> TMDB id, taking only an exact (case-folded) name match.

    TMDB carries duplicate entries for the big studios ("Paramount pictures"
    alongside "Paramount Pictures"), and the duplicates hold a handful of films
    each. The canonical record is always the older one, so take the lowest id.
    """
    out = {}
    for name in MAJOR_COMPANIES:
        res = api.get("/search/company", query=name).get("results", [])
        hits = [c for c in res if c["name"].casefold() == name.casefold()]
        if hits:
            hit = min(hits, key=lambda c: c["id"])
            out[hit["name"]] = hit["id"]
        else:
            print(f"  ! no exact match for {name!r}", file=sys.stderr)
    return out


def decade_ids(api: Tmdb, company_ids: list[int], decade: int) -> list[int]:
    ids, pages = [], PAGES_PER_DECADE
    for page in range(1, pages + 1):
        r = api.get(
            "/discover/movie",
            with_companies="|".join(str(i) for i in company_ids),
            with_origin_country="US",
            **{"primary_release_date.gte": f"{decade}-01-01",
               "primary_release_date.lte": f"{decade + 9}-12-31"},
            sort_by="popularity.desc",
            include_adult="false",
            page=page,
        )
        ids += [m["id"] for m in r.get("results", [])]
        if page >= r.get("total_pages", 1):
            break
    return ids


def budgets(api: Tmdb, ids: list[int]) -> list[int]:
    def one(i):
        try:
            return api.get(f"/movie/{i}").get("budget") or 0
        except Exception:
            return 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        vals = list(pool.map(one, ids))
    return sorted(v for v in vals if v >= MIN_BUDGET)


def quantile(xs: list[int], q: float) -> float:
    if not xs:
        return 0.0
    pos = q * (len(xs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--out", default="web/decade_budgets.json")
    args = ap.parse_args()

    key = _key_from_dotenv()
    if not key:
        print("TMDB_API_KEY not found (put it in .env)", file=sys.stderr)
        return 1
    api = Tmdb(key)

    print("resolving company ids...", file=sys.stderr)
    companies = resolve_companies(api)
    ids = sorted(companies.values())

    rows = []
    for d in DECADES:
        film_ids = decade_ids(api, ids, d)
        vals = budgets(api, film_ids)
        rows.append({
            "decade": d,
            "sampled": len(film_ids),
            "with_budget": len(vals),
            "median": round(quantile(vals, 0.5)),
            "p25": round(quantile(vals, 0.25)),
            "p75": round(quantile(vals, 0.75)),
            "mean": round(statistics.fmean(vals)) if vals else 0,
        })
        print(f"{d}s: {len(vals):>4}/{len(film_ids):>4} budgets, "
              f"median ${rows[-1]['median']/1e6:.1f}M", file=sys.stderr)

    by = {r["decade"]: r for r in rows}
    carried = []
    for target, src in CARRY_FORWARD.items():
        if by.get(target) and by.get(src) and by[src]["median"]:
            by[target]["median_measured"] = by[target]["median"]
            by[target]["median"] = by[src]["median"]
            by[target]["median_source"] = f"carried forward from the {src}s"
            carried.append(
                f"The {target}s median is the {src}s figure carried forward. "
                f"It measured ${by[target]['median_measured']/1e6:.0f}M, below "
                f"the {src}s, which reflects an incomplete decade and missing "
                f"budgets for the newest films more than it reflects cost.")
            print(f"{target}s: median carried forward from {src}s "
                  f"(${by[target]['median']/1e6:.1f}M, measured "
                  f"${by[target]['median_measured']/1e6:.1f}M)", file=sys.stderr)

    doc = {
        "source": "TMDB",
        "generated": time.strftime("%Y-%m-%d"),
        "method": ("median of TMDB-reported production budgets for US films "
                   "credited to a major studio's own production company, "
                   "nominal dollars of the release decade"),
        "caveats": [
            "TMDB reports a budget for a minority of films and those it reports "
            "skew large and well known; this is a median of reported budgets.",
            "TMDB company credits mix production and distribution, so a studio "
            "pickup can enter the sample.",
            f"Sampled up to {PAGES_PER_DECADE * 20} films per decade by TMDB "
            "popularity, which skews towards films still watched today.",
            *carried,
        ],
        "companies": companies,
        "decades": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
