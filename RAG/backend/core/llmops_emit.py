def emit_llmops_calls(call_records: list[dict]) -> None:
    """Wyslij metadane wywolan do centralnej telemetrii. Nigdy nie podnosi wyjatku."""
    for rec in call_records:
        try:
            from core import llmops_client
            llmops_client.record(
                provider=rec["provider"],
                model=rec["model"],
                call_type=rec["call_type"],
                tokens_in=rec["tokens_in"],
                tokens_out=rec["tokens_out"],
                latency_ms=rec.get("latency_ms"),
                ok=True,
            )
        except Exception:
            continue
