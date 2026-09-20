"""Keyless metadata lookup: Wikidata (for identity) -> Wikipedia (for the
infobox), with optional TMDB enrichment when TMDB_API_KEY is set.

Wikidata's SPARQL endpoint rate-limits hard from shared IPs, so we use the
action API instead.
"""

import atexit
import json
import math
import os
import re
import time
from pathlib import Path

import httpx
from difflib import SequenceMatcher
from urllib.parse import urlsplit


def title_sim(a: str, b: str, strip_articles: bool = True) -> float:
    """Title similarity, ignoring punctuation and case.

    Articles are dropped by default, because Letterboxd and TMDB disagree about
    them constantly. That tolerance has a cost: it makes *The Obsession* a
    perfect match for *Obsession*, which are different films. Callers that are
    choosing between candidates should score with strip_articles=False as well,
    and let the strict figure break the tie.
    """
    def norm(x):
        x = re.sub(r"[^a-z0-9 ]+", " ", (x or "").lower())
        if strip_articles:
            x = re.sub(r"^(the|a|an|le|la|les|el|il|der|die|das)\s+", "", x)
        return re.sub(r"\s+", " ", x).strip()
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()

UA = "filmheuristic/0.1 (personal watchlist research; contact via Letterboxd)"
WD_API = "https://www.wikidata.org/w/api.php"
WP_API = "https://en.wikipedia.org/w/api.php"
TMDB_API = "https://api.themoviedb.org/3"

# Minimum seconds between requests to each host. Wikimedia's anonymous burst
# limit is the binding constraint on a full run -- once tripped it answers 429
# with Retry-After: 35, so a request saved by hurrying costs thirty-five.
# TMDB is authenticated and unbothered at this volume.
HOST_INTERVAL = {
    "en.wikipedia.org": 2.0,
    "www.wikidata.org": 2.0,
    "api.themoviedb.org": 0.05,
}

FILM_CLASSES = {
    "Q11424",    # film
    "Q24856",    # film series (rare mismatch, still accept)
    "Q506240",   # television film
    "Q202866",   # animated film
    "Q229390",   # 3D film
    "Q18011172", # film project
    "Q20650540", # arthouse film
    "Q93204",    # documentary film
    "Q226730",   # silent film
    "Q24862",    # short film
}


class Cache:
    """Plain JSON on disk -- every network answer is stored, so reruns are free.

    Writes are batched. Saving on every answer re-serialises the whole file,
    which is free at a few hundred kilobytes and ruinous once the cache has
    grown: at 32MB a full run spent more time rewriting JSON than waiting on
    the network, several seconds per film against a 0.6s request delay. The
    file is written every FLUSH_EVERY answers and again on exit, so an
    interrupted run costs at most the last few lookups, which are re-fetchable.

    The write goes to a temporary file and is renamed over the original, so a
    process killed mid-write cannot leave a truncated cache behind.
    """

    FLUSH_EVERY = 100

    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {}
        self._pending = 0
        atexit.register(self.flush)

    def get(self, key):
        return self.data.get(key)

    def put(self, key, value):
        self.data[key] = value
        self._pending += 1
        if self._pending >= self.FLUSH_EVERY:
            self.flush()

    def flush(self):
        if not self._pending:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False))
        tmp.replace(self.path)
        self._pending = 0


def _key_from_dotenv() -> str | None:
    """Read TMDB_API_KEY from a .env file next to the project, if present."""
    for base in (Path.cwd(), Path(__file__).resolve().parents[2]):
        env = base / ".env"
        if not env.exists():
            continue
        for line in env.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "TMDB_API_KEY":
                return v.strip().strip("\"'") or None
    return None


def _page_years(page: str, box: dict) -> list[int]:
    """Release years for a candidate article, from its disambiguator and its
    infobox. A film that premiered at a festival one year and opened the next
    legitimately has two, and either may be the one the watchlist recorded."""
    out = []
    m = re.search(r"\((\d{4})\s+film\)", page)
    if m:
        out.append(int(m.group(1)))
    out += [int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b",
                                      box.get("released") or "")]
    return sorted(set(out))


class Client:
    def __init__(self, cache: Cache, delay: float = 0.6):
        self.cache = cache
        self.delay = delay
        self.http = httpx.Client(headers={"User-Agent": UA}, timeout=30,
                                 follow_redirects=True)
        self.tmdb_key = os.environ.get("TMDB_API_KEY") or _key_from_dotenv()
        self._interval = dict(HOST_INTERVAL)
        self._last: dict[str, float] = {}
        self.throttled: dict[str, int] = {}

    @property
    def _tmdb_is_v4(self) -> bool:
        """TMDB hands out two credentials: a v3 api_key and a v4 JWT token."""
        return bool(self.tmdb_key) and self.tmdb_key.startswith("eyJ")

    def _tmdb_get(self, path, params, cache_key):
        headers = {"Authorization": f"Bearer {self.tmdb_key}"} if self._tmdb_is_v4 else {}
        if not self._tmdb_is_v4:
            params = {**params, "api_key": self.tmdb_key}
        return self._get(f"{TMDB_API}{path}", params, cache_key, headers=headers)

    def _pace(self, host: str) -> None:
        """Hold each host to its own minimum interval between requests."""
        gap = self._interval.get(host, self.delay)
        last = self._last.get(host)
        if last is not None:
            owed = gap - (time.monotonic() - last)
            if owed > 0:
                time.sleep(owed)
        self._last[host] = time.monotonic()

    def _get(self, url, params, cache_key, headers=None):
        hit = self.cache.get(cache_key)
        if hit is not None:
            return hit
        # Wikimedia enforces a burst limit per IP and answers 429 with
        # Retry-After: 35 once it is tripped, which costs far more than going
        # fast ever saves. A flat delay shared across three hosts does not
        # express that: TMDB is keyed and does not care, while en.wikipedia.org
        # and wikidata.org need room. So each host is paced separately, and a
        # host that throttles us is slowed for the rest of the run rather than
        # only for the request that tripped it.
        host = urlsplit(url).netloc
        for attempt in range(7):
            self._pace(host)
            r = self.http.get(url, params=params, headers=headers or {})
            if r.status_code in (429, 503):
                self.throttled[host] = self.throttled.get(host, 0) + 1
                was = self._interval.get(host, self.delay)
                self._interval[host] = min(was * 1.5, 10.0)
                ra = r.headers.get("Retry-After")
                time.sleep(float(ra) if ra and ra.isdigit()
                           else min(2 * (attempt + 1), 60))
                continue
            r.raise_for_status()
            # Ease back towards the baseline after a clean answer. Without
            # this, one burst of 429s early on slows every remaining film for
            # the rest of the run: three throttles take Wikidata from 2s to
            # nearly 7s a request and it never recovers.
            base = HOST_INTERVAL.get(host, self.delay)
            if self._interval.get(host, base) > base:
                self._interval[host] = max(base, self._interval[host] * 0.97)
            out = r.json()
            self.cache.put(cache_key, out)
            return out
        raise RuntimeError(f"rate-limited after {attempt + 1} attempts: {url}")

    # --- Wikidata -------------------------------------------------------
    def find_film(self, title: str, year: int | None) -> dict | None:
        """Find the Wikidata item for a film, verified by type and year."""
        search = self._get(WD_API, {
            "action": "wbsearchentities", "search": title, "language": "en",
            "uselang": "en", "type": "item", "limit": 12, "format": "json",
        }, f"wdsearch::{title}::{year}")
        ids = [h["id"] for h in search.get("search", [])]
        if not ids:
            return None
        ents = self._get(WD_API, {
            "action": "wbgetentities", "ids": "|".join(ids[:12]),
            "props": "claims|labels|sitelinks", "format": "json",
        }, f"wdents::{'|'.join(ids[:12])}")
        best = None
        for qid in ids:
            ent = ents.get("entities", {}).get(qid)
            if not ent:
                continue
            classes = {c["mainsnak"]["datavalue"]["value"]["id"]
                       for c in ent.get("claims", {}).get("P31", [])
                       if c["mainsnak"].get("datavalue")}
            if not classes & FILM_CLASSES:
                continue
            yrs = self._years(ent)
            if year and not yrs:
                continue          # cannot verify -- do not guess
            score = 0
            if year and yrs:
                gap = min(abs(year - y) for y in yrs)
                if gap > 2:
                    continue
                score = 10 - gap
            best_now = (score, qid, ent)
            if best is None or best_now[0] > best[0]:
                best = best_now
        if best is None:
            return None
        _, qid, ent = best
        return self._film_record(qid, ent)

    def film_from_qid(self, qid: str, title: str, year: int | None) -> dict | None:
        """Build the film record for a Wikidata id we already know.

        TMDB's external_ids hands over the Wikidata id outright, which lets the
        whole wbsearchentities step be skipped. That matters: every other
        request in a lookup answers in under a second, while the entity search
        is throttled hard enough to spend fifty-four seconds on one film.

        The entity is still checked, not trusted: it has to be a film, and its
        release years have to agree with the watchlist. An entity carrying no
        release date at all is accepted here, unlike in a search, because the
        identification did not come from matching a label -- TMDB already
        verified title and year, and this is a cross-reference to it.
        """
        ents = self._get(WD_API, {
            "action": "wbgetentities", "ids": qid,
            "props": "claims|labels|sitelinks", "format": "json",
        }, f"wdents::{qid}")
        ent = ents.get("entities", {}).get(qid)
        if not ent or "missing" in ent:
            return None
        classes = {c["mainsnak"]["datavalue"]["value"]["id"]
                   for c in ent.get("claims", {}).get("P31", [])
                   if c["mainsnak"].get("datavalue")}
        if not classes & FILM_CLASSES:
            return None
        yrs = self._years(ent)
        if year and yrs and min(abs(year - y) for y in yrs) > 2:
            return None
        return self._film_record(qid, ent)

    def _film_record(self, qid: str, ent: dict) -> dict:
        labels = self._labels_many(ent, ("P272", "P750", "P495"))
        return {
            "qid": qid,
            "years": self._years(ent),
            "companies": labels["P272"],              # production company
            "distributors": labels["P750"],
            "countries": labels["P495"],
            "enwiki": ent.get("sitelinks", {}).get("enwiki", {}).get("title"),
            "cost": self._cost(ent),
        }

    @staticmethod
    def _years(ent):
        out = []
        for c in ent.get("claims", {}).get("P577", []):
            dv = c["mainsnak"].get("datavalue")
            if dv:
                m = re.match(r"[+-](\d{4})", dv["value"]["time"])
                if m:
                    out.append(int(m.group(1)))
        return sorted(set(out))

    def _labels_many(self, ent, props) -> dict[str, list[str]]:
        """Resolve several properties' labels in one request.

        Each property used to cost its own wbgetentities call -- three per
        film, every one of them throttled. The ids all come from the same
        entity and the API takes fifty at a time, so one call does for all
        three. Claim order is preserved, and ids Wikidata has no English label
        for are dropped rather than returned as empty strings.
        """
        by_prop = {p: [c["mainsnak"]["datavalue"]["value"]["id"]
                       for c in ent.get("claims", {}).get(p, [])
                       if c["mainsnak"].get("datavalue")] for p in props}
        ids = list(dict.fromkeys(q for qs in by_prop.values() for q in qs))[:50]
        labels = {}
        if ids:
            data = self._get(WD_API, {
                "action": "wbgetentities", "ids": "|".join(ids),
                "props": "labels", "languages": "en", "format": "json",
            }, f"wdlabels::{'|'.join(sorted(ids))}")
            for q, e in data.get("entities", {}).items():
                v = e.get("labels", {}).get("en", {}).get("value")
                if v:
                    labels[q] = v
        return {p: [labels[q] for q in qs if q in labels]
                for p, qs in by_prop.items()}

    @staticmethod
    def _cost(ent):
        for c in ent.get("claims", {}).get("P2130", []):
            dv = c["mainsnak"].get("datavalue")
            if dv:
                amt = dv["value"].get("amount", "").lstrip("+")
                unit = dv["value"].get("unit", "").rsplit("/", 1)[-1]
                return {"amount": amt, "unit_qid": unit}
        return None

    # --- Wikipedia infobox ----------------------------------------------
    def infobox(self, page_title: str) -> dict:
        data = self._get(WP_API, {
            "action": "query", "prop": "revisions", "rvprop": "content",
            "rvslots": "main", "titles": page_title, "format": "json",
            "formatversion": "2", "redirects": "1",
        }, f"wp::{page_title}")
        pages = data.get("query", {}).get("pages", [])
        if not pages or "revisions" not in pages[0]:
            return {}
        text = pages[0]["revisions"][0]["slots"]["main"]["content"]
        return parse_infobox(text)

    # --- Wikipedia search (only when Wikidata could not find the film) ---
    def find_wikipedia_page(self, title: str, year: int | None) -> str | None:
        """Find the en.wikipedia article for a film, verified on year.

        Wikidata's wbsearchentities matches entity *labels*, which is hopeless
        for a common word. Searching it for "Obsession" returns a Star Trek
        short story, a video game, a pornographic actress and an album before
        any film at all, and the one we want is nowhere in the first twelve --
        so step 1 sees no production companies and step 2 sees no budget, for a
        film whose Wikipedia article states both. Wikipedia's own full-text
        search finds "Obsession (2025 film)" first, because the disambiguator
        it needs is in the page title.

        The year check is kept as strict as everywhere else: a page whose year
        cannot be established is rejected rather than guessed at.
        """
        res = self._get(WP_API, {
            "action": "query", "list": "search",
            "srsearch": f"{title} {year} film" if year else f"{title} film",
            "srlimit": 8, "format": "json", "formatversion": "2",
        }, f"wpsearch::{title}::{year}")
        for hit in res.get("query", {}).get("search", [])[:5]:
            page = hit["title"]
            if title_sim(title, re.sub(r"\s*\(.*?\)\s*$", "", page)) < 0.85:
                continue
            # A disambiguator that does not say "film" belongs to something
            # else -- "Obsession (video game)", "(album)", "(novel)". Skipping
            # those before fetching the article saves a request each, which
            # matters because Wikimedia throttles shared IPs hard and this
            # fallback runs for every film Wikidata could not find.
            dab = re.search(r"\(([^)]*)\)\s*$", page)
            if dab and "film" not in dab.group(1).lower():
                continue
            box = self.infobox(page)
            if not box:
                continue                     # not an {{Infobox film}} article
            if year is not None:
                yrs = _page_years(page, box)
                if not yrs or min(abs(year - y) for y in yrs) > 1:
                    continue
            return page
        return None

    # --- TMDB (optional) -------------------------------------------------
    def tmdb(self, title: str, year: int | None) -> dict | None:
        if not self.tmdb_key:
            return None
        s = self._tmdb_get("/search/movie", {
            "query": title, **({"year": year} if year else {}),
        }, f"tmdbsearch::{title}::{year}")
        hits = s.get("results") or []
        best, best_score = None, -1
        for h in hits:
            ry = (h.get("release_date") or "")[:4]
            ry = int(ry) if ry.isdigit() else None
            if year and ry and abs(ry - year) > 1:
                continue
            if year and not ry:
                continue
            loose = max(title_sim(title, h.get("title")),
                        title_sim(title, h.get("original_title")))
            if loose < 0.85:
                continue
            strict = max(title_sim(title, h.get("title"), strip_articles=False),
                         title_sim(title, h.get("original_title"),
                                   strip_articles=False))
            # A year disagreement of one is routine -- a festival premiere and
            # a theatrical release straddle new year constantly, and Letterboxd
            # records the first while TMDB records the primary. It must not be
            # worth more than the title, or an exact-year match on the wrong
            # film wins: *Obsession* (TIFF 2025, released 2026) lost to an
            # unrelated *The Obsession* from 2025 on exactly that trade.
            score = strict * 10 + loose * 2
            if year and ry is not None:
                score += 3 if ry == year else 1.5
            # Popularity only separates candidates the title and year already
            # allow, but it has to be able to: the wanted film is the one
            # someone put on a watchlist, not a same-named obscurity.
            score += math.log10(1 + max(h.get("popularity", 0), 0))
            if score > best_score:
                best, best_score = h, score
        if best is None:
            return None
        mid = best["id"]
        # external_ids rides along on the same request, and carries the
        # Wikidata id that saves the entity search entirely.
        d = self._tmdb_get(f"/movie/{mid}", {"append_to_response": "external_ids"},
                           f"tmdbmovie::{mid}::ext")
        return {
            "id": mid,
            "wikidata_id": (d.get("external_ids") or {}).get("wikidata_id") or None,
            "release_date": d.get("release_date") or None,
            "status": d.get("status"),
            "budget": d.get("budget") or None,
            "companies": [c["name"] for c in d.get("production_companies", [])],
            "countries": [c["name"] for c in d.get("production_countries", [])],
        }


_INFOBOX_FIELDS = {
    "studio": "companies", "production_companies": "companies",
    "production company": "companies", "production_company": "companies",
    "distributor": "distributors", "budget": "budget",
    "country": "countries", "released": "released", "language": "languages",
}


def _split_list(value: str) -> list[str]:
    """Pull individual names out of a plainlist / ubl / hlist infobox value."""
    v = re.sub(r"<!--.*?-->", " ", value, flags=re.S)
    v = re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", " ", v, flags=re.S | re.I)
    v = re.sub(r"\{\{\s*(plainlist|ubl|unbulleted list|hlist|flatlist|ubt)\s*\|",
               "", v, flags=re.I)
    v = re.sub(r"\{\{[^{}]*\}\}", " ", v)
    v = v.replace("}}", " ")
    v = re.sub(r"<br\s*/?>", "|", v, flags=re.I)
    v = re.sub(r"^\s*\*", "|", v, flags=re.M)
    parts = re.split(r"\||\n", v)
    out = []
    for p in parts:
        p = re.sub(r"\[\[([^\]|]*\|)?([^\]]*)\]\]", r"\2", p)
        p = re.sub(r"[\[\]']", " ", p).strip(" .,;")
        if p and not re.fullmatch(r"(name|title|list)\s*=?.*", p, re.I):
            out.append(re.sub(r"\s+", " ", p))
    return out


def parse_infobox(wikitext: str) -> dict:
    """Extract the fields we need from {{Infobox film}}."""
    m = re.search(r"\{\{\s*Infobox\s+film", wikitext, re.I)
    if not m:
        return {}
    i, depth, start = m.end(), 2, m.end()
    while i < len(wikitext) and depth:
        if wikitext.startswith("{{", i):
            depth += 2; i += 2
        elif wikitext.startswith("}}", i):
            depth -= 2; i += 2
        else:
            i += 1
    body = wikitext[start:i - 2]

    fields, depth, buf = {}, 0, ""
    for ch in body + "|":
        if ch == "|" and depth == 0:
            if "=" in buf:
                k, _, v = buf.partition("=")
                fields[k.strip().lower()] = v.strip()
            buf = ""
            continue
        depth += {"{": 1, "[": 1}.get(ch, 0) - {"}": 1, "]": 1}.get(ch, 0)
        buf += ch

    out = {"companies": [], "distributors": [], "countries": [],
           "budget": None, "released": None, "languages": []}
    for key, target in _INFOBOX_FIELDS.items():
        if key not in fields:
            continue
        raw = fields[key]
        if target == "budget":
            out["budget"] = raw
        elif target == "released":
            out["released"] = raw
        else:
            out[target] = out[target] + [x for x in _split_list(raw)
                                         if x not in out[target]]
    return out
