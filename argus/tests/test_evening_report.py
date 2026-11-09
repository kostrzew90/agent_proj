from datetime import datetime, timezone
from unittest.mock import patch

from argus import evening_report


def _utc(d, h, m=5):
    return datetime(2026, 11, d, h, m, tzinfo=timezone.utc)


def test_sends_once_per_day_with_both_sections(session):
    with patch("argus.evening_report.send_message") as send, \
         patch("argus.evening_report.llm_report.build_section", return_value="SEKCJA-LLM"):
        # 20:30 Warsaw = 19:30 UTC
        assert evening_report.maybe_send_evening_report(session, _utc(2, 19, 30)) is False
        send.assert_not_called()
        # 21:05 Warsaw = 20:05 UTC
        assert evening_report.maybe_send_evening_report(session, _utc(2, 20)) is True
        text = send.call_args[0][0]
        assert "💰 Wirtualne konto" in text and "SEKCJA-LLM" in text
        assert evening_report.maybe_send_evening_report(session, _utc(2, 21)) is False
        assert send.call_count == 1
        assert evening_report.maybe_send_evening_report(session, _utc(3, 20)) is True
        assert send.call_count == 2


def test_still_sends_when_llm_section_raises(session):
    with patch("argus.evening_report.send_message") as send, \
         patch("argus.evening_report.llm_report.build_section", side_effect=RuntimeError("x")):
        assert evening_report.maybe_send_evening_report(session, _utc(2, 20)) is True
        text = send.call_args[0][0]
        assert "💰 Wirtualne konto" in text and "LLM: błąd sekcji" in text


def test_straznik_section_fresh_file(tmp_path):
    import os
    f = tmp_path / "section.txt"
    f.write_text("🛡️ Bezpieczeństwo: wszystko OK", encoding="utf-8")
    now = datetime(2026, 11, 9, 20, 0, tzinfo=timezone.utc)
    os.utime(f, (now.timestamp() - 3600, now.timestamp() - 3600))
    assert evening_report.straznik_section(str(f), now) == "🛡️ Bezpieczeństwo: wszystko OK"


def test_straznik_section_missing_or_stale(tmp_path):
    import os
    brak = "🛡️ Bezpieczeństwo: brak danych ze Strażnika"
    now = datetime(2026, 11, 9, 20, 0, tzinfo=timezone.utc)
    assert evening_report.straznik_section(str(tmp_path / "nie-ma.txt"), now) == brak
    f = tmp_path / "section.txt"
    f.write_text("stare", encoding="utf-8")
    old = now.timestamp() - 27 * 3600
    os.utime(f, (old, old))
    assert evening_report.straznik_section(str(f), now) == brak


def test_evening_report_has_three_sections(session):
    with patch("argus.evening_report.send_message") as send, \
         patch("argus.evening_report.llm_report.build_section", return_value="SEKCJA-LLM"), \
         patch("argus.evening_report.straznik_section", return_value="SEKCJA-STRAZNIK"):
        assert evening_report.maybe_send_evening_report(session, _utc(2, 20)) is True
        text = send.call_args[0][0]
        assert "SEKCJA-LLM" in text and text.endswith("SEKCJA-STRAZNIK")
