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

**Identity: Wikidata, confirmed by TMDB.**
Titles are matched by name similarity *and* release year; a candidate that cannot be
verified on year is rejected rather than guessed at. Without this, TMDB happily matched
*Adolescence* to a documentary called *The Real Adolescence: Our Killer Kids*.

Wikimedia rate-limits shared IPs aggressively, so requests are paced and retried with
backoff. A full run of a few hundred films takes on the order of fifteen minutes.

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
out/           classification results (committed)
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
classifications for a personal watchlist, not a TMDB data dump.
