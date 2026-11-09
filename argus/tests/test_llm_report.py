from argus import llm_report


def _vec(*items):
    return [{"metric": m, "value": [0, str(v)]} for m, v in items]


def _prices():
    return {
        "qwen/qwen3.6-35b-a3b": (1e-7, 9e-7),
        "google/gemma-4-26b-a4b-it": (1e-7, 4e-7),
        "baai/bge-m3": (1e-8, 0.0),
    }


def _fake(overrides=None):
    reqs = _vec(
        ({"requested_model": "argus-extract", "api_provider": "ollama"}, 4.2),
        ({"requested_model": "rag-chat", "api_provider": "ollama"}, 9.8),
        ({"requested_model": "rag-chat", "api_provider": "openrouter"}, 2.1),
        ({"requested_model": "mac-embed", "api_provider": "ollama"}, 0.0),
    )
    data = {
        "total_requests_metric_total{route": reqs,
        'status_code!~': _vec(({"requested_model": "rag-chat"}, 0.0)),
        "input_tokens": _vec(
            ({"requested_model": "argus-extract", "api_provider": "ollama"}, 3174.4),
            ({"requested_model": "rag-chat", "api_provider": "ollama"}, 10000.0),
        ),
        "output_tokens": _vec(
            ({"requested_model": "argus-extract", "api_provider": "ollama"}, 171.0),
        ),
        "spend": _vec(({"requested_model": "rag-chat", "api_provider": "gemini"}, 0.0012)),
        "latency_metric_sum": _vec(({}, 61.0)),
        "latency_metric_count": _vec(({}, 10.0)),
    }
    data.update(overrides or {})

    def q(expr):
        if "latency_metric_sum" in expr:
            return data["latency_metric_sum"]
        if "latency_metric_count" in expr:
            return data["latency_metric_count"]
        if "spend" in expr:
            return data["spend"]
        if "input_tokens" in expr:
            return data["input_tokens"]
        if "output_tokens" in expr:
            return data["output_tokens"]
        if "status_code!~" in expr:
            return data["status_code!~"]
        return data["total_requests_metric_total{route"]
    return q


def test_per_app_lines_with_split_and_tokens():
    out = llm_report.build_section(_fake(), _prices)
    assert out.startswith("🧠 LLM — ostatnie 24 h")
    assert "Argus: 4 zapytań · Mac 4/4 · tokeny 3 174 wej. / 171 wyj." in out
    assert "RAG: 12 zapytań · Mac 10/12, OpenRouter 2 ·" in out
    assert "Wektory" not in out


def test_mac_share_and_latency():
    out = llm_report.build_section(_fake(), _prices)
    assert "Mac Studio: odpowiedział na 14 z 16 zapytań (88%), śr. czas 6,1 s" in out
    assert "Błędy: 0" in out


def test_cost():
    out = llm_report.build_section(_fake(), _prices)
    assert "Koszt: 0,0012 $ (Gemini 0,0012 $)" in out


def test_zero_requests():
    out = llm_report.build_section(_fake({"total_requests_metric_total{route": []}), _prices)
    assert out == "🧠 LLM — ostatnie 24 h\nBrak wywołań."


def test_query_raises():
    def boom(expr):
        raise RuntimeError("down")
    assert llm_report.build_section(boom) == "🧠 LLM: brak danych (Prometheus niedostępny)"


def test_openrouter_estimate_only_mac_rows():
    out = llm_report.build_section(_fake({
        "input_tokens": _vec(
            ({"requested_model": "argus-extract", "api_provider": "ollama"}, 3174.4),
            ({"requested_model": "rag-chat", "api_provider": "ollama"}, 10000.0),
            ({"requested_model": "rag-chat", "api_provider": "openrouter"}, 999999.0),
            ({"requested_model": "rag-chat", "api_provider": "gemini"}, 999999.0),
        ),
    }), _prices)
    assert "Gdyby przez OpenRouter: ~0,0015 $ / 24 h (Argus 0,0005, RAG 0,0010) · ~0,04 $/mies." in out
    assert out.index("Koszt:") < out.index("Gdyby przez OpenRouter")


def test_openrouter_embedding_without_completion():
    out = llm_report.build_section(_fake({
        "input_tokens": _vec(({"requested_model": "mac-embed", "api_provider": "ollama"}, 1000000.0)),
        "output_tokens": [],
    }), _prices)
    assert "Gdyby przez OpenRouter: ~0,0100 $ / 24 h (Wektory 0,0100) · ~0,30 $/mies." in out


def test_openrouter_unmapped_alias():
    out = llm_report.build_section(_fake({
        "input_tokens": _vec(({"requested_model": "mac-nieznany", "api_provider": "ollama_chat"}, 500.0)),
        "output_tokens": [],
    }), _prices)
    assert "(bez cennika: mac-nieznany 500 tok.)" in out
    assert "Gdyby przez OpenRouter: ~0,0000 $ / 24 h · ~0,00 $/mies." in out


def test_openrouter_prices_fail():
    def boom():
        raise RuntimeError("net")
    out = llm_report.build_section(_fake(), boom)
    assert "Gdyby przez OpenRouter: brak cennika" in out
    assert "Koszt: 0,0012 $" in out


def test_openrouter_no_mac_traffic():
    out = llm_report.build_section(_fake({
        "input_tokens": _vec(({"requested_model": "rag-chat", "api_provider": "openrouter"}, 100.0)),
        "output_tokens": [],
    }), _prices)
    assert "Gdyby przez OpenRouter" not in out
