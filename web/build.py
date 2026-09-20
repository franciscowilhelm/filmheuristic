"""Bake the classifier's output into a single-file threshold explorer.

The page has to run from a file:// URL (double-click, no server), so the CSVs
and the decade budget table are embedded rather than fetched. The inflation
factors are read out of filmheuristic.budget itself rather than retyped, so the
page cannot silently drift from the classifier.

    uv run python web/build.py
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from filmheuristic.budget import THRESHOLD_USD_TODAY, inflation_factor  # noqa: E402

DATASETS = [
    ("recent50.csv", "50 most recent"),
    ("verdicts.csv", "Sample across decades"),
    ("edge.csv", "Edge cases"),
]
YEARS = range(1900, 2036)

# Columns the page actually reads. Everything else in the CSV is provenance for
# checking a verdict by hand, which the page does with links instead.
KEEP_NUM = ("budget_usd_today", "budget_wikipedia_today", "budget_tmdb_today")
KEEP_STR = ("title", "verdict", "reason", "confidence", "majors", "countries",
            "budget_source", "wikipedia", "tmdb")


def row_of(r: dict) -> dict:
    out = {k: (r.get(k) or "") for k in KEEP_STR}
    out["year"] = int(r["year"]) if (r.get("year") or "").isdigit() else None
    for k in KEEP_NUM:
        v = (r.get(k) or "").strip()
        out[k] = float(v) if v else None
    out["non_us"] = {"True": True, "False": False}.get(r.get("non_us") or "")
    out["straddles"] = (r.get("budget_straddles") or "") == "True"
    return out


def inflation_runs() -> list[list]:
    """[[first_year, factor], ...] -- one entry per step, not per year."""
    runs = []
    for y in YEARS:
        f = inflation_factor(y)
        if not runs or runs[-1][1] != f:
            runs.append([y, f])
    return runs


def main() -> int:
    datasets = []
    for name, label in DATASETS:
        path = ROOT / "out" / name
        if not path.exists():
            print(f"skipping missing {path}", file=sys.stderr)
            continue
        with path.open(newline="", encoding="utf-8") as fh:
            rows = [row_of(r) for r in csv.DictReader(fh) if r.get("title")]
        datasets.append({"id": path.stem, "label": label,
                         "file": f"out/{name}", "rows": rows})

    decades_path = Path(__file__).parent / "decade_budgets.json"
    decades = json.loads(decades_path.read_text()) if decades_path.exists() else None
    if decades is None:
        print("no decade_budgets.json -- page will offer the flat slider only",
              file=sys.stderr)

    payload = {
        "threshold_default": THRESHOLD_USD_TODAY,
        "inflation": inflation_runs(),
        "datasets": datasets,
        "decades": decades,
    }
    template = (Path(__file__).parent / "template.html").read_text()
    out = Path(__file__).parent / "index.html"
    out.write_text(template.replace(
        "__DATA__", json.dumps(payload, separators=(",", ":"))))
    n = sum(len(d["rows"]) for d in datasets)
    print(f"wrote {out} -- {len(datasets)} datasets, {n} films")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
