import logging
import os

import httpx

logger = logging.getLogger(__name__)

PROM_URL = os.getenv("ARGUS_PROMETHEUS_URL", "http://mac-prometheus:9090")

_ROUTE = 'route=~"/v1/(chat/completions|embeddings)"'
_APPS = {
    "argus-extract": "Argus",
    "rag-chat": "RAG",
    "ocr": "OCR",
    "mac-ocr": "OCR",
    "mac-ocr-2": "OCR",
    "mac-embed": "Wektory",
    "google-embed": "Wektory",
}
_PROVIDERS = {
    "ollama": "Mac",
    "ollama_chat": "Mac",
    "openrouter": "OpenRouter",
    "gemini": "Gemini",
}
_APP_ORDER = ["Argus", "RAG", "OCR", "Wektory", "Inne"]
_BY = "sum by (requested_model, api_provider)"
_MAC_PROVIDERS = ("ollama", "ollama_chat")
# Alias LiteLLM -> model OpenRouter. Przy braku dokladnego odpowiednika bierzemy najmniejszy
# model z tej samej rodziny co najmniej tak duzy (koszt minimalnie zawyzony, nigdy zanizony).
_OR_MODELS = {
    "argus-extract": "qwen/qwen3.6-35b-a3b",
    "mac-qwen": "qwen/qwen3.6-35b-a3b",
    "rag-chat": "google/gemma-4-26b-a4b-it",
    "mac-gemma": "google/gemma-4-26b-a4b-it",
    "ocr": "z-ai/glm-5.3-flash",
    "mac-ocr": "z-ai/glm-5.3-flash",
    "mac-ocr-2": "nvidia/nemotron-3.5-lightning",
    "mac-embed": "baai/bge-m3",
}
_OR_URLS = (
    "https://openrouter.ai/api/v1/models",
    "https://openrouter.ai/api/v1/embeddings/models",
)


def _query(expr: str) -> list:
    r = httpx.get(f"{PROM_URL}/api/v1/query", params={"query": expr}, timeout=15)
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "success":
        raise RuntimeError(f"Prometheus: {body}")
    return body["data"]["result"]


def _app(model) -> str:
    return _APPS.get(model or "", "Inne")


def _provider(name) -> str:
    return _PROVIDERS.get(name or "", name or "?")


def _num(x: float) -> str:
    return f"{int(round(x)):,}".replace(",", " ")


def _dec(x: float, digits: int) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


def _collect(result, by_provider=True) -> dict:
    """{(app, provider): value} lub {app: value} gdy by_provider=False."""
    out = {}
    for r in result:
        m = r["metric"]
        v = float(r["value"][1])
        key = (_app(m.get("requested_model")), _provider(m.get("api_provider"))) if by_provider \
            else _app(m.get("requested_model"))
        out[key] = out.get(key, 0.0) + v
    return out


def _fetch_or_prices() -> dict:
    """{model_id: (prompt, completion)} w $ za token; brak completion = 0."""
    out = {}
    for url in _OR_URLS:
        r = httpx.get(url, timeout=15)
        r.raise_for_status()
        for m in r.json().get("data", []):
            pr = m.get("pricing") or {}
            out[m["id"]] = (float(pr.get("prompt") or 0), float(pr.get("completion") or 0))
    return out


def _mac_by_alias(result) -> dict:
    """{requested_model: value} tylko dla wierszy obsluzonych przez Mac."""
    out = {}
    for r in result:
        m = r["metric"]
        if m.get("api_provider") in _MAC_PROVIDERS:
            k = m.get("requested_model") or ""
            out[k] = out.get(k, 0.0) + float(r["value"][1])
    return out


def _openrouter_line(tin_raw, tout_raw, prices_fn) -> str | None:
    mac_in = _mac_by_alias(tin_raw)
    mac_out = _mac_by_alias(tout_raw)
    aliases = {a for a in set(mac_in) | set(mac_out) if mac_in.get(a, 0) + mac_out.get(a, 0) > 0}
    if not aliases:
        return None
    label = "Gdyby przez OpenRouter:"
    try:
        prices = (prices_fn or _fetch_or_prices)()
    except Exception as e:
        logger.warning("llm_report: cennik OpenRouter niedostępny: %s", e)
        return f"{label} brak cennika"
    per_app, missing = {}, {}
    for a in sorted(aliases):
        ti, to = mac_in.get(a, 0.0), mac_out.get(a, 0.0)
        price = prices.get(_OR_MODELS.get(a, ""))
        if price is None:
            missing[a] = ti + to
            continue
        app = _app(a)
        per_app[app] = per_app.get(app, 0.0) + ti * price[0] + to * price[1]
    total = sum(per_app.values())
    apps = ", ".join(f"{a} {_dec(per_app[a], 4)}" for a in _APP_ORDER if per_app.get(a, 0) > 0)
    line = f"{label} ~{_dec(total, 4)} $ / 24 h" + (f" ({apps})" if apps else "")
    line += f" · ~{_dec(total * 30, 2)} $/mies."
    if missing:
        line += " (bez cennika: " + ", ".join(f"{a} {_num(n)} tok." for a, n in missing.items()) + ")"
    return line


def build_section(query_fn=None, prices_fn=None) -> str:
    q = query_fn or _query
    head = "🧠 LLM — ostatnie 24 h"
    try:
        reqs = _collect(q(f'{_BY}(increase(litellm_proxy_total_requests_metric_total{{{_ROUTE}}}[24h]))'))
        errs = _collect(q(
            f'sum by (requested_model)(increase(litellm_proxy_total_requests_metric_total'
            f'{{{_ROUTE},status_code!~"2.."}}[24h]))'), by_provider=False)
        tin_raw = q(f'{_BY}(increase(litellm_input_tokens_metric_total[24h]))')
        tout_raw = q(f'{_BY}(increase(litellm_output_tokens_metric_total[24h]))')
        tin = _collect(tin_raw)
        tout = _collect(tout_raw)
        cost = _collect(q(f'{_BY}(increase(litellm_spend_metric_total[24h]))'))
        lat_sum = q('sum(increase(litellm_llm_api_latency_metric_sum{api_provider=~"ollama.*"}[24h]))')
        lat_cnt = q('sum(increase(litellm_llm_api_latency_metric_count{api_provider=~"ollama.*"}[24h]))')
    except Exception as e:
        logger.warning("llm_report: Prometheus niedostępny: %s", e)
        return "🧠 LLM: brak danych (Prometheus niedostępny)"

    total = sum(reqs.values())
    if round(total) == 0:
        return f"{head}\nBrak wywołań."

    lines = [head]
    for app in _APP_ORDER:
        by_prov = {p: v for (a, p), v in reqs.items() if a == app and round(v) > 0}
        n = sum(by_prov.values())
        if round(n) == 0:
            continue
        split = ", ".join(
            f"{p} {_num(v)}/{_num(n)}" if p == "Mac" else f"{p} {_num(v)}"
            for p, v in sorted(by_prov.items(), key=lambda kv: (kv[0] != "Mac", kv[0]))
        )
        ti = sum(v for (a, _), v in tin.items() if a == app)
        to = sum(v for (a, _), v in tout.items() if a == app)
        lines.append(
            f"{app}: {_num(n)} zapytań · {split} · tokeny {_num(ti)} wej. / {_num(to)} wyj."
        )

    mac = sum(v for (_, p), v in reqs.items() if p == "Mac")
    mac_line = f"Mac Studio: odpowiedział na {_num(mac)} z {_num(total)} zapytań ({int(round(mac) / round(total) * 100 + 0.5)}%)"
    try:
        s = float(lat_sum[0]["value"][1])
        c = float(lat_cnt[0]["value"][1])
        if c > 0:
            mac_line += f", śr. czas {_dec(s / c, 1)} s"
    except (IndexError, KeyError, ValueError):
        pass
    lines.append(mac_line)

    lines.append(f"Błędy: {_num(sum(errs.values()))}")

    total_cost = sum(cost.values())
    by_prov_cost = {}
    for (_, p), v in cost.items():
        by_prov_cost[p] = by_prov_cost.get(p, 0.0) + v
    parts = ", ".join(f"{p} {_dec(v, 4)} $" for p, v in sorted(by_prov_cost.items()) if v > 0)
    lines.append(f"Koszt: {_dec(total_cost, 4)} $" + (f" ({parts})" if parts else ""))
    or_line = _openrouter_line(tin_raw, tout_raw, prices_fn)
    if or_line:
        lines.append(or_line)
    return "\n".join(lines)
