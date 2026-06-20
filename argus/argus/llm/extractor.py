import json
import logging
from dataclasses import dataclass

from argus.llm.router import call_llm

logger = logging.getLogger(__name__)
LLM_DEFAULT_CONFIDENCE = 0.35
PROMPT_VERSION = "llm-v1"
_SYSTEM = "Jesteś ekspertem od krypto i makro. Odpowiadasz WYŁĄCZNIE poprawnym JSON-em."


@dataclass
class LlmClaim:
    asset_symbol: str
    direction: str
    confidence: float
    reasoning: str


def build_prompt(text: str, assets, sector_map: dict | None) -> str:
    allowed = ", ".join(sorted(a.symbol for a in assets))
    sectors = "\n".join(
        f"- {', '.join(s.get('aliases', [])[:4])} -> {', '.join(s.get('tickers', []))}"
        for s in (sector_map or {}).values()
    )
    return (
        f"Dozwolone assety: {allowed}\n"
        f"Mapowania sektorowe:\n{sectors}\n\n"
        "Z poniższego tekstu wyciągnij TYLKO powiązania kierunkowe z dozwolonych assetów.\n"
        "Zwróć claim WYŁĄCZNIE gdy w tekście jest bezpośrednie lub bardzo silne uzasadnienie. "
        "Jeśli powiązanie jest słabe, spekulacyjne, neutralne lub wymaga dużej interpretacji — zwróć pustą listę [].\n"
        'Zwróć WYŁĄCZNIE JSON: [{"asset":"SYM","direction":"bull|bear","reasoning":"krótko"}]\n\n'
        f"Tekst:\n{text}"
    )


def _extract_json(raw: str):
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    return json.loads(raw[start:end + 1])


def extract_claims_llm(text: str, assets, sector_map: dict | None = None) -> list[LlmClaim]:
    known = {a.symbol for a in assets}
    # call_llm exceptions (429, circuit open) propagate — caller must NOT cache on failure
    raw = call_llm(build_prompt(text, assets, sector_map), system=_SYSTEM, max_tokens=400)
    try:
        data = _extract_json(raw)
    except Exception as e:
        logger.warning("llm json parse failed: %s", e)
        return []
    if not isinstance(data, list):
        return []
    out = []
    for d in data:
        if not isinstance(d, dict):
            continue
        sym = (d.get("asset") or "").upper()
        direction = d.get("direction")
        if sym in known and direction in ("bull", "bear"):
            out.append(LlmClaim(sym, direction, LLM_DEFAULT_CONFIDENCE, (d.get("reasoning") or "")[:500]))
    return out
