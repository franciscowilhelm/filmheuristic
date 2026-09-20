# filmheuristic

Classifies films in a Letterboxd watchlist as **H (Hollywood)** or **A (Alternative)**,
so that every H film watched can be paid for with two A films — ideally with at least
one of the two being non-US.

The point is not to avoid Hollywood. It is to make the ratio visible and deliberate.

## The rule

```
Film to classify
      |
      v
Major studio behind it?  --yes-->  H · Hollywood  (owes 2 A films)
      |                                  ^
      no                                 |
      v                                  |
Budget above ~$35M in today's money? --yes
      |
      no
      v
A · Alternative  (trash and cult count too)
```

**Step 1 — is a major behind it?** Only companies that *made or financed* the film
count, never the distributor. A major that merely picked a finished film up for one
territory (Universal releasing *Brazil* in the US) does not make it H. Specialty labels
— Searchlight, Focus Features, Sony Pictures Classics, Paramount Vantage, Miramax in its
Disney years — answer "no" here and go on to the budget test. Netflix, Apple, Lionsgate,
A24, Neon and DreamWorks SKG are deliberately left out of step 1 so that budget decides
them.

**Step 2 — budget in today's money.** Original budgets are inflated by decade
(1970s ×5.5, 1980s ×3, 1990s ×2, 2000s ×1.6, 2010s ×1.3) and converted roughly to USD.
The ~$35M threshold is therefore about $12M for an 80s film.

**Verdicts** are `H`, `A`, or `?`. A `?` means the rule could not be applied honestly —
see [Unresolved films](#unresolved-films).

## Install

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

A TMDB API key is optional but strongly recommended (see [Data sources](#data-sources)).
Put it in a `.env` file at the repo root — both the v3 API key and the v4 read access
token work:

```sh
echo 'TMDB_API_KEY=your_key_here' > .env
```

## Usage

```sh
# the 50 most recently released films in the watchlist
uv run filmheuristic data/<export>/watchlist.csv -r 50 -o out/recent50.csv

# 10 random films, reproducibly
uv run filmheuristic data/<export>/watchlist.csv -n 10 --seed 20260920

# everything
uv run filmheuristic data/<export>/watchlist.csv -o out/all.csv
```

Input is the `watchlist.csv` from a Letterboxd data export (`Name`, `Year` columns);
`watched.csv` and `diary.csv` have the same shape and work too.

Every API response is cached in `data/cache.json`, so re-runs are instant and cost no
requests. Delete the file to force a refresh.

### Output

One row per film in `out/*.csv`. The columns that matter when checking a verdict:

| column | meaning |
| --- | --- |
| `verdict` | `H`, `A` or `?` |
| `reason` | the sentence explaining which step decided it |
| `confidence` | `high` / `medium` / `low` / `none` — see below |
| `majors` | which major studio group was matched, if any |
| `budget_usd_today` | inflated, currency-converted, averaged across sources |
| `budget_wikipedia_today`, `budget_tmdb_today` | the two figures separately |
| `budget_straddles` | true when the sources fall on opposite sides of $35M |
| `company_source` | which source supplied the production companies |
| `non_us` | for the "at least one of the two is non-US" half of the rule |
| `wikipedia`, `wikidata`, `tmdb` | links, so any verdict can be checked by hand |

`confidence` is `medium` when a budget lands within 25% of the threshold or the two
sources disagree across it, and `low` when no production companies were found or the
verdict rests on the no-budget default. Low-confidence rows are the ones worth eyeballing.

## Threshold explorer

The $35M in step 2 is the one number in the rule that was picked rather than
derived. `web/index.html` is a single self-contained page for pushing it around
and watching the watchlist re-sort as it moves. Open it directly — no server:

```sh
uv run python web/build.py && open web/index.html
```

`build.py` bakes the CSVs in `out/`, the decade table below, and the inflation
factors read straight out of `filmheuristic.budget` into the page, so it cannot
drift from the classifier. Re-run it after a new classification run. Step 1 is
not adjustable: a major studio credit is a fact about the film, not a dial.

Two ways to set the line:

**Flat, in today's money** — the rule exactly as written. At $35M the page
reproduces the committed verdicts film for film; move the slider and the rows
that change side are tagged with the verdict they used to have.

**Per decade** — the line becomes a *share of what a major-studio film actually
cost in that decade*, so it tracks the era instead of being CPI-inflated back
from one present-day figure. The slider sets the share; it starts at 30%, which
is roughly what $35M is of a median studio film today, and it recalibrates itself if the
decade figures are regenerated.

**Non-US films: budget test on or off.** Lowering the line far enough to catch US
mid-budget prestige also sweeps in well-funded cinema from everywhere else. On the 50
most recent, a $12M line makes H of *Nickel Boys*, *Priscilla*, *Women Talking* and
*Problemista* — and, in the same move, of *Dhurandhar*, *The Furious*, *Perfect Days*,
*No Other Choice* and *EO*. One global number cannot separate the two, because they cost
the same. Switching the budget test off for non-US films does: they are then A unless a
major studio made or financed them, and the line governs US films only. At that $12M
line it is the difference between 17 H and 12.

The toggle is a real change to the rule, not a display option. It says that scale means
something different outside the US system — that $20M of Korean or Japanese money does
not buy what $20M of American money buys — and it rests entirely on step 1 for those
films. Whether that is right is a judgment about what the rule is for. Films whose
country could not be determined keep the budget test.

### Where the decade figures come from

`scripts/decade_budgets.py` asks TMDB for US films credited to a major studio's
own production company (the step 1 list, resolved to TMDB company IDs), takes
the reported budgets and reports the median per decade, in the money of the
time. Regenerate with:

```sh
uv run python scripts/decade_budgets.py -o web/decade_budgets.json
```

Published series were the obvious alternative and turned out not to be usable:
the MPAA's average negative cost is an average rather than a median, stops in
2007, and exists only as figures quoted in news stories.

| decade | median major budget | budgets found |
| --- | --- | --- |
| 1930s | $0.7M | 90/240 |
| 1940s | $1.4M | 102/240 |
| 1950s | $2.0M | 117/240 |
| 1960s | $4.0M | 132/240 |
| 1970s | $4.4M | 189/240 |
| 1980s | $15.0M | 232/240 |
| 1990s | $45.0M | 235/240 |
| 2000s | $85.0M | 240/240 |
| 2010s | $126.0M | 240/240 |
| 2020s | $126.0M † | 216/240 |

† The 2020s median is the 2010s figure carried forward. It measured $90M, below the 2010s, which cannot be a real fall in what a studio film costs: the decade is incomplete, COVID-era slates sit in the middle of it, and TMDB has no budget yet for many 2025-26 titles. Some genuine pullback is real — streaming took the mid-budget slate — but not a third, so the two decades share one baseline.

Read it with its biases in view, all three of which are recorded in
`web/decade_budgets.json`: TMDB reports a budget for a minority of older films
and the ones it reports skew large and well known; its company credits mix
production and distribution, which is exactly the leak step 1 avoids by reading
Wikipedia's `|studio=` field; and the sample is TMDB's most popular 240 films
per decade, which favours films still watched today. The pre-1980 rows in
particular rest on well under half the sample having a budget at all.

What the table shows regardless of the noise is that studio budgets have risen
far faster than consumer prices. Between the 1980s and the 2010s the median
major-studio budget grows about eightfold, while the rule's inflation factors
imply about 2.3x over the same span. Holding the line at $35M in today's money
is therefore a *stricter* test for recent films than for old ones: on the decade
basis the 1980s line lands near $18M in today's money and the 2010s line near
$65M. Whether that is a bug depends on what the threshold is for. If it marks
"expensive for its moment", the decade basis is closer; if it marks "the kind of
money that buys a film an audience by force", the flat line may be the honest
one. The page exists so the choice can be made by looking rather than by
argument.

## Data sources

Three sources, each used for what it is actually good at. The ordering is not arbitrary —
it was arrived at by measuring where each one fails.

**Step 1 (production companies): Wikipedia → Wikidata → TMDB.**
Wikipedia's infobox is the only source that separates `|studio=` from `|distributor=`,
which is exactly the distinction step 1 depends on. TMDB's `production_companies` is one
flat list that mixes producers and distributors: it credits Universal on *Red Rock West*,
which would wrongly make it H. On a 20-film comparison, classifying from TMDB data alone
got 2 wrong — both false H. Wikidata's P272 leaks the same way (it credits Touchstone on
the same film), so both are fallbacks used only when Wikipedia has nothing.

**Step 2 (budget): Wikipedia and TMDB, averaged.**
The two disagree often enough to matter near the threshold — *The Grand Budapest Hotel*
is $25M on Wikipedia and $30M on TMDB, which inflate to $32.5M and $39M, landing either
side of the line. Both figures are kept, the rule runs on their mean, and
`budget_straddles` flags the disagreement. TMDB also fills real gaps: it has budgets for
films where Wikipedia has none.

**Identity: TMDB first, verified against Wikidata.**
Titles are matched by name similarity *and* release year; a candidate that cannot be
verified on year is rejected rather than guessed at. Without this, TMDB happily matched
*Adolescence* to a documentary called *The Real Adolescence: Our Killer Kids*.

TMDB is asked first, because it answers in well under a second, is authenticated and is
not rate-limited at this volume — and because its `external_ids` carry the film's
Wikidata id outright. That turns the Wikidata step from a fuzzy label search into a
direct fetch of a known entity, which is worth more than it sounds: every other request
in a lookup answers in about a second, while `wbsearchentities` is throttled hard enough
to spend fifty-four seconds on a single film. On a twelve-film sample spanning 1937 to
2026, TMDB had a Wikidata id for all twelve.

Nothing is taken on trust for being fast. TMDB has to match on title and release year,
and the Wikidata entity it hands over has to be a film whose own release years agree
before anything is read off it. When either check fails, the older and slower path runs
instead: search Wikidata by name, and then search Wikipedia.

That fallback exists because Wikidata's entity search matches *labels*, which fails badly
on a common word. Searching it for "Obsession" returns a Star Trek short story, a video game,
a pornographic actress and an album before any film, and the film in question is not in
the first twelve results at all — so step 1 saw no production companies and step 2 saw no
budget, for a film whose Wikipedia article states both. When Wikidata comes back empty,
Wikipedia's own full-text search is tried instead: it finds `Obsession (2025 film)` first,
because the disambiguator is in the page title. The candidate page is still verified on
year before anything is read off it.

This matters beyond filling gaps. Where Wikidata failed, the classifier fell back to
TMDB's flat company list — the one that mixes producers and distributors. *Tony* (2026)
was filed as A on TMDB's credits, which list A24; Wikipedia's `|studio=` shows A24 is the
*distributor* and Metro-Goldwyn-Mayer produced it, which makes it H at step 1.

**Release years disagree by one, constantly.** A film that premieres at a festival in
September and opens the following May has two defensible years, and Letterboxd records
the first while TMDB records the second. A one-year gap is therefore tolerated, and — more
importantly — is not allowed to outweigh the title. It used to be: an exact-year match was
worth half of a perfect title match, so *Obsession* (TIFF 2025, released 2026) lost to an
unrelated *The Obsession* from 2025. Article-stripping made that worse, since it scores
"The Obsession" as a perfect match for "Obsession", so candidates are now also compared
with articles intact and the strict figure breaks the tie.

**Wikimedia rate-limits shared IPs aggressively**, and the limit is a burst limit: trip
it and en.wikipedia.org answers `429` with `Retry-After: 35`, so one request saved by
hurrying costs thirty-five. A single delay shared across all three sources cannot express
that, since TMDB does not care and Wikimedia does, so each host is paced separately
(`HOST_INTERVAL` in `sources.py`). A host that throttles us is slowed for the rest of the
run and then eased back after clean answers, and the run prints which hosts throttled it
rather than hiding it in the timings. A full run of a few hundred films takes on the order
of half an hour.

## Unresolved films

A `?` verdict means the rule could not be applied, which is deliberately distinct from A.
The no-budget default ("no figure: usually A") is safe for an obscure old film and wrong
for an unreleased blockbuster, so two cases are separated out:

- **Not a film.** Letterboxd watchlists contain TV miniseries (*Adolescence*,
  *We Own This City*). These match nothing and are flagged rather than classified.
- **Not yet released.** *Dune: Part Three* has no published budget because it has not
  come out. Its Wikipedia studio credit is Legendary, which step 1 excludes by design, so
  defaulting it to A would file next year's tentpoles as alternative cinema. Films whose
  release date is still in the future, or whose TMDB status is Planned / In Production /
  Post Production, return `?` instead.

## Known limitations

- **The threshold does real work near the line.** Films within ~20% of $35M are decided
  by which budget figure a source happened to record. These are flagged `medium`, and
  they are genuinely arguable rather than wrong.
- **Older films have thinner data.** Budget coverage on Wikipedia and TMDB falls off
  before the 1980s, and the inflation multipliers are rough by construction. Expect more
  low-confidence A verdicts the further back the watchlist goes.
- **Step 1 is blind to mid-century studio financing.** From roughly 1950 to 1980 the
  majors financed and distributed films that a nominally independent company produced,
  and Wikipedia records that arrangement exactly as it was: `|studio=` names the
  producer, `|distributor=` names the major. *Blazing Saddles* is Crossbow Productions
  (Warner Bros.), *Cool Hand Luke* is Jalem (Warner Bros.-Seven Arts), *Anatomy of a
  Murder* is Carlyle (Columbia), *Midnight Cowboy* is Jerome Hellman (United Artists),
  *Hannah and Her Sisters* is Rollins/Joffe (Orion). Step 1 refuses to count a
  distributor, which is the rule that keeps *Brazil* and *Red Rock West* honest, so for
  this entire era it answers "no major" and the budget test decides alone. The threshold
  therefore does *more* work on old films than on new ones, which is the opposite of how
  it looks. On the full watchlist this is where flat and per-decade thresholds disagree:
  all 18 films they classify differently are pre-1990, and every one is A under the flat
  $35M and H under its own decade's line.
- **Inflation is consumer-price inflation, which film budgets have outrun.**
  The factors in `budget.py` imply a 1980s film cost 2.3x less than a 2010s one;
  the median major-studio budgets in [Threshold explorer](#threshold-explorer)
  put the gap nearer 8x. A single threshold in today's money is therefore not
  era-neutral, whatever value it is set to.
- **Foreign-currency budgets are converted at present-day rates**, not the rate at the
  time of production. The rule's own text calls a rough conversion sufficient.
- **The studio list is a judgment call in places.** Touchstone, Hollywood Pictures and
  Caravan are treated as Disney majors (in-house brands, unlike acquired specialty arms);
  Working Title is treated as Universal; Screen Gems is treated as a specialty label and
  falls to the budget test. See `src/filmheuristic/studios.py` — the lists are meant to be
  edited.

## Layout

```
src/filmheuristic/
  studios.py   step 1: major-studio matching, specialty exclusions, era rules
  budget.py    step 2: budget parsing, currency conversion, inflation
  sources.py   Wikidata / Wikipedia / TMDB lookup, caching, rate-limit backoff
  classify.py  the rule
  cli.py       CSV in, CSV out
scripts/
  decade_budgets.py   median major-studio budget per decade, from TMDB
web/
  template.html       the threshold explorer's markup and logic
  build.py            bakes out/*.csv and the decade table into index.html
  index.html          the built page (generated, committed)
out/           classification results (committed; all.csv is the whole watchlist)
data/          Letterboxd export and API cache (not committed)
```

## License

MIT — see [LICENSE](LICENSE). This covers the code only; film metadata carries the terms
described below.

## Credits and attribution

This product uses the TMDB API but is not endorsed or certified by TMDB.

Film metadata comes from [TMDB](https://www.themoviedb.org), Wikipedia and Wikidata.
Wikipedia and Wikidata content is available under [CC BY-SA](https://creativecommons.org/licenses/by-sa/4.0/)
and [CC0](https://creativecommons.org/publicdomain/zero/1.0/) respectively.

TMDB's terms restrict bulk storage and redistribution of their data. `data/cache.json` is
a local request cache and is not committed; the CSVs in `out/` contain derived
classifications for a personal watchlist, and `web/decade_budgets.json` holds ten
summary statistics, not a TMDB data dump.
