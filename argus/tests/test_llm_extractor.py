import pytest
from unittest.mock import patch
from argus.models import Asset
import argus.llm.extractor as ex

ASSETS = [Asset(symbol="BTC", kind="crypto"), Asset(symbol="NFE", kind="stock")]

def test_valid_json_yields_fixed_confidence():
    raw = '[{"asset":"BTC","direction":"bull","reasoning":"Fed dovish -> risk on"}]'
    with patch.object(ex, "call_llm", return_value=raw):
        out = ex.extract_claims_llm("Fed signals cuts", ASSETS)
    assert len(out) == 1
    assert out[0].asset_symbol == "BTC" and out[0].direction == "bull"
    assert out[0].confidence == ex.LLM_DEFAULT_CONFIDENCE == 0.35
    assert "Fed" in out[0].reasoning

def test_hallucinated_ticker_rejected():
    raw = '[{"asset":"DOGE","direction":"bull","reasoning":"x"}]'
    with patch.object(ex, "call_llm", return_value=raw):
        assert ex.extract_claims_llm("doge to moon", ASSETS) == []

def test_markdown_fenced_json_parsed():
    raw = '```json\n[{"asset":"NFE","direction":"bear","reasoning":"gas glut"}]\n```'
    with patch.object(ex, "call_llm", return_value=raw):
        out = ex.extract_claims_llm("natural gas glut", ASSETS)
    assert out[0].asset_symbol == "NFE" and out[0].direction == "bear"

def test_bad_json_returns_empty():
    with patch.object(ex, "call_llm", return_value="sorry, no idea"):
        assert ex.extract_claims_llm("noise", ASSETS) == []

def test_llm_error_propagates():
    # błąd LLM (429, circuit open) ma się propagować, by caller nie cache'ował porażki
    with patch.object(ex, "call_llm", side_effect=RuntimeError("down")):
        with pytest.raises(RuntimeError):
            ex.extract_claims_llm("x", ASSETS)

def test_neutral_direction_rejected():
    raw = '[{"asset":"BTC","direction":"neutral","reasoning":"no direct link"}]'
    with patch.object(ex, "call_llm", return_value=raw):
        assert ex.extract_claims_llm("noise", ASSETS) == []
