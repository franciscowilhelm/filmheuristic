"""The rule itself: major studio? -> H. Else budget > ~$35M today? -> H. Else A."""

import datetime as _dt
from dataclasses import dataclass, field, asdict

from . import budget as bud
from . import studios


@dataclass
class Verdict:
    title: str
    year: int | None
    verdict: str                  # "H" or "A"
    reason: str
    confidence: str               # high / medium / low
    majors: list[str] = field(default_factory=list)
    distributor_majors: list[str] = field(default_factory=list)
    companies: list[str] = field(default_factory=list)
    distributors: list[str] = field(default_factory=list)
    budget_raw: str | None = None
    budget_usd_today: float | None = None
    countries: list[str] = field(default_factory=list)
    non_us: bool | None = None
    budget_wikipedia_today: float | None = None
    budget_tmdb_today: float | None = None
    budget_straddles: bool = False
    budget_source: str | None = None
    company_source: str | None = None
    wikipedia: str | None = None
    wikidata: str | None = None
    tmdb: str | None = None
    notes: str = ""

    def as_row(self):
        d = asdict(self)
        for k in ("majors", "distributor_majors", "companies",
                  "distributors", "countries"):
            d[k] = "; ".join(d[k])
        if d["budget_usd_today"]:
            d["budget_usd_today"] = round(d["budget_usd_today"])
        return d


def _unreleased(meta, year) -> bool:
    """True when the film has not come out yet, so a missing budget is
    expected rather than evidence of a small production."""
    today = _dt.date.today()
    rd = meta.get("release_date")
    if rd:
        try:
            return _dt.date.fromisoformat(rd) > today
        except ValueError:
            pass
    if (meta.get("status") or "") in {"Planned", "In Production",
                                      "Post Production", "Rumored"}:
        return True
    return bool(year) and year >= today.year


def budget_figures(v: "Verdict", meta, year):
    """Fill v's budget fields from the sources. Returns (today_usd, note).

    Run for every film, including ones step 1 has already decided, so the
    figures are on the row whatever settled it. A verdict that turns on the
    pre-1980 distributor reading has to be recomputable without it, and that
    means falling back to the budget test -- which needs the budget present.
    """
    budgets = meta.get("budgets") or {}
    if not budgets and meta.get("budget_raw"):
        budgets = {"wikipedia": meta["budget_raw"]}
    per_source, notes, raws = {}, [], []
    for src in ("wikipedia", "tmdb"):
        raw = budgets.get(src)
        if not raw:
            continue
        nominal, note = bud.parse_amount(raw, year)
        val = bud.today_usd(nominal, year)
        if val is not None:
            per_source[src] = val
            raws.append(f"{src}: {raw.strip()[:60]}")
        else:
            notes.append(f"{src}: {note}")
    v.budget_wikipedia_today = per_source.get("wikipedia")
    v.budget_tmdb_today = per_source.get("tmdb")
    v.budget_raw = " | ".join(raws) or None
    v.budget_source = "+".join(per_source) or None
    today = sum(per_source.values()) / len(per_source) if per_source else None
    v.budget_usd_today = today
    if len(per_source) == 2:
        lo, hi = min(per_source.values()), max(per_source.values())
        v.budget_straddles = lo <= bud.THRESHOLD_USD_TODAY <= hi
    return today, ("; ".join(notes) or "no budget text")


def classify(title, year, meta, era_distributor: bool = True) -> Verdict:
    """meta: merged dict from sources -- companies, budget, countries, links.

    era_distributor turns on the studio-system reading of step 1: for a US
    film made before 1980, a major credited as distributor is taken to have
    financed it. See studios.DISTRIBUTOR_ERA_BEFORE for why.
    """
    companies = meta.get("companies", [])
    countries = meta.get("countries", [])
    if not meta.get("resolved"):
        return Verdict(title=title, year=year, verdict="?",
                       reason="no matching film found in any source",
                       confidence="none")
    v = Verdict(
        title=title, year=year, verdict="A", reason="", confidence="low",
        companies=companies, countries=countries,
        distributors=list(meta.get("distributors") or []),
        budget_source=meta.get("budget_source"),
        company_source=meta.get("company_source"),
        wikipedia=meta.get("wikipedia"), wikidata=meta.get("wikidata"),
        tmdb=meta.get("tmdb"),
    )
    v.non_us = bool(countries) and not any(
        c.strip().lower() in {"united states", "usa", "us", "united states of america"}
        for c in countries) or None if countries else None
    if countries:
        v.non_us = not any(c.strip().lower() in
                           {"united states", "usa", "us", "united states of america"}
                           for c in countries)

    # Parsed before step 1 so the figures are on every row, whatever decided it.
    today, note = budget_figures(v, meta, year)

    # Step 1
    hits = studios.scan(companies, year)
    if hits:
        v.majors = sorted({g for g, _ in hits})
        v.verdict = "H"
        v.reason = "major studio: " + ", ".join(f"{t} ({g})" for g, t in hits)
        v.confidence = "high"
        return v
    # Step 1, studio-system reading. The majors financed far more than they
    # produced between the Paramount decrees and about 1980, and Wikipedia
    # files that under |distributor=. This is recorded either way, so the
    # verdict can be recomputed without it.
    dhits = studios.era_distributor_hits(v.distributors, year, v.non_us)
    v.distributor_majors = sorted({g for g, _ in dhits})
    if dhits and era_distributor:
        v.verdict = "H"
        v.reason = ("US film before "
                    f"{studios.DISTRIBUTOR_ERA_BEFORE}, major as distributor "
                    "and so its financier: "
                    + ", ".join(f"{t} ({g})" for g, t in dhits))
        # An inference from the era, not a production credit: never "high".
        v.confidence = "medium"
        return v

    if not companies:
        v.notes = "no production companies found; step 1 unverified. "

    # Step 2 -- run on the average of whatever figures we have.
    if today is None:
        # An unreleased film has no budget *yet*. Defaulting it to A would file
        # next year's tentpoles as alternative cinema, so say so instead.
        if _unreleased(meta, year):
            v.verdict = "?"
            v.reason = ("not yet released and no budget published; "
                        "step 2 cannot be applied")
            v.confidence = "none"
            v.notes += note
            return v
        v.verdict = "A"
        v.reason = "no major studio; no budget figure found (rule: treat as A)"
        v.confidence = "low"
        v.notes += note
        return v
    two = (v.budget_wikipedia_today is not None
           and v.budget_tmdb_today is not None)
    avg = "avg of 2 sources" if two else v.budget_source
    if today > bud.THRESHOLD_USD_TODAY:
        v.verdict = "H"
        v.reason = (f"no major studio, but budget ${today/1e6:.1f}M in today's "
                    f"money, {avg} (> $35M)")
    else:
        v.verdict = "A"
        v.reason = (f"no major studio; budget ${today/1e6:.1f}M in today's "
                    f"money, {avg} (< $35M)")
    margin = abs(today - bud.THRESHOLD_USD_TODAY) / bud.THRESHOLD_USD_TODAY
    v.confidence = "medium" if margin < 0.25 else "high"
    if v.budget_straddles:
        v.confidence = "medium"
        v.notes += "sources disagree across the threshold; "
    if not companies:
        v.confidence = "low"
    v.notes += note
    return v
