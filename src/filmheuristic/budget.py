"""Step 2 of the heuristic: is the budget above ~$35M in today's money?"""

import re

THRESHOLD_USD_TODAY = 35_000_000

# Rough inflation factors from the rule, extended either side.
def inflation_factor(year: int | None) -> float:
    if year is None:
        return 1.0
    if year < 1940: return 12.0
    if year < 1950: return 10.0
    if year < 1960: return 9.0
    if year < 1970: return 7.5
    if year < 1980: return 5.5
    if year < 1990: return 3.0
    if year < 2000: return 2.0
    if year < 2010: return 1.6
    if year < 2020: return 1.3
    if year < 2024: return 1.15
    return 1.0

# Rough USD conversion -- "a rough conversion is enough" per the rule.
FX = {
    "$": 1.0, "US$": 1.0, "USD": 1.0,
    "£": 1.27, "GBP": 1.27,
    "€": 1.08, "EUR": 1.08,
    "¥": 0.0067, "JPY": 0.0067,
    "₹": 0.012, "INR": 0.012, "Rs": 0.012,
    "A$": 0.66, "AUD": 0.66,
    "CA$": 0.73, "C$": 0.73, "CAD": 0.73,
    "CHF": 1.12, "SEK": 0.095, "NOK": 0.094, "DKK": 0.145,
    "R$": 0.19, "₩": 0.00074, "KRW": 0.00074,
    "DM": 0.69,            # Deutsche Mark, via its fixed euro rate
    "FRF": 0.165, "F": 0.165, "₣": 0.165,
    "₤": 1.27, "ITL": 0.00056, "₨": 0.012,
    "MX$": 0.055, "HK$": 0.128, "NT$": 0.031, "RMB": 0.14, "CN¥": 0.14,
}

_SCALE = {
    "thousand": 1e3, "million": 1e6, "billion": 1e9,
    "m": 1e6, "mil": 1e6, "bn": 1e9, "k": 1e3,
    "crore": 1e7, "lakh": 1e5, "lakhs": 1e5,
}

_CUR_RE = "|".join(sorted((re.escape(k) for k in FX), key=len, reverse=True))
_NUM = r"(\d[\d,.]*)"
_AMOUNT_RE = re.compile(
    rf"(?P<cur>{_CUR_RE})?\s*{_NUM}\s*"
    rf"(?P<scale>million|billion|thousand|crore|lakhs?|mil\b|bn\b|m\b|k\b)?",
    re.I,
)


# Wikipedia writes currencies as templates: {{KRW|17 billion}}, {{INR}}250 crore,
# {{US$|12.2 million}}. Stripping braces naively drops the currency code and the
# amount silently becomes dollars, so expand them properly.
CURRENCY_TEMPLATES = {
    "us$": "$", "usd": "$", "currency": "", "monospaced": "",
    "inr": "INR", "indian rupee": "INR", "rs": "INR", "rupee": "INR",
    "krw": "KRW", "won": "KRW", "jpy": "JPY", "yen": "JPY",
    "eur": "EUR", "euro": "EUR", "gbp": "GBP", "pound": "GBP", "gbp2": "GBP",
    "cad": "CAD", "aud": "AUD", "cny": "RMB", "rmb": "RMB", "chf": "CHF",
    "sek": "SEK", "nok": "NOK", "dkk": "DKK", "brl": "R$", "mxn": "MX$",
    "hkd": "HK$", "twd": "NT$", "dem": "DM", "frf": "FRF", "itl": "ITL",
}
# Templates that merely wrap text; keep their contents.
PASSTHROUGH = {"nowrap", "nobr", "small", "0", "ubl", "plainlist", "flatlist",
               "based on", "circa", "c.", "abbr", "convert", "formatnum", "val"}


def _expand_templates(text: str) -> str:
    """Rewrite {{KRW|17 billion|link=yes}} as "KRW 17 billion", innermost first."""
    for _ in range(6):                       # bounded: templates nest a little
        new = re.sub(r"\{\{([^{}]*)\}\}", _expand_one, text)
        if new == text:
            break
        text = new
    return text


def _expand_one(m) -> str:
    parts = [p.strip() for p in m.group(1).split("|")]
    name = parts[0].lower().strip()
    args = [p for p in parts[1:] if "=" not in p]
    if name in CURRENCY_TEMPLATES:
        return f" {CURRENCY_TEMPLATES[name]} {' '.join(args)} "
    if name in PASSTHROUGH:
        return " " + " ".join(args) + " "
    return " " + " ".join(args) + " " if args else " "


def _to_float(num: str) -> float | None:
    num = num.rstrip(".")
    # "1,234,567" vs European "1.234.567" vs "1.5"
    if "," in num and "." in num:
        num = num.replace(",", "")
    elif num.count(",") == 1 and len(num.split(",")[1]) <= 2:
        num = num.replace(",", ".")
    else:
        num = num.replace(",", "")
    try:
        return float(num)
    except ValueError:
        return None


# Currencies written after the amount ("60 million DM", "3 million pounds").
NAMED = {
    r"deutsche\s*marks?|deutschmarks?|\bDM\b": "DM",
    r"pounds?(\s*sterling)?|\bGBP\b": "GBP",
    r"euros?|\bEUR\b": "EUR",
    r"yen|\bJPY\b": "JPY",
    r"(french\s*)?francs?|\bFRF\b": "FRF",
    r"rupees?|\bINR\b": "INR",
    r"(swedish\s*)?kronor|\bSEK\b": "SEK",
    r"(australian\s*)?dollars?\s*\(AUD\)|\bAUD\b": "AUD",
    r"\bCAD\b|canadian\s*dollars?": "CAD",
    r"(south\s*korean\s*)?won\b|\bKRW\b": "KRW",
    r"lire|\bITL\b": "ITL",
    r"(swiss\s*)?francs?\s*\(CHF\)|\bCHF\b": "CHF",
    r"(chinese\s*)?yuan|renminbi|\bRMB\b|\bCNY\b": "RMB",
}
_SCALE_WORDS = r"(?:million|billion|thousand|crore|lakhs?|mil|bn|m|k)"


def _hoist_trailing_currency(t: str) -> str:
    """Rewrite "60 million DM" as "DM 60 million" so one regex handles both."""
    for pat, code in NAMED.items():
        t = re.sub(rf"(\d[\d,.]*\s*{_SCALE_WORDS}?)\s*(?:{pat})",
                   lambda m, c=code: f"{c} {m.group(1)}", t, flags=re.I)
    return t


def parse_amount(text: str) -> tuple[float | None, str]:
    """Parse a free-text budget string into nominal USD. Returns (usd, note)."""
    if not text:
        return None, "no budget text"
    t = re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", " ", text, flags=re.S | re.I)
    t = _expand_templates(t)
    t = re.sub(r"\[\[([^\]|]*\|)?([^\]]*)\]\]", r"\2", t)
    t = t.replace("&nbsp;", " ")
    t = _hoist_trailing_currency(t)
    t = re.sub(r"(\d[\d,.]*)\s*[\u2013\u2014-]\s*(\d[\d,.]*)", r"\2", t)
    if re.search(r"\bunknown\b|\bn/?a\b", t, re.I) and not re.search(r"\d", t):
        return None, "budget stated as unknown"

    best, sticky = None, None
    for m in _AMOUNT_RE.finditer(t):
        val = _to_float(m.group(2))
        if val is None:
            continue
        scale = _SCALE.get((m.group("scale") or "").lower(), 1.0)
        cur = m.group("cur") or sticky or "$"
        if m.group("cur"):
            sticky = m.group("cur")
        # A bare number under 1000 with no scale is noise (a year, a footnote).
        if scale == 1.0 and val < 10_000:
            continue
        usd = val * scale * FX.get(cur, FX.get(cur.upper(), 1.0))
        # Ranges ("$10-12 million"): take the top of the range.
        if best is None or usd > best[0]:
            best = (usd, f"{cur}{m.group(2)} {m.group('scale') or ''}".strip())
    if best is None:
        return None, f"could not parse budget: {text[:60]!r}"
    return best[0], f"parsed {best[1]}"


def today_usd(nominal_usd: float | None, year: int | None) -> float | None:
    if nominal_usd is None:
        return None
    return nominal_usd * inflation_factor(year)
