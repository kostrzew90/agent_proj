import logging
import os
from datetime import datetime, timezone

from argus import llm_report, paper
from argus.telegram import send_message

logger = logging.getLogger(__name__)


STRAZNIK_BRAK = "🛡️ Bezpieczeństwo: brak danych ze Strażnika"
STRAZNIK_MAX_AGE_S = 26 * 3600


def straznik_section(path="/straznik/section.txt", now=None) -> str:
    now = now or datetime.now(timezone.utc)
    try:
        if now.timestamp() - os.path.getmtime(path) > STRAZNIK_MAX_AGE_S:
            return STRAZNIK_BRAK
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return STRAZNIK_BRAK


def maybe_send_evening_report(session, now) -> bool:
    acc = paper.get_account(session, now)
    local = paper._warsaw(now)
    if local.hour < paper.REPORT_HOUR or acc.last_report_date == local.date().isoformat():
        return False
    sections = []
    for name, fn in (
        ("Wirtualne konto", lambda: paper.build_report(session, now)),
        ("LLM", llm_report.build_section),
        ("Strażnik", lambda: straznik_section(now=now)),
    ):
        try:
            sections.append(fn())
        except Exception as e:
            logger.warning("evening_report: sekcja %s nie powiodła się: %s", name, e)
            sections.append(f"{name}: błąd sekcji")
    send_message("\n\n".join(sections))
    acc.last_report_date = local.date().isoformat()
    session.commit()
    return True
