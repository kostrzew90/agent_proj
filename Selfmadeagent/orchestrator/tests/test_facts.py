import pytest
from agent.facts import Facts, load_facts

SAMPLE_FACTS_MD = """# FAKTY
- projekt używa FastAPI + PostgreSQL
- testy w pytest

# OGRANICZENIA
- nie zgaduj ścieżek plików
- nie usuwaj plików bez potwierdzenia

# INWARIANTY
- nie modyfikuj plików poza workspace/
- nie uruchamiaj rm -rf
"""


def test_parse_facts():
    facts = Facts.parse(SAMPLE_FACTS_MD)
    assert len(facts.fakty) == 2
    assert len(facts.ograniczenia) == 2
    assert len(facts.inwarianty) == 2
    assert "FastAPI" in facts.fakty[0]


def test_parse_empty():
    facts = Facts.parse("")
    assert facts.fakty == []
    assert facts.ograniczenia == []
    assert facts.inwarianty == []


def test_to_prompt():
    facts = Facts.parse(SAMPLE_FACTS_MD)
    prompt = facts.to_prompt()
    assert "FAKTY" in prompt
    assert "OGRANICZENIA" in prompt
    assert "INWARIANTY" in prompt


def test_load_facts_missing_file(tmp_path):
    facts = load_facts(str(tmp_path))
    assert facts is None


def test_load_facts_exists(tmp_path):
    f = tmp_path / "FACTS.md"
    f.write_text(SAMPLE_FACTS_MD)
    facts = load_facts(str(tmp_path))
    assert facts is not None
    assert len(facts.inwarianty) == 2
