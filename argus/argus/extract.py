import re
from dataclasses import dataclass

PARSER_VERSION = "rule-v2"

@dataclass
class ParsedClaim:
    asset_symbol: str
    direction: str       # bull|bear|neutral
    confidence: float    # 0..1
    target_price: float | None = None

# (regex, direction, confidence) — kolejność = priorytet (jednoznaczne/mocniejsze wyżej)
_PATTERNS = [
    (r"\bshort squeeze\b", "bull", 0.7),
    (r"\bgamma squeeze\b", "bull", 0.7),
    (r"\bsqueeze\b", "bull", 0.6),
    (r"\blong\b", "bull", 0.8),
    (r"\bshort\b", "bear", 0.8),
    (r"\bcalls?\b", "bull", 0.7),
    (r"\bputs\b", "bear", 0.7),
    (r"\bbullish\b", "bull", 0.6),
    (r"\bbearish\b", "bear", 0.6),
    (r"\bbreakout\b", "bull", 0.55),
    (r"\bmoonshot\b", "bull", 0.55),
    (r"\bmoon(ing|ed)?\b", "bull", 0.5),
    (r"🚀", "bull", 0.5),
    (r"\brip(s|ping|ped)?\b", "bull", 0.5),
    (r"\bsending\b", "bull", 0.5),
    (r"\bpump(s|ing|ed)?\b", "bull", 0.5),
    (r"\brug(\s*pull)?\b", "bear", 0.6),
    (r"\bbloodbath\b", "bear", 0.6),
    (r"\bmassacre\b", "bear", 0.6),
    (r"\bcapitulation\b", "bear", 0.6),
    (r"\brekt\b", "bear", 0.6),
    (r"\bdrilling\b", "bear", 0.55),
    (r"\bsell\s*off\b", "bear", 0.55),
    (r"\bcrash(ing|ed|es)?\b", "bear", 0.55),
    (r"\bdump(s|ing|ed)?\b", "bear", 0.5),
    (r"\bbuy\b", "bull", 0.4),
    (r"\bsell\b", "bear", 0.4),
]
_HEDGE = re.compile(r"\b(maybe|might|could|a bit|slightly|imo)\b", re.I)
_TARGET = re.compile(r"target\s*\$?([0-9][0-9.,]*)\s*([kKmM]?)")

def _parse_target(text: str) -> float | None:
    m = _TARGET.search(text)
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    unit = m.group(2).lower()
    return num * {"k": 1_000, "m": 1_000_000, "": 1}[unit]

def extract_claims(text: str, assets, sector_map: dict | None = None) -> list[ParsedClaim]:
    low = text.lower()
    tokens = set(re.findall(r"[a-z0-9]+", low))            # cashtag/punctuation-robust
    symbols = [a.symbol for a in assets if a.symbol.lower() in tokens]
    direction, confidence = None, 0.0
    for pat, d, conf in _PATTERNS:
        if re.search(pat, low):
            direction, confidence = d, conf
            break
    if direction is None:
        return []
    if _HEDGE.search(text):
        confidence = max(0.2, confidence - 0.4)
    target = _parse_target(text)
    claimed = set(symbols)
    out = [ParsedClaim(s, direction, round(confidence, 2), target) for s in symbols]
    if sector_map:
        known = {a.symbol for a in assets}
        for sec in sector_map.values():
            if any(alias.lower() in low for alias in sec.get("aliases", [])):
                sconf = round(float(sec.get("confidence", 0.3)), 2)
                for tk in sec.get("tickers", []):
                    if tk not in claimed and tk in known:
                        claimed.add(tk)
                        out.append(ParsedClaim(tk, direction, sconf, None))
    return out
