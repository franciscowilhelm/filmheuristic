"""Step 1 of the heuristic: is a major studio behind the film?

Matching runs against production/financing companies only -- never the
distributor, so a regional pickup (Universal releasing *Brazil* in the US)
does not make a film H.

Order matters: specialty labels are tested first, because their names contain
their parent major's name ("Fox Searchlight", "Sony Pictures Classics").
"""

import re

# Labels that answer "no" at step 1 and go on to the budget test.
SPECIALTY = [
    r"fox\s*searchlight",
    r"\bsearchlight\b",
    r"focus\s*features",
    r"sony\s*pictures\s*classics",
    r"paramount\s*vantage",
    r"paramount\s*classics",
    r"miramax",              # incl. the Disney years, 1993-2010
    r"dimension\s*films",
    r"fox\s*atomic",
    r"screen\s*gems",        # arguable; kept out, see NOTE below
]

# NOTE: Screen Gems is listed as a Sony major in the rule text but operates as
# a genre/low-budget label. It is excluded here so the budget test decides it.
# Flip it by deleting the line above if you want it back in step 1.

# Majors, by parent group. Each entry is (regex, group label).
MAJORS = [
    # Disney
    (r"walt\s*disney(\s*pictures|\s*productions|\s*animation)?", "Disney"),
    (r"\bdisney\b", "Disney"),
    (r"touchstone", "Disney"),          # Disney's own adult label, not an acquisition
    (r"hollywood\s*pictures", "Disney"),
    (r"caravan\s*pictures", "Disney"),
    (r"pixar", "Disney"),
    (r"marvel\s*studios", "Disney"),
    (r"lucasfilm", "Disney"),
    (r"20th\s*century\s*(fox|studios)", "Disney/Fox"),
    (r"twentieth\s*century[\s-]*fox", "Disney/Fox"),
    (r"fox\s*2000", "Disney/Fox"),
    (r"blue\s*sky\s*studios", "Disney/Fox"),
    # Universal / Comcast
    (r"universal\s*(pictures|studios|city\s*studios|international)?", "Universal"),
    (r"illumination", "Universal"),
    (r"dreamworks\s*animation", "Universal"),
    (r"working\s*title", "Universal"),
    (r"focus\s*world", "Universal"),
    # Warner Bros.
    (r"warner\s*bros", "Warner"),
    (r"warner\s*brothers", "Warner"),
    (r"new\s*line\s*cinema", "Warner"),
    (r"\bdc\s*(studios|films|entertainment)\b", "Warner"),
    (r"castle\s*rock", "Warner"),
    # Paramount / Skydance
    (r"paramount\s*(pictures|animation|players)?", "Paramount"),
    (r"nickelodeon\s*movies", "Paramount"),
    (r"skydance", "Paramount"),
    # Sony
    (r"columbia\s*pictures", "Sony"),
    (r"tristar", "Sony"),
    (r"sony\s*pictures(\s*animation|\s*entertainment|\s*releasing)?", "Sony"),
    # Amazon MGM
    (r"amazon\s*mgm", "Amazon MGM"),
    (r"\bmgm\b", "Amazon MGM"),
    (r"metro[\s-]*goldwyn[\s-]*mayer", "Amazon MGM"),
    (r"united\s*artists", "Amazon MGM"),
    # Classic era only (pre-1970) -- see CLASSIC_ONLY below
    (r"\brko\b", "RKO"),
    (r"radio[\s-]*keith[\s-]*orpheum", "RKO"),
]

# Groups whose H status only holds for films released before this year.
# RKO stopped being a major long ago; everything else on the list is current.
CLASSIC_ONLY = {"RKO": 1970}

# Deliberately NOT majors: the budget test decides them.
NOT_MAJORS = [
    "Netflix", "Apple", "Apple Studios", "Apple Original Films",
    "Lionsgate", "Lions Gate", "A24", "Neon", "DreamWorks SKG",
    "DreamWorks Pictures", "Annapurna", "Blumhouse", "Legendary",
    "Village Roadshow", "Amblin",
]

_SPECIALTY_RE = re.compile("|".join(SPECIALTY), re.I)
_MAJORS_RE = [(re.compile(p, re.I), g) for p, g in MAJORS]

# DreamWorks SKG (1994-2016) is not a major, but DreamWorks Animation is
# (Universal). Disambiguate before the generic patterns run.
_DW_ANIM = re.compile(r"dreamworks\s*animation", re.I)
_DW_SKG = re.compile(r"dreamworks(?!\s*animation)", re.I)


def normalise(name: str) -> str:
    """Strip corporate suffixes and punctuation noise from a company name."""
    n = re.sub(r"\[\[|\]\]", " ", name)
    n = re.sub(r"\b(inc|ltd|llc|gmbh|s\.?a\.?|co|corp|corporation|company|"
               r"productions?|entertainment\s*group|film(s)?\s*group)\b\.?", " ", n, flags=re.I)
    n = re.sub(r"[.,]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def match_major(company: str, year: int | None) -> tuple[str, str] | None:
    """Return (group, matched_text) if this company is a major, else None."""
    n = normalise(company)
    if not n:
        return None
    if _DW_SKG.search(n) and not _DW_ANIM.search(n):
        return None
    if _SPECIALTY_RE.search(n):
        return None
    for rx, group in _MAJORS_RE:
        if rx.search(n):
            cutoff = CLASSIC_ONLY.get(group)
            if cutoff and year and year >= cutoff:
                continue
            return group, n
    return None


def scan(companies: list[str], year: int | None) -> list[tuple[str, str]]:
    """All major hits among a film's production companies."""
    hits = []
    for c in companies:
        m = match_major(c, year)
        if m and m not in hits:
            hits.append(m)
    return hits
