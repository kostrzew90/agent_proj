import re
from dataclasses import dataclass

PARSER_VERSION = "rule-v1"

@dataclass
class ParsedClaim:
    asset_symbol: str
    direction: str       # bull|bear|neutral
    confidence: float    # 0..1
    target_price: float | None = None

# (regex, direction, confidence) — kolejność = priorytet (mocniejsze wzorce wyżej)
_PATTERNS = [
    (r"\blong\b", "bull", 0.8),
    (r"\bshort\b", "bear", 0.8),
    (r"\bbullish\b", "bull", 0.6),
    (r"\bbearish\b", "bear", 0.6),
    (r"\bpump(s|ing|ed)?\b", "bull", 0.5),
    (r"\bdump(s|ing|ed)?\b", "bear", 0.5),
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

def extract_claims(text: str, assets) -> list[ParsedClaim]:
    low = text.lower()
    symbols = [a.symbol for a in assets if a.symbol.lower() in re.findall(r"[a-z0-9.]+", low)]
    if not symbols:
        return []
    direction = None
    confidence = 0.0
    for pat, d, conf in _PATTERNS:
        if re.search(pat, low):
            direction, confidence = d, conf
            break
    if direction is None:
        return []
    if _HEDGE.search(text):
        confidence = max(0.2, confidence - 0.4)
    target = _parse_target(text)
    return [ParsedClaim(asset_symbol=s, direction=direction,
                        confidence=round(confidence, 2), target_price=target)
            for s in symbols]
