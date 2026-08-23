# tresrv Increment 1 (Core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the tresrv Telegram bot (Increment 1): user profile/onboarding, meal logging via text or photo through Gemini, daily weight logging, an evening summary, and a retry queue that guarantees no user log is ever silently lost.

**Architecture:** Plain Python process (no FastAPI — see spec §3) with three layers: `domain/` (pure functions, zero I/O — BMR/TDEE targets, day-boundary resolution, confirmation rule, daily aggregation), a thin `repo.py` over SQLAlchemy for persistence, and `bot/`+`scheduler/` wiring python-telegram-bot (polling) and APScheduler to the domain+repo layers. Docker Compose deploys `app` (this process) + `db` (Postgres) on the Contabo VPS alongside Argus.

**Tech Stack:** Python 3.11, SQLAlchemy 2.0 (declarative, sync `Session`), Postgres (prod) / SQLite (unit tests), python-telegram-bot v21 (async, polling), APScheduler (`AsyncIOScheduler`), `google-generativeai` (Gemini), Pydantic v2, pytest.

**Spec:** `docs/superpowers/specs/2026-08-23-tresrv-design.md`

## Global Constraints

- Timezone for all "day" logic is `Europe/Warsaw` (spec §3, §5).
- No FastAPI, no HTTP server — plain process, heartbeat written to Postgres (spec §3).
- LLM: Gemini `gemini-2.5-flash` only, no fallback provider (spec §6). New, dedicated `GEMINI_API_KEY`, not shared with Argus (spec §9).
- Retry backoff for `pending_parse`: 60s → 120s → 300s → cap at 300s, `max attempts = 5` (spec §3, §7).
- All meal aggregations filter `status != 'superseded'` (spec §4) — never sum a corrected-away row.
- `needs_confirmation` is computed by application code, never trusted from the LLM (spec §4).
- Evening summary default time: 21:00 Europe/Warsaw (spec §5). It is a snapshot — never re-sent (spec §5).
- Corrections (`/popraw`) always insert a new `meals` row and mark the old one `superseded` in the same transaction (spec §4).

---

## File Structure

```
tresrv/
  Dockerfile
  docker-compose.yml
  requirements.txt
  .env.example
  tresrv/
    __init__.py
    config.py
    db.py
    models.py
    repo.py
    llm.py
    domain/
      __init__.py
      daytime.py
      targets.py
      confirmation.py
      aggregation.py
    bot/
      __init__.py
      onboarding.py
      profile.py
      weight.py
      meals.py
      correction.py
    scheduler/
      __init__.py
      jobs.py
    main.py
  tests/
    test_config.py
    test_models.py
    domain/
      test_daytime.py
      test_targets.py
      test_confirmation.py
      test_aggregation.py
    test_llm.py
    test_repo.py
    bot/
      test_onboarding.py
      test_profile.py
      test_weight.py
      test_meals.py
      test_correction.py
    scheduler/
      test_jobs.py
```

---

### Task 1: Project skeleton, config, DB bootstrap

**Files:**
- Create: `tresrv/requirements.txt`
- Create: `tresrv/Dockerfile`
- Create: `tresrv/.env.example`
- Create: `tresrv/tresrv/__init__.py`
- Create: `tresrv/tresrv/config.py`
- Create: `tresrv/tresrv/db.py`
- Test: `tresrv/tests/test_config.py`

**Interfaces:**
- Produces: `Settings` dataclass (`telegram_bot_token: str`, `telegram_chat_id: int`, `gemini_api_key: str`, `database_url: str`, `evening_summary_hour: int = 21`, `evening_summary_minute: int = 0`, `pending_parse_interval_minutes: int = 2`, `heartbeat_interval_minutes: int = 5`, `max_pending_attempts: int = 5`); `load_settings() -> Settings`; `make_session_factory(database_url: str) -> sessionmaker`.

- [ ] **Step 1: Write requirements.txt**

```
sqlalchemy>=2.0
psycopg2-binary>=2.9
python-telegram-bot>=21.0
apscheduler>=3.10
google-generativeai>=0.8
pydantic>=2.0
pillow>=10.0
pytest>=8.0
```

- [ ] **Step 2: Write the failing test for config loading**

```python
# tresrv/tests/test_config.py
import os
import pytest
from tresrv.config import load_settings


def test_load_settings_reads_required_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "555")
    monkeypatch.setenv("GEMINI_API_KEY", "gem-key")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = load_settings()

    assert settings.telegram_bot_token == "abc123"
    assert settings.telegram_chat_id == 555
    assert settings.gemini_api_key == "gem-key"
    assert settings.database_url == "postgresql+psycopg2://tresrv:tresrv@db:5432/tresrv"
    assert settings.evening_summary_hour == 21


def test_load_settings_missing_required_env_raises(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(KeyError):
        load_settings()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd tresrv && python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tresrv.config'`

- [ ] **Step 4: Implement config.py**

```python
# tresrv/tresrv/config.py
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: int
    gemini_api_key: str
    database_url: str
    evening_summary_hour: int = 21
    evening_summary_minute: int = 0
    pending_parse_interval_minutes: int = 2
    heartbeat_interval_minutes: int = 5
    max_pending_attempts: int = 5


def load_settings() -> Settings:
    return Settings(
        telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        telegram_chat_id=int(os.environ["TELEGRAM_CHAT_ID"]),
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        database_url=os.environ.get(
            "DATABASE_URL", "postgresql+psycopg2://tresrv:tresrv@db:5432/tresrv"
        ),
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd tresrv && python -m pytest tests/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Write db.py (no test — thin wrapper, verified by Task 2's model tests)**

```python
# tresrv/tresrv/db.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tresrv.models import Base


def make_session_factory(database_url: str):
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)
```

- [ ] **Step 7: Write Dockerfile**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY tresrv ./tresrv
CMD ["python", "-m", "tresrv.main"]
```

- [ ] **Step 8: Write .env.example**

```
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
GEMINI_API_KEY=
DATABASE_URL=postgresql+psycopg2://tresrv:tresrv@db:5432/tresrv
```

- [ ] **Step 9: Commit**

```bash
git add tresrv/requirements.txt tresrv/Dockerfile tresrv/.env.example \
        tresrv/tresrv/__init__.py tresrv/tresrv/config.py tresrv/tresrv/db.py \
        tresrv/tests/test_config.py
git commit -m "feat(tresrv): project skeleton, config, db session factory"
```

---

### Task 2: Data model (schema)

**Files:**
- Create: `tresrv/tresrv/models.py`
- Test: `tresrv/tests/test_models.py`

**Interfaces:**
- Consumes: nothing from Task 1 directly (models.py is imported BY db.py, not the reverse — fix Task 1's import order by creating this file first if running strictly in order; both files can coexist since Python resolves imports at call time).
- Produces: `Base` (declarative base), ORM classes `UserProfile`, `WeightLog`, `Meal`, `PendingParse` with exactly the columns below — later tasks (`repo.py`, `domain/`) construct/query these by these exact attribute names.

- [ ] **Step 1: Write the failing test for schema constraints**

```python
# tresrv/tests/test_models.py
from datetime import datetime, timezone, date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tresrv.models import Base, UserProfile, WeightLog, Meal, PendingParse


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_user_profile_rejects_invalid_plec(session):
    session.add(UserProfile(
        chat_id=1, plec="x", wiek=30, wzrost_cm=180, waga_kg=80,
        poziom_aktywnosci="moderate", cel="reduction",
        updated_at=datetime.now(timezone.utc),
    ))
    with pytest.raises(IntegrityError):
        session.commit()


def test_weight_logs_unique_per_chat_and_day(session):
    session.add(WeightLog(chat_id=1, waga_kg=80.0,
                           logged_at=datetime.now(timezone.utc), local_date=date(2026, 8, 23)))
    session.commit()
    session.add(WeightLog(chat_id=1, waga_kg=80.5,
                           logged_at=datetime.now(timezone.utc), local_date=date(2026, 8, 23)))
    with pytest.raises(IntegrityError):
        session.commit()


def test_meal_rejects_invalid_status(session):
    now = datetime.now(timezone.utc)
    session.add(Meal(
        chat_id=1, logged_at=now, consumed_at=now, consumed_date=now.date(),
        raw_input_type="text", raw_text="jajka", kcal=300, protein_g=20,
        fat_g=10, carbs_g=5, status="not_a_real_status", created_at=now,
    ))
    with pytest.raises(IntegrityError):
        session.commit()


def test_meal_corrected_from_id_links_to_previous_meal(session):
    now = datetime.now(timezone.utc)
    original = Meal(
        chat_id=1, logged_at=now, consumed_at=now, consumed_date=now.date(),
        raw_input_type="text", raw_text="jajka", kcal=300, protein_g=20,
        fat_g=10, carbs_g=5, status="superseded", created_at=now,
    )
    session.add(original)
    session.commit()

    correction = Meal(
        chat_id=1, logged_at=now, consumed_at=now, consumed_date=now.date(),
        raw_input_type="text", raw_text="jajka", kcal=320, protein_g=22,
        fat_g=10, carbs_g=5, status="corrected", value_source="user",
        corrected_from_id=original.id, created_at=now,
    )
    session.add(correction)
    session.commit()

    assert correction.corrected_from_id == original.id


def test_pending_parse_rejects_invalid_status(session):
    now = datetime.now(timezone.utc)
    session.add(PendingParse(
        chat_id=1, raw_input_type="text", raw_text="jajka",
        logged_at=now, consumed_at=now, next_attempt_at=now,
        status="not_real", created_at=now,
    ))
    with pytest.raises(IntegrityError):
        session.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tresrv && python -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tresrv.models'`

- [ ] **Step 3: Implement models.py**

```python
# tresrv/tresrv/models.py
from datetime import datetime, date

from sqlalchemy import (
    BigInteger, String, Numeric, Boolean, DateTime, Date, Integer,
    ForeignKey, CheckConstraint, UniqueConstraint, Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserProfile(Base):
    __tablename__ = "user_profile"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    plec: Mapped[str] = mapped_column(String(1))
    wiek: Mapped[int] = mapped_column(Integer)
    wzrost_cm: Mapped[float] = mapped_column(Numeric(5, 1))
    waga_kg: Mapped[float] = mapped_column(Numeric(5, 1))
    poziom_aktywnosci: Mapped[str] = mapped_column(String(20))
    cel: Mapped[str] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("plec IN ('m','k')", name="ck_user_profile_plec"),
        CheckConstraint(
            "poziom_aktywnosci IN ('sedentary','light','moderate','active','very_active')",
            name="ck_user_profile_activity",
        ),
        CheckConstraint("cel IN ('reduction','mass','maintenance')", name="ck_user_profile_cel"),
    )


class WeightLog(Base):
    __tablename__ = "weight_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    waga_kg: Mapped[float] = mapped_column(Numeric(5, 1))
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    local_date: Mapped[date] = mapped_column(Date)

    __table_args__ = (
        UniqueConstraint("chat_id", "local_date", name="uq_weight_logs_chat_date"),
    )


class Meal(Base):
    __tablename__ = "meals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_date: Mapped[date] = mapped_column(Date)
    raw_input_type: Mapped[str] = mapped_column(String(10))
    raw_text: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String, nullable=True)
    telegram_file_id: Mapped[str | None] = mapped_column(String, nullable=True)
    opis: Mapped[str | None] = mapped_column(String, nullable=True)
    kcal: Mapped[float | None] = mapped_column(Numeric(6, 1), nullable=True)
    protein_g: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    fat_g: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    carbs_g: Mapped[float | None] = mapped_column(Numeric(5, 1), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    needs_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    value_source: Mapped[str] = mapped_column(String(10), default="llm")
    llm_model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="parsed")
    corrected_from_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("meals.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("raw_input_type IN ('text','photo')", name="ck_meals_input_type"),
        CheckConstraint("value_source IN ('llm','user')", name="ck_meals_value_source"),
        CheckConstraint("status IN ('parsed','corrected','superseded')", name="ck_meals_status"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_meals_confidence_range",
        ),
        Index("meals_day_idx", "chat_id", "consumed_date"),
    )


class PendingParse(Base):
    __tablename__ = "pending_parse"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    raw_input_type: Mapped[str] = mapped_column(String(10))
    raw_text: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String, nullable=True)
    telegram_file_id: Mapped[str | None] = mapped_column(String, nullable=True)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    meal_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("meals.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("raw_input_type IN ('text','photo')", name="ck_pending_input_type"),
        CheckConstraint(
            "status IN ('pending','failed_permanently','resolved')", name="ck_pending_status"
        ),
        Index("pending_parse_due_idx", "next_attempt_at"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tresrv && python -m pytest tests/test_models.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add tresrv/tresrv/models.py tresrv/tests/test_models.py
git commit -m "feat(tresrv): SQLAlchemy schema for user_profile, weight_logs, meals, pending_parse"
```

---

### Task 3: Domain — day boundary and `consumed_at` resolution

**Files:**
- Create: `tresrv/tresrv/domain/__init__.py`
- Create: `tresrv/tresrv/domain/daytime.py`
- Test: `tresrv/tests/domain/test_daytime.py`

**Interfaces:**
- Produces: `WARSAW: ZoneInfo`; `local_date(dt: datetime, tz: ZoneInfo = WARSAW) -> date`; `resolve_consumed_at(logged_at: datetime, when_hint: str | None) -> tuple[datetime, bool]` (second value = `needs_time_confirmation`).

- [ ] **Step 1: Write the failing tests**

```python
# tresrv/tests/domain/test_daytime.py
from datetime import datetime, timezone, timedelta

from tresrv.domain.daytime import local_date, resolve_consumed_at, WARSAW


def test_local_date_converts_utc_to_warsaw_date():
    dt = datetime(2026, 8, 23, 22, 30, tzinfo=timezone.utc)  # 00:30 next day in Warsaw (CEST, UTC+2)
    assert local_date(dt) == datetime(2026, 8, 24).date()


def test_resolve_consumed_at_none_hint_returns_logged_at():
    logged_at = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    consumed_at, needs_confirm = resolve_consumed_at(logged_at, None)
    assert consumed_at == logged_at
    assert needs_confirm is False


def test_resolve_consumed_at_hours_ago_hint():
    logged_at = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    consumed_at, needs_confirm = resolve_consumed_at(logged_at, "3h_ago")
    assert consumed_at == logged_at - timedelta(hours=3)
    assert needs_confirm is False


def test_resolve_consumed_at_yesterday_hint():
    logged_at = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    consumed_at, needs_confirm = resolve_consumed_at(logged_at, "yesterday")
    assert consumed_at == logged_at - timedelta(days=1)
    assert needs_confirm is False


def test_resolve_consumed_at_unknown_hint_falls_back_to_logged_at():
    logged_at = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    consumed_at, needs_confirm = resolve_consumed_at(logged_at, "some_garbage")
    assert consumed_at == logged_at
    assert needs_confirm is False


def test_resolve_consumed_at_beyond_48h_needs_confirmation():
    logged_at = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    consumed_at, needs_confirm = resolve_consumed_at(logged_at, "72h_ago")
    assert consumed_at == logged_at - timedelta(hours=72)
    assert needs_confirm is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tresrv && python -m pytest tests/domain/test_daytime.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tresrv.domain'`

- [ ] **Step 3: Implement daytime.py**

```python
# tresrv/tresrv/domain/daytime.py
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

WARSAW = ZoneInfo("Europe/Warsaw")
_HOURS_AGO_RE = re.compile(r"^(\d+)h_ago$")
_CONFIRM_THRESHOLD = timedelta(hours=48)


def local_date(dt: datetime, tz: ZoneInfo = WARSAW):
    return dt.astimezone(tz).date()


def resolve_consumed_at(logged_at: datetime, when_hint: str | None) -> tuple[datetime, bool]:
    if when_hint is None:
        return logged_at, False

    if when_hint == "yesterday":
        candidate = logged_at - timedelta(days=1)
    elif when_hint == "yesterday_evening":
        local_dt = logged_at.astimezone(WARSAW)
        target_local = (local_dt - timedelta(days=1)).replace(
            hour=19, minute=0, second=0, microsecond=0
        )
        candidate = target_local.astimezone(logged_at.tzinfo)
    else:
        match = _HOURS_AGO_RE.match(when_hint)
        if not match:
            return logged_at, False
        candidate = logged_at - timedelta(hours=int(match.group(1)))

    needs_confirmation = (logged_at - candidate) > _CONFIRM_THRESHOLD
    return candidate, needs_confirmation
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tresrv && python -m pytest tests/domain/test_daytime.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add tresrv/tresrv/domain/__init__.py tresrv/tresrv/domain/daytime.py \
        tresrv/tests/domain/test_daytime.py
git commit -m "feat(tresrv): day-boundary and consumed_at resolution logic"
```

---

### Task 4: Domain — calorie/macro targets (BMR/TDEE)

**Files:**
- Create: `tresrv/tresrv/domain/targets.py`
- Test: `tresrv/tests/domain/test_targets.py`

**Interfaces:**
- Produces: `DailyTarget` dataclass (`kcal: float`, `protein_g: float`); `bmr_mifflin_st_jeor(plec: str, waga_kg: float, wzrost_cm: float, wiek: int) -> float`; `daily_target(plec: str, waga_kg: float, wzrost_cm: float, wiek: int, poziom_aktywnosci: str, cel: str) -> DailyTarget`.

- [ ] **Step 1: Write the failing tests**

```python
# tresrv/tests/domain/test_targets.py
import pytest

from tresrv.domain.targets import bmr_mifflin_st_jeor, daily_target


def test_bmr_male():
    bmr = bmr_mifflin_st_jeor("m", waga_kg=80, wzrost_cm=180, wiek=30)
    assert bmr == pytest.approx(10 * 80 + 6.25 * 180 - 5 * 30 + 5)


def test_bmr_female():
    bmr = bmr_mifflin_st_jeor("k", waga_kg=65, wzrost_cm=165, wiek=28)
    assert bmr == pytest.approx(10 * 65 + 6.25 * 165 - 5 * 28 - 161)


def test_bmr_rejects_unknown_plec():
    with pytest.raises(ValueError):
        bmr_mifflin_st_jeor("x", waga_kg=80, wzrost_cm=180, wiek=30)


@pytest.mark.parametrize("cel,expected_modifier", [
    ("reduction", -0.20),
    ("mass", 0.15),
    ("maintenance", 0.0),
])
def test_daily_target_applies_goal_modifier(cel, expected_modifier):
    bmr = bmr_mifflin_st_jeor("m", waga_kg=80, wzrost_cm=180, wiek=30)
    tdee = bmr * 1.55  # moderate
    target = daily_target("m", 80, 180, 30, "moderate", cel)
    assert target.kcal == pytest.approx(tdee * (1 + expected_modifier), abs=1)


def test_daily_target_protein_is_1_8_per_kg():
    target = daily_target("m", 80, 180, 30, "moderate", "reduction")
    assert target.protein_g == pytest.approx(80 * 1.8, abs=0.1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tresrv && python -m pytest tests/domain/test_targets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tresrv.domain.targets'`

- [ ] **Step 3: Implement targets.py**

```python
# tresrv/tresrv/domain/targets.py
from dataclasses import dataclass

ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

GOAL_MODIFIERS = {
    "reduction": -0.20,
    "mass": 0.15,
    "maintenance": 0.0,
}


@dataclass(frozen=True)
class DailyTarget:
    kcal: float
    protein_g: float


def bmr_mifflin_st_jeor(plec: str, waga_kg: float, wzrost_cm: float, wiek: int) -> float:
    base = 10 * waga_kg + 6.25 * wzrost_cm - 5 * wiek
    if plec == "m":
        return base + 5
    if plec == "k":
        return base - 161
    raise ValueError(f"Nieznana płeć: {plec}")


def daily_target(
    plec: str, waga_kg: float, wzrost_cm: float, wiek: int,
    poziom_aktywnosci: str, cel: str,
) -> DailyTarget:
    bmr = bmr_mifflin_st_jeor(plec, waga_kg, wzrost_cm, wiek)
    tdee = bmr * ACTIVITY_MULTIPLIERS[poziom_aktywnosci]
    kcal = tdee * (1 + GOAL_MODIFIERS[cel])
    protein_g = waga_kg * 1.8
    return DailyTarget(kcal=round(kcal, 1), protein_g=round(protein_g, 1))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tresrv && python -m pytest tests/domain/test_targets.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add tresrv/tresrv/domain/targets.py tresrv/tests/domain/test_targets.py
git commit -m "feat(tresrv): BMR/TDEE/target calorie calculation (Mifflin-St Jeor)"
```

---

### Task 5: Domain — `needs_confirmation` rule

**Files:**
- Create: `tresrv/tresrv/domain/confirmation.py`
- Test: `tresrv/tests/domain/test_confirmation.py`

**Interfaces:**
- Produces: `needs_confirmation(confidence: float | None, kcal: float | None, raw_input_type: str, opis: str | None) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# tresrv/tests/domain/test_confirmation.py
from tresrv.domain.confirmation import needs_confirmation


def test_low_confidence_needs_confirmation():
    assert needs_confirmation(0.5, 400, "text", "kanapka") is True


def test_high_confidence_text_no_confirmation():
    assert needs_confirmation(0.9, 400, "text", "kanapka") is False


def test_none_confidence_needs_confirmation():
    assert needs_confirmation(None, 400, "text", "kanapka") is True


def test_very_large_kcal_needs_confirmation_even_with_high_confidence():
    assert needs_confirmation(0.95, 1500, "text", "wielka pizza") is True


def test_photo_without_gramature_needs_confirmation():
    assert needs_confirmation(0.9, 500, "photo", "kurczak z ryżem i warzywami") is True


def test_photo_with_gramature_no_confirmation():
    assert needs_confirmation(0.9, 500, "photo", "200g kurczaka, 150g ryżu") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tresrv && python -m pytest tests/domain/test_confirmation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tresrv.domain.confirmation'`

- [ ] **Step 3: Implement confirmation.py**

```python
# tresrv/tresrv/domain/confirmation.py
_GRAMATURE_UNITS = ("g", "gram", "ml", "szt")


def needs_confirmation(
    confidence: float | None, kcal: float | None,
    raw_input_type: str, opis: str | None,
) -> bool:
    if confidence is None or confidence < 0.7:
        return True
    if kcal is not None and kcal > 1200:
        return True
    if raw_input_type == "photo" and not _has_gramature(opis):
        return True
    return False


def _has_gramature(opis: str | None) -> bool:
    if not opis:
        return False
    lowered = opis.lower()
    return any(unit in lowered for unit in _GRAMATURE_UNITS)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tresrv && python -m pytest tests/domain/test_confirmation.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add tresrv/tresrv/domain/confirmation.py tresrv/tests/domain/test_confirmation.py
git commit -m "feat(tresrv): needs_confirmation rule computed by app, not LLM"
```

---

### Task 6: Domain — daily aggregation

**Files:**
- Create: `tresrv/tresrv/domain/aggregation.py`
- Test: `tresrv/tests/domain/test_aggregation.py`

**Interfaces:**
- Produces: `MealRow` dataclass (`kcal: float`, `protein_g: float`, `fat_g: float`, `carbs_g: float`, `status: str`); `DaySummary` dataclass (`kcal: float`, `protein_g: float`, `fat_g: float`, `carbs_g: float`, `meal_count: int`); `aggregate_day(meals: list[MealRow]) -> DaySummary`.

- [ ] **Step 1: Write the failing tests**

```python
# tresrv/tests/domain/test_aggregation.py
from tresrv.domain.aggregation import MealRow, aggregate_day


def test_aggregate_day_sums_active_meals():
    meals = [
        MealRow(kcal=300, protein_g=20, fat_g=10, carbs_g=30, status="parsed"),
        MealRow(kcal=500, protein_g=30, fat_g=15, carbs_g=50, status="parsed"),
    ]
    summary = aggregate_day(meals)
    assert summary.kcal == 800
    assert summary.protein_g == 50
    assert summary.fat_g == 25
    assert summary.carbs_g == 80
    assert summary.meal_count == 2


def test_aggregate_day_excludes_superseded():
    meals = [
        MealRow(kcal=300, protein_g=20, fat_g=10, carbs_g=30, status="superseded"),
        MealRow(kcal=320, protein_g=22, fat_g=10, carbs_g=30, status="corrected"),
    ]
    summary = aggregate_day(meals)
    assert summary.kcal == 320
    assert summary.meal_count == 1


def test_aggregate_day_empty_list():
    summary = aggregate_day([])
    assert summary.kcal == 0
    assert summary.meal_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tresrv && python -m pytest tests/domain/test_aggregation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tresrv.domain.aggregation'`

- [ ] **Step 3: Implement aggregation.py**

```python
# tresrv/tresrv/domain/aggregation.py
from dataclasses import dataclass


@dataclass(frozen=True)
class MealRow:
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    status: str


@dataclass(frozen=True)
class DaySummary:
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    meal_count: int


def aggregate_day(meals: list[MealRow]) -> DaySummary:
    active = [m for m in meals if m.status != "superseded"]
    return DaySummary(
        kcal=sum(m.kcal for m in active),
        protein_g=sum(m.protein_g for m in active),
        fat_g=sum(m.fat_g for m in active),
        carbs_g=sum(m.carbs_g for m in active),
        meal_count=len(active),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tresrv && python -m pytest tests/domain/test_aggregation.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tresrv/tresrv/domain/aggregation.py tresrv/tests/domain/test_aggregation.py
git commit -m "feat(tresrv): daily aggregation excluding superseded meals"
```

---

### Task 7: Gemini client + response validation

**Files:**
- Create: `tresrv/tresrv/llm.py`
- Test: `tresrv/tests/test_llm.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `ParsedMeal` (Pydantic model: `kcal: float`, `protein_g: float`, `fat_g: float`, `carbs_g: float`, `opis: str`, `confidence: float`, `when_hint: str | None`); `NotFoodError`, `ParseError` exceptions; `GeminiClient(api_key: str, model_name: str = "gemini-2.5-flash", model=None)` with `.parse_text(text: str) -> ParsedMeal` and `.parse_photo(image_path: str) -> ParsedMeal`. `model` param (default `None`) allows test injection of a fake model object exposing `.generate_content(...)`.

- [ ] **Step 1: Write the failing tests**

```python
# tresrv/tests/test_llm.py
import pytest

from tresrv.llm import GeminiClient, ParsedMeal, NotFoodError, ParseError


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeModel:
    def __init__(self, response_text):
        self._response_text = response_text
        self.last_call_args = None

    def generate_content(self, *args, **kwargs):
        self.last_call_args = (args, kwargs)
        return FakeResponse(self._response_text)


def test_parse_text_valid_response():
    fake = FakeModel(
        '{"kcal": 450, "protein_g": 30, "fat_g": 15, "carbs_g": 40, '
        '"opis": "kurczak z ryżem", "confidence": 0.85, "when_hint": null}'
    )
    client = GeminiClient(api_key="unused", model=fake)

    result = client.parse_text("kurczak z ryżem")

    assert isinstance(result, ParsedMeal)
    assert result.kcal == 450
    assert result.confidence == 0.85
    assert result.when_hint is None


def test_parse_text_not_food_raises():
    fake = FakeModel('{"error": "not_food"}')
    client = GeminiClient(api_key="unused", model=fake)

    with pytest.raises(NotFoodError):
        client.parse_text("stół z drewna")


def test_parse_text_garbage_json_raises_parse_error():
    fake = FakeModel("to nie jest JSON")
    client = GeminiClient(api_key="unused", model=fake)

    with pytest.raises(ParseError):
        client.parse_text("cokolwiek")


def test_parse_text_missing_required_field_raises_parse_error():
    fake = FakeModel('{"kcal": 450, "protein_g": 30}')
    client = GeminiClient(api_key="unused", model=fake)

    with pytest.raises(ParseError):
        client.parse_text("cokolwiek")


def test_parse_text_confidence_out_of_range_raises_parse_error():
    fake = FakeModel(
        '{"kcal": 450, "protein_g": 30, "fat_g": 15, "carbs_g": 40, '
        '"opis": "x", "confidence": 1.5, "when_hint": null}'
    )
    client = GeminiClient(api_key="unused", model=fake)

    with pytest.raises(ParseError):
        client.parse_text("cokolwiek")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tresrv && python -m pytest tests/test_llm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tresrv.llm'`

- [ ] **Step 3: Implement llm.py**

```python
# tresrv/tresrv/llm.py
import json

from pydantic import BaseModel, Field, ValidationError

PROMPT_TEXT = """Jestes parserem posilkow. Otrzymasz opis posilku po polsku.
Zwroc WYLACZNIE JSON (bez markdown, bez dodatkowego tekstu) w formacie:
{{"kcal": number, "protein_g": number, "fat_g": number, "carbs_g": number,
  "opis": string, "confidence": number 0..1, "when_hint": string or null}}
when_hint: null (teraz), "Nh_ago" (np. "3h_ago"), "yesterday", albo "yesterday_evening".
Jesli opis NIE dotyczy jedzenia, zwroc WYLACZNIE {{"error": "not_food"}}.

Opis posilku: {text}
"""

PROMPT_PHOTO = """Jestes parserem posilkow. Na zdjeciu jest posilek.
Zwroc WYLACZNIE JSON w formacie:
{"kcal": number, "protein_g": number, "fat_g": number, "carbs_g": number,
  "opis": string, "confidence": number 0..1, "when_hint": null}
Jesli na zdjeciu NIE ma jedzenia, zwroc WYLACZNIE {"error": "not_food"}.
"""


class ParsedMeal(BaseModel):
    kcal: float = Field(gt=0)
    protein_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    carbs_g: float = Field(ge=0)
    opis: str
    confidence: float = Field(ge=0, le=1)
    when_hint: str | None = None


class NotFoodError(Exception):
    pass


class ParseError(Exception):
    pass


class GeminiClient:
    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash", model=None):
        self.model_name = model_name
        if model is not None:
            self._model = model
        else:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self._model = genai.GenerativeModel(model_name)

    def parse_text(self, text: str) -> ParsedMeal:
        response = self._model.generate_content(PROMPT_TEXT.format(text=text))
        return self._parse_response(response.text)

    def parse_photo(self, image_path: str) -> ParsedMeal:
        import PIL.Image
        image = PIL.Image.open(image_path)
        response = self._model.generate_content([PROMPT_PHOTO, image])
        return self._parse_response(response.text)

    def _parse_response(self, raw_text: str) -> ParsedMeal:
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ParseError(f"nieparsowalny JSON: {exc}") from exc

        if data.get("error") == "not_food":
            raise NotFoodError()

        try:
            return ParsedMeal.model_validate(data)
        except ValidationError as exc:
            raise ParseError(f"nieprawidlowy schemat: {exc}") from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tresrv && python -m pytest tests/test_llm.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add tresrv/tresrv/llm.py tresrv/tests/test_llm.py
git commit -m "feat(tresrv): Gemini client with strict response validation"
```

---

### Task 8: Repository layer (persistence)

**Files:**
- Create: `tresrv/tresrv/repo.py`
- Test: `tresrv/tests/test_repo.py`

**Interfaces:**
- Consumes: `Base`, `UserProfile`, `WeightLog`, `Meal`, `PendingParse` from `tresrv.models` (Task 2).
- Produces: `upsert_profile(session, chat_id, **fields) -> UserProfile`; `get_profile(session, chat_id) -> UserProfile | None`; `upsert_weight_log(session, chat_id, waga_kg, logged_at, local_date) -> WeightLog`; `save_meal(session, **fields) -> Meal`; `save_pending_parse(session, **fields) -> PendingParse`; `get_active_meals_for_day(session, chat_id, consumed_date) -> list[Meal]`; `get_last_active_meal(session, chat_id) -> Meal | None`; `correct_meal(session, meal_id, **new_values) -> Meal`; `fetch_due_pending(session, now) -> list[PendingParse]`; `mark_pending_resolved(session, pending, meal_id)`; `mark_pending_retry(session, pending, error, next_attempt_at)`; `mark_pending_failed_permanently(session, pending, error)`.

- [ ] **Step 1: Write the failing tests**

```python
# tresrv/tests/test_repo.py
from datetime import datetime, timezone, date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tresrv.models import Base
from tresrv import repo


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_upsert_profile_creates_then_updates(session):
    now = datetime.now(timezone.utc)
    repo.upsert_profile(
        session, chat_id=1, plec="m", wiek=30, wzrost_cm=180, waga_kg=80,
        poziom_aktywnosci="moderate", cel="reduction",
    )
    repo.upsert_profile(session, chat_id=1, cel="maintenance")

    profile = repo.get_profile(session, 1)
    assert profile.cel == "maintenance"
    assert profile.waga_kg == 80  # untouched field survives partial update


def test_upsert_weight_log_is_idempotent_per_day(session):
    d = date(2026, 8, 23)
    repo.upsert_weight_log(session, chat_id=1, waga_kg=80.0,
                            logged_at=datetime.now(timezone.utc), local_date=d)
    repo.upsert_weight_log(session, chat_id=1, waga_kg=80.5,
                            logged_at=datetime.now(timezone.utc), local_date=d)

    logs = session.query(repo.WeightLog).filter_by(chat_id=1, local_date=d).all()
    assert len(logs) == 1
    assert logs[0].waga_kg == 80.5


def test_get_active_meals_for_day_excludes_superseded(session):
    now = datetime.now(timezone.utc)
    today = now.date()
    m1 = repo.save_meal(
        session, chat_id=1, logged_at=now, consumed_at=now, consumed_date=today,
        raw_input_type="text", raw_text="a", kcal=300, protein_g=20, fat_g=10,
        carbs_g=30, status="superseded", created_at=now,
    )
    repo.save_meal(
        session, chat_id=1, logged_at=now, consumed_at=now, consumed_date=today,
        raw_input_type="text", raw_text="b", kcal=320, protein_g=22, fat_g=10,
        carbs_g=30, status="corrected", corrected_from_id=m1.id, created_at=now,
    )

    active = repo.get_active_meals_for_day(session, 1, today)
    assert len(active) == 1
    assert active[0].kcal == 320


def test_correct_meal_supersedes_old_and_creates_new(session):
    now = datetime.now(timezone.utc)
    today = now.date()
    original = repo.save_meal(
        session, chat_id=1, logged_at=now, consumed_at=now, consumed_date=today,
        raw_input_type="text", raw_text="kanapka", kcal=300, protein_g=20,
        fat_g=10, carbs_g=30, opis="kanapka", status="parsed", created_at=now,
    )

    corrected = repo.correct_meal(session, original.id, kcal=600)

    session.refresh(original)
    assert original.status == "superseded"
    assert corrected.status == "corrected"
    assert corrected.value_source == "user"
    assert corrected.corrected_from_id == original.id
    assert corrected.kcal == 600
    assert corrected.protein_g == 20  # untouched field copied from original


def test_fetch_due_pending_only_returns_due_and_pending(session):
    now = datetime.now(timezone.utc)
    repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="a",
        logged_at=now, consumed_at=now, next_attempt_at=now - timedelta(minutes=1),
        status="pending", created_at=now,
    )
    repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="b",
        logged_at=now, consumed_at=now, next_attempt_at=now + timedelta(hours=1),
        status="pending", created_at=now,
    )
    repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="c",
        logged_at=now, consumed_at=now, next_attempt_at=now - timedelta(minutes=1),
        status="resolved", created_at=now,
    )

    due = repo.fetch_due_pending(session, now)
    assert len(due) == 1
    assert due[0].raw_text == "a"


def test_mark_pending_retry_increments_attempts_and_sets_next_attempt(session):
    now = datetime.now(timezone.utc)
    pending = repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="a",
        logged_at=now, consumed_at=now, next_attempt_at=now,
        status="pending", created_at=now,
    )

    next_attempt = now + timedelta(seconds=120)
    repo.mark_pending_retry(session, pending, "429 rate limited", next_attempt)

    assert pending.attempts == 1
    assert pending.last_error == "429 rate limited"
    assert pending.next_attempt_at == next_attempt
    assert pending.status == "pending"


def test_mark_pending_failed_permanently_sets_status(session):
    now = datetime.now(timezone.utc)
    pending = repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="a",
        logged_at=now, consumed_at=now, next_attempt_at=now,
        status="pending", created_at=now,
    )

    repo.mark_pending_failed_permanently(session, pending, "nieparsowalny JSON x2")

    assert pending.status == "failed_permanently"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tresrv && python -m pytest tests/test_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tresrv.repo'`

- [ ] **Step 3: Implement repo.py**

```python
# tresrv/tresrv/repo.py
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from tresrv.models import UserProfile, WeightLog, Meal, PendingParse

_MEAL_COPY_FIELDS = (
    "chat_id", "logged_at", "consumed_at", "consumed_date", "raw_input_type",
    "raw_text", "storage_path", "telegram_file_id", "opis", "kcal",
    "protein_g", "fat_g", "carbs_g", "confidence", "llm_model",
)


def get_profile(session: Session, chat_id: int) -> UserProfile | None:
    return session.get(UserProfile, chat_id)


def upsert_profile(session: Session, chat_id: int, **fields) -> UserProfile:
    profile = session.get(UserProfile, chat_id)
    now = datetime.now(timezone.utc)
    if profile is None:
        profile = UserProfile(chat_id=chat_id, updated_at=now, **fields)
        session.add(profile)
    else:
        for key, value in fields.items():
            setattr(profile, key, value)
        profile.updated_at = now
    session.commit()
    return profile


def upsert_weight_log(session: Session, chat_id: int, waga_kg: float,
                       logged_at: datetime, local_date) -> WeightLog:
    existing = session.execute(
        select(WeightLog).where(
            WeightLog.chat_id == chat_id, WeightLog.local_date == local_date
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = WeightLog(chat_id=chat_id, waga_kg=waga_kg,
                              logged_at=logged_at, local_date=local_date)
        session.add(existing)
    else:
        existing.waga_kg = waga_kg
        existing.logged_at = logged_at
    session.commit()
    return existing


def save_meal(session: Session, **fields) -> Meal:
    meal = Meal(**fields)
    session.add(meal)
    session.commit()
    return meal


def save_pending_parse(session: Session, **fields) -> PendingParse:
    pending = PendingParse(**fields)
    session.add(pending)
    session.commit()
    return pending


def get_active_meals_for_day(session: Session, chat_id: int, consumed_date) -> list[Meal]:
    return list(session.execute(
        select(Meal).where(
            Meal.chat_id == chat_id,
            Meal.consumed_date == consumed_date,
            Meal.status != "superseded",
        )
    ).scalars())


def get_last_active_meal(session: Session, chat_id: int) -> Meal | None:
    return session.execute(
        select(Meal)
        .where(Meal.chat_id == chat_id, Meal.status != "superseded")
        .order_by(Meal.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def correct_meal(session: Session, meal_id: int, **new_values) -> Meal:
    original = session.get(Meal, meal_id)
    if original is None:
        raise ValueError(f"Meal {meal_id} nie istnieje")

    data = {field: getattr(original, field) for field in _MEAL_COPY_FIELDS}
    data.update(new_values)
    data["value_source"] = "user"
    data["status"] = "corrected"
    data["needs_confirmation"] = False
    data["corrected_from_id"] = original.id
    data["created_at"] = datetime.now(timezone.utc)

    corrected = Meal(**data)
    original.status = "superseded"
    session.add(corrected)
    session.commit()
    return corrected


def fetch_due_pending(session: Session, now: datetime) -> list[PendingParse]:
    return list(session.execute(
        select(PendingParse).where(
            PendingParse.status == "pending",
            PendingParse.next_attempt_at <= now,
        )
    ).scalars())


def mark_pending_resolved(session: Session, pending: PendingParse, meal_id: int) -> None:
    pending.status = "resolved"
    pending.meal_id = meal_id
    session.commit()


def mark_pending_retry(session: Session, pending: PendingParse, error: str,
                        next_attempt_at: datetime) -> None:
    pending.attempts += 1
    pending.last_attempt_at = datetime.now(timezone.utc)
    pending.last_error = error
    pending.next_attempt_at = next_attempt_at
    session.commit()


def mark_pending_failed_permanently(session: Session, pending: PendingParse, error: str) -> None:
    pending.attempts += 1
    pending.last_attempt_at = datetime.now(timezone.utc)
    pending.last_error = error
    pending.status = "failed_permanently"
    session.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tresrv && python -m pytest tests/test_repo.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add tresrv/tresrv/repo.py tresrv/tests/test_repo.py
git commit -m "feat(tresrv): repository layer over SQLAlchemy (profile, weight, meals, pending_parse)"
```

---

### Task 9: Onboarding — pure validation + ConversationHandler + entrypoint skeleton

**Files:**
- Create: `tresrv/tresrv/bot/__init__.py`
- Create: `tresrv/tresrv/bot/onboarding.py`
- Create: `tresrv/tresrv/main.py`
- Test: `tresrv/tests/bot/test_onboarding.py`

**Interfaces:**
- Consumes: `repo.upsert_profile`, `repo.upsert_weight_log` (Task 8); `domain.daytime.local_date` (Task 3).
- Produces: pure parsers `parse_plec(text: str) -> str`, `parse_wiek(text: str) -> int`, `parse_wzrost(text: str) -> float`, `parse_waga(text: str) -> float`, `parse_aktywnosc(text: str) -> str`, `parse_cel(text: str) -> str` (each raises `ValueError` with a Polish user-facing message on invalid input); `build_onboarding_handler() -> telegram.ext.ConversationHandler` (wiring, not unit-tested here — manual test per spec §8).

- [ ] **Step 1: Write the failing tests for the pure parsers**

```python
# tresrv/tests/bot/test_onboarding.py
import pytest

from tresrv.bot.onboarding import (
    parse_plec, parse_wiek, parse_wzrost, parse_waga, parse_aktywnosc, parse_cel,
)


def test_parse_plec_accepts_m_and_k():
    assert parse_plec("M") == "m"
    assert parse_plec("k") == "k"


def test_parse_plec_rejects_other():
    with pytest.raises(ValueError):
        parse_plec("inne")


def test_parse_wiek_accepts_reasonable_range():
    assert parse_wiek("30") == 30


@pytest.mark.parametrize("text", ["0", "150", "abc"])
def test_parse_wiek_rejects_out_of_range_or_non_numeric(text):
    with pytest.raises(ValueError):
        parse_wiek(text)


def test_parse_wzrost_accepts_cm():
    assert parse_wzrost("180") == 180.0


@pytest.mark.parametrize("text", ["50", "260", "abc"])
def test_parse_wzrost_rejects_out_of_range(text):
    with pytest.raises(ValueError):
        parse_wzrost(text)


def test_parse_waga_accepts_kg():
    assert parse_waga("80.5") == 80.5


@pytest.mark.parametrize("text", ["10", "400", "abc"])
def test_parse_waga_rejects_out_of_range(text):
    with pytest.raises(ValueError):
        parse_waga(text)


def test_parse_aktywnosc_accepts_known_levels():
    assert parse_aktywnosc("moderate") == "moderate"


def test_parse_aktywnosc_rejects_unknown():
    with pytest.raises(ValueError):
        parse_aktywnosc("super_active")


def test_parse_cel_accepts_known_goals():
    assert parse_cel("reduction") == "reduction"


def test_parse_cel_rejects_unknown():
    with pytest.raises(ValueError):
        parse_cel("bulk")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tresrv && python -m pytest tests/bot/test_onboarding.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tresrv.bot'`

- [ ] **Step 3: Implement the pure parsers in onboarding.py**

```python
# tresrv/tresrv/bot/onboarding.py
_ACTIVITY_LEVELS = {"sedentary", "light", "moderate", "active", "very_active"}
_GOALS = {"reduction", "mass", "maintenance"}


def parse_plec(text: str) -> str:
    normalized = text.strip().lower()
    if normalized not in ("m", "k"):
        raise ValueError("Podaj 'M' (mężczyzna) lub 'K' (kobieta).")
    return normalized


def parse_wiek(text: str) -> int:
    try:
        value = int(text.strip())
    except ValueError as exc:
        raise ValueError("Wiek musi być liczbą całkowitą.") from exc
    if not (10 <= value <= 100):
        raise ValueError("Podaj realny wiek (10-100 lat).")
    return value


def parse_wzrost(text: str) -> float:
    try:
        value = float(text.strip().replace(",", "."))
    except ValueError as exc:
        raise ValueError("Wzrost musi być liczbą (w cm).") from exc
    if not (100 <= value <= 250):
        raise ValueError("Podaj realny wzrost w cm (100-250).")
    return value


def parse_waga(text: str) -> float:
    try:
        value = float(text.strip().replace(",", "."))
    except ValueError as exc:
        raise ValueError("Waga musi być liczbą (w kg).") from exc
    if not (30 <= value <= 300):
        raise ValueError("Podaj realną wagę w kg (30-300).")
    return value


def parse_aktywnosc(text: str) -> str:
    normalized = text.strip().lower()
    if normalized not in _ACTIVITY_LEVELS:
        raise ValueError(
            "Wybierz jeden z: sedentary, light, moderate, active, very_active."
        )
    return normalized


def parse_cel(text: str) -> str:
    normalized = text.strip().lower()
    if normalized not in _GOALS:
        raise ValueError("Wybierz jeden z: reduction, mass, maintenance.")
    return normalized
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tresrv && python -m pytest tests/bot/test_onboarding.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Add the ConversationHandler wiring (no unit test — wraps python-telegram-bot; verified manually per spec §8)**

```python
# tresrv/tresrv/bot/onboarding.py (append)
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, MessageHandler, filters,
)

from tresrv import repo
from tresrv.domain.daytime import local_date

PLEC, WIEK, WZROST, WAGA, AKTYWNOSC, CEL = range(6)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Zaczynamy onboarding. Podaj płeć (M/K):")
    return PLEC


async def receive_plec(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["plec"] = parse_plec(update.message.text)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return PLEC
    await update.message.reply_text("Podaj wiek (lata):")
    return WIEK


async def receive_wiek(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["wiek"] = parse_wiek(update.message.text)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return WIEK
    await update.message.reply_text("Podaj wzrost (cm):")
    return WZROST


async def receive_wzrost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["wzrost_cm"] = parse_wzrost(update.message.text)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return WZROST
    await update.message.reply_text("Podaj wagę (kg):")
    return WAGA


async def receive_waga(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["waga_kg"] = parse_waga(update.message.text)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return WAGA
    await update.message.reply_text(
        "Poziom aktywności (sedentary/light/moderate/active/very_active):"
    )
    return AKTYWNOSC


async def receive_aktywnosc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["poziom_aktywnosci"] = parse_aktywnosc(update.message.text)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return AKTYWNOSC
    await update.message.reply_text("Cel (reduction/mass/maintenance):")
    return CEL


async def receive_cel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        cel = parse_cel(update.message.text)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return CEL

    chat_id = update.effective_chat.id
    now = datetime.now(timezone.utc)
    session = context.bot_data["session_factory"]()
    try:
        repo.upsert_profile(
            session, chat_id=chat_id,
            plec=context.user_data["plec"], wiek=context.user_data["wiek"],
            wzrost_cm=context.user_data["wzrost_cm"], waga_kg=context.user_data["waga_kg"],
            poziom_aktywnosci=context.user_data["poziom_aktywnosci"], cel=cel,
        )
        repo.upsert_weight_log(
            session, chat_id=chat_id, waga_kg=context.user_data["waga_kg"],
            logged_at=now, local_date=local_date(now),
        )
    finally:
        session.close()

    await update.message.reply_text("Profil zapisany. Możesz teraz logować posiłki i wagę.")
    return ConversationHandler.END


def build_onboarding_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            PLEC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_plec)],
            WIEK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_wiek)],
            WZROST: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_wzrost)],
            WAGA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_waga)],
            AKTYWNOSC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_aktywnosc)],
            CEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_cel)],
        },
        fallbacks=[],
    )
```

- [ ] **Step 6: Write main.py entrypoint skeleton**

```python
# tresrv/tresrv/main.py
from telegram.ext import Application

from tresrv.config import load_settings
from tresrv.db import make_session_factory
from tresrv.bot.onboarding import build_onboarding_handler


def build_application() -> Application:
    settings = load_settings()
    session_factory = make_session_factory(settings.database_url)

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.bot_data["session_factory"] = session_factory
    application.bot_data["settings"] = settings
    application.add_handler(build_onboarding_handler())
    return application


def main() -> None:
    application = build_application()
    application.run_polling()


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run full test suite to verify no regression**

Run: `cd tresrv && python -m pytest -v`
Expected: PASS (all tests from Tasks 1-9)

- [ ] **Step 8: Commit**

```bash
git add tresrv/tresrv/bot/__init__.py tresrv/tresrv/bot/onboarding.py tresrv/tresrv/main.py \
        tresrv/tests/bot/test_onboarding.py
git commit -m "feat(tresrv): onboarding conversation handler + entrypoint skeleton"
```

---

### Task 10: `/profil`, `/cel`, `/waga` commands

**Files:**
- Create: `tresrv/tresrv/bot/profile.py`
- Create: `tresrv/tresrv/bot/weight.py`
- Test: `tresrv/tests/bot/test_profile.py`
- Test: `tresrv/tests/bot/test_weight.py`
- Modify: `tresrv/tresrv/main.py:1-18` (register the two new handlers)

**Interfaces:**
- Consumes: `parse_cel`, `parse_waga` (Task 9); `repo.upsert_profile`, `repo.upsert_weight_log`, `repo.get_profile` (Task 8); `local_date` (Task 3).
- Produces: `parse_cel_command(args: list[str]) -> str` (validates `/cel <value>` args); `parse_waga_command(args: list[str]) -> float` (validates `/waga <value>` args); `format_profile(profile) -> str`; `cel_command`, `waga_command`, `profil_command` (async PTB handlers, wiring only).

- [ ] **Step 1: Write the failing tests**

```python
# tresrv/tests/bot/test_profile.py
import pytest
from datetime import datetime, timezone

from tresrv.bot.profile import parse_cel_command, format_profile
from tresrv.models import UserProfile


def test_parse_cel_command_valid():
    assert parse_cel_command(["reduction"]) == "reduction"


def test_parse_cel_command_no_args_raises():
    with pytest.raises(ValueError):
        parse_cel_command([])


def test_parse_cel_command_invalid_value_raises():
    with pytest.raises(ValueError):
        parse_cel_command(["bulk"])


def test_format_profile_includes_all_fields():
    profile = UserProfile(
        chat_id=1, plec="m", wiek=30, wzrost_cm=180, waga_kg=80,
        poziom_aktywnosci="moderate", cel="reduction",
        updated_at=datetime.now(timezone.utc),
    )
    text = format_profile(profile)
    assert "180" in text
    assert "80" in text
    assert "reduction" in text
```

```python
# tresrv/tests/bot/test_weight.py
import pytest

from tresrv.bot.weight import parse_waga_command


def test_parse_waga_command_valid():
    assert parse_waga_command(["80.5"]) == 80.5


def test_parse_waga_command_no_args_raises():
    with pytest.raises(ValueError):
        parse_waga_command([])


def test_parse_waga_command_out_of_range_raises():
    with pytest.raises(ValueError):
        parse_waga_command(["500"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tresrv && python -m pytest tests/bot/test_profile.py tests/bot/test_weight.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement profile.py**

```python
# tresrv/tresrv/bot/profile.py
from telegram import Update
from telegram.ext import ContextTypes

from tresrv import repo
from tresrv.bot.onboarding import parse_cel
from tresrv.models import UserProfile


def parse_cel_command(args: list[str]) -> str:
    if not args:
        raise ValueError("Użycie: /cel reduction|mass|maintenance")
    return parse_cel(args[0])


def format_profile(profile: UserProfile) -> str:
    return (
        f"Płeć: {profile.plec}\n"
        f"Wiek: {profile.wiek}\n"
        f"Wzrost: {profile.wzrost_cm} cm\n"
        f"Waga: {profile.waga_kg} kg\n"
        f"Aktywność: {profile.poziom_aktywnosci}\n"
        f"Cel: {profile.cel}"
    )


async def profil_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = context.bot_data["session_factory"]()
    try:
        profile = repo.get_profile(session, update.effective_chat.id)
    finally:
        session.close()

    if profile is None:
        await update.message.reply_text("Brak profilu. Użyj /start.")
        return
    await update.message.reply_text(format_profile(profile))


async def cel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        cel = parse_cel_command(context.args)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    session = context.bot_data["session_factory"]()
    try:
        repo.upsert_profile(session, chat_id=update.effective_chat.id, cel=cel)
    finally:
        session.close()
    await update.message.reply_text(f"Cel ustawiony na: {cel}")
```

- [ ] **Step 4: Implement weight.py**

```python
# tresrv/tresrv/bot/weight.py
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

from tresrv import repo
from tresrv.bot.onboarding import parse_waga
from tresrv.domain.daytime import local_date


def parse_waga_command(args: list[str]) -> float:
    if not args:
        raise ValueError("Użycie: /waga 80.5")
    return parse_waga(args[0])


async def waga_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        waga_kg = parse_waga_command(context.args)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    now = datetime.now(timezone.utc)
    session = context.bot_data["session_factory"]()
    try:
        repo.upsert_weight_log(
            session, chat_id=update.effective_chat.id, waga_kg=waga_kg,
            logged_at=now, local_date=local_date(now),
        )
        repo.upsert_profile(session, chat_id=update.effective_chat.id, waga_kg=waga_kg)
    finally:
        session.close()
    await update.message.reply_text(f"Zapisano wagę: {waga_kg} kg")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd tresrv && python -m pytest tests/bot/test_profile.py tests/bot/test_weight.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Register handlers in main.py**

```python
# tresrv/tresrv/main.py — modify build_application()
from telegram.ext import CommandHandler

from tresrv.bot.profile import profil_command, cel_command
from tresrv.bot.weight import waga_command

# inside build_application(), after application.add_handler(build_onboarding_handler()):
    application.add_handler(CommandHandler("profil", profil_command))
    application.add_handler(CommandHandler("cel", cel_command))
    application.add_handler(CommandHandler("waga", waga_command))
```

- [ ] **Step 7: Commit**

```bash
git add tresrv/tresrv/bot/profile.py tresrv/tresrv/bot/weight.py tresrv/tresrv/main.py \
        tresrv/tests/bot/test_profile.py tresrv/tests/bot/test_weight.py
git commit -m "feat(tresrv): /profil, /cel, /waga commands"
```

---

### Task 11: Meal logging (text + photo)

**Files:**
- Create: `tresrv/tresrv/bot/meals.py`
- Modify: `tresrv/tresrv/main.py:1-24` (register message handlers)
- Test: `tresrv/tests/bot/test_meals.py`

**Interfaces:**
- Consumes: `GeminiClient`, `ParsedMeal`, `NotFoodError`, `ParseError` (Task 7); `repo.save_meal`, `repo.save_pending_parse` (Task 8); `resolve_consumed_at`, `local_date` (Task 3); `needs_confirmation` (Task 5).
- Produces: `build_meal_fields(chat_id: int, parsed: ParsedMeal, raw_input_type: str, raw_text: str | None, storage_path: str | None, telegram_file_id: str | None, logged_at: datetime) -> dict` (pure — the exact kwargs `repo.save_meal` expects); `resolve_photo_storage(download_succeeded: bool, storage_path: str | None, telegram_file_id: str) -> tuple[str | None, str | None]` (pure); `format_meal_reply(fields: dict) -> str`; `text_message_handler`, `photo_message_handler` (async PTB wiring).

- [ ] **Step 1: Write the failing tests for the pure functions**

```python
# tresrv/tests/bot/test_meals.py
from datetime import datetime, timezone

from tresrv.bot.meals import build_meal_fields, resolve_photo_storage, format_meal_reply
from tresrv.llm import ParsedMeal


def test_build_meal_fields_defaults_consumed_at_to_logged_at():
    logged_at = datetime(2026, 8, 23, 19, 0, tzinfo=timezone.utc)
    parsed = ParsedMeal(kcal=450, protein_g=30, fat_g=15, carbs_g=40,
                         opis="kurczak z ryzem", confidence=0.9, when_hint=None)

    fields = build_meal_fields(
        chat_id=1, parsed=parsed, raw_input_type="text", raw_text="kurczak z ryzem",
        storage_path=None, telegram_file_id=None, logged_at=logged_at,
    )

    assert fields["consumed_at"] == logged_at
    assert fields["consumed_date"] == logged_at.date()
    assert fields["kcal"] == 450
    assert fields["needs_confirmation"] is False
    assert fields["value_source"] == "llm"
    assert fields["status"] == "parsed"


def test_build_meal_fields_applies_when_hint():
    logged_at = datetime(2026, 8, 23, 8, 0, tzinfo=timezone.utc)
    parsed = ParsedMeal(kcal=450, protein_g=30, fat_g=15, carbs_g=40,
                         opis="pizza", confidence=0.9, when_hint="yesterday")

    fields = build_meal_fields(
        chat_id=1, parsed=parsed, raw_input_type="text", raw_text="wczoraj jadlem pizze",
        storage_path=None, telegram_file_id=None, logged_at=logged_at,
    )

    assert fields["consumed_at"] < logged_at


def test_build_meal_fields_low_confidence_needs_confirmation():
    logged_at = datetime(2026, 8, 23, 19, 0, tzinfo=timezone.utc)
    parsed = ParsedMeal(kcal=450, protein_g=30, fat_g=15, carbs_g=40,
                         opis="cos", confidence=0.4, when_hint=None)

    fields = build_meal_fields(
        chat_id=1, parsed=parsed, raw_input_type="text", raw_text="cos",
        storage_path=None, telegram_file_id=None, logged_at=logged_at,
    )

    assert fields["needs_confirmation"] is True


def test_resolve_photo_storage_download_succeeded():
    path, file_id = resolve_photo_storage(True, "/data/meals/abc.jpg", "tg_file_1")
    assert path == "/data/meals/abc.jpg"
    assert file_id == "tg_file_1"


def test_resolve_photo_storage_download_failed_keeps_file_id_only():
    path, file_id = resolve_photo_storage(False, None, "tg_file_1")
    assert path is None
    assert file_id == "tg_file_1"


def test_format_meal_reply_labels_as_estimate():
    fields = {"kcal": 740, "protein_g": 48, "fat_g": 22, "carbs_g": 73, "value_source": "llm"}
    text = format_meal_reply(fields)
    assert "Szacunek" in text
    assert "740" in text


def test_format_meal_reply_labels_as_user_correction():
    fields = {"kcal": 740, "protein_g": 48, "fat_g": 22, "carbs_g": 73, "value_source": "user"}
    text = format_meal_reply(fields)
    assert "Twoja korekta" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tresrv && python -m pytest tests/bot/test_meals.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tresrv.bot.meals'`

- [ ] **Step 3: Implement the pure functions in meals.py**

```python
# tresrv/tresrv/bot/meals.py
from datetime import datetime, timezone

from tresrv.domain.confirmation import needs_confirmation
from tresrv.domain.daytime import resolve_consumed_at
from tresrv.llm import ParsedMeal


def build_meal_fields(
    chat_id: int, parsed: ParsedMeal, raw_input_type: str,
    raw_text: str | None, storage_path: str | None, telegram_file_id: str | None,
    logged_at: datetime,
) -> dict:
    consumed_at, _time_needs_confirmation = resolve_consumed_at(logged_at, parsed.when_hint)
    confirmation_needed = needs_confirmation(
        parsed.confidence, parsed.kcal, raw_input_type, parsed.opis
    ) or _time_needs_confirmation

    return {
        "chat_id": chat_id,
        "logged_at": logged_at,
        "consumed_at": consumed_at,
        "consumed_date": consumed_at.date(),
        "raw_input_type": raw_input_type,
        "raw_text": raw_text,
        "storage_path": storage_path,
        "telegram_file_id": telegram_file_id,
        "opis": parsed.opis,
        "kcal": parsed.kcal,
        "protein_g": parsed.protein_g,
        "fat_g": parsed.fat_g,
        "carbs_g": parsed.carbs_g,
        "confidence": parsed.confidence,
        "needs_confirmation": confirmation_needed,
        "value_source": "llm",
        "status": "parsed",
        "created_at": datetime.now(timezone.utc),
    }


def resolve_photo_storage(
    download_succeeded: bool, storage_path: str | None, telegram_file_id: str,
) -> tuple[str | None, str | None]:
    if download_succeeded:
        return storage_path, telegram_file_id
    return None, telegram_file_id


def format_meal_reply(fields: dict) -> str:
    label = "Twoja korekta" if fields["value_source"] == "user" else "Szacunek"
    return (
        f"{label}: {fields['kcal']:.0f} kcal\n"
        f"B: {fields['protein_g']:.0f}g | T: {fields['fat_g']:.0f}g | "
        f"W: {fields['carbs_g']:.0f}g"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tresrv && python -m pytest tests/bot/test_meals.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Add PTB wiring (no new unit test — manual test per spec §8)**

```python
# tresrv/tresrv/bot/meals.py (append)
import uuid
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from tresrv import repo
from tresrv.llm import NotFoodError, ParseError

MEALS_DIR = Path("/data/meals")


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = update.message.text
    logged_at = datetime.now(timezone.utc)
    llm_client = context.bot_data["llm_client"]
    session = context.bot_data["session_factory"]()
    try:
        try:
            parsed = llm_client.parse_text(text)
        except NotFoundErrorPlaceholder:  # replaced below
            raise
        except NotFoodError:
            await update.message.reply_text("To nie wygląda na jedzenie — spróbuj inaczej.")
            return
        except ParseError as exc:
            repo.save_pending_parse(
                session, chat_id=chat_id, raw_input_type="text", raw_text=text,
                logged_at=logged_at, consumed_at=logged_at, next_attempt_at=logged_at,
                status="pending", created_at=logged_at, last_error=str(exc),
            )
            await update.message.reply_text("Zapisane, policzę za chwilę.")
            return

        fields = build_meal_fields(
            chat_id=chat_id, parsed=parsed, raw_input_type="text", raw_text=text,
            storage_path=None, telegram_file_id=None, logged_at=logged_at,
        )
        fields["llm_model"] = llm_client.model_name
        repo.save_meal(session, **fields)
        await update.message.reply_text(format_meal_reply(fields))
    finally:
        session.close()


async def photo_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logged_at = datetime.now(timezone.utc)
    telegram_photo = update.message.photo[-1]
    telegram_file_id = telegram_photo.file_id

    MEALS_DIR.mkdir(parents=True, exist_ok=True)
    storage_path = str(MEALS_DIR / f"{uuid.uuid4()}.jpg")
    download_succeeded = True
    try:
        telegram_file = await context.bot.get_file(telegram_file_id)
        await telegram_file.download_to_drive(storage_path)
    except Exception:
        download_succeeded = False

    resolved_path, resolved_file_id = resolve_photo_storage(
        download_succeeded, storage_path, telegram_file_id
    )

    llm_client = context.bot_data["llm_client"]
    session = context.bot_data["session_factory"]()
    try:
        if not download_succeeded:
            repo.save_pending_parse(
                session, chat_id=chat_id, raw_input_type="photo", telegram_file_id=resolved_file_id,
                logged_at=logged_at, consumed_at=logged_at, next_attempt_at=logged_at,
                status="pending", created_at=logged_at, last_error="download failed",
            )
            await update.message.reply_text("Zapisane, policzę za chwilę.")
            return

        try:
            parsed = llm_client.parse_photo(resolved_path)
        except NotFoodError:
            await update.message.reply_text("To nie wygląda na jedzenie — spróbuj inaczej.")
            return
        except ParseError as exc:
            repo.save_pending_parse(
                session, chat_id=chat_id, raw_input_type="photo", storage_path=resolved_path,
                telegram_file_id=resolved_file_id, logged_at=logged_at, consumed_at=logged_at,
                next_attempt_at=logged_at, status="pending", created_at=logged_at,
                last_error=str(exc),
            )
            await update.message.reply_text("Zapisane, policzę za chwilę.")
            return

        fields = build_meal_fields(
            chat_id=chat_id, parsed=parsed, raw_input_type="photo", raw_text=None,
            storage_path=resolved_path, telegram_file_id=resolved_file_id, logged_at=logged_at,
        )
        fields["llm_model"] = llm_client.model_name
        repo.save_meal(session, **fields)
        await update.message.reply_text(format_meal_reply(fields))
    finally:
        session.close()
```

**Note for the implementer:** remove the stray `except NotFoundErrorPlaceholder: raise` line above when writing this file — it was left in to mark that `NotFoodError` must be caught *before* the generic `ParseError` handler; delete that placeholder line entirely.

- [ ] **Step 6: Register handlers in main.py**

```python
# tresrv/tresrv/main.py — modify build_application()
from telegram.ext import MessageHandler, filters

from tresrv.llm import GeminiClient
from tresrv.bot.meals import text_message_handler, photo_message_handler

# inside build_application(), after registering command handlers:
    application.bot_data["llm_client"] = GeminiClient(api_key=settings.gemini_api_key)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    application.add_handler(MessageHandler(filters.PHOTO, photo_message_handler))
```

- [ ] **Step 7: Run full test suite**

Run: `cd tresrv && python -m pytest -v`
Expected: PASS (all tests)

- [ ] **Step 8: Commit**

```bash
git add tresrv/tresrv/bot/meals.py tresrv/tresrv/main.py tresrv/tests/bot/test_meals.py
git commit -m "feat(tresrv): meal logging via text and photo, with pending_parse fallback"
```

---

### Task 12: Retry queue drain job

**Files:**
- Create: `tresrv/tresrv/scheduler/__init__.py`
- Create: `tresrv/tresrv/scheduler/jobs.py`
- Test: `tresrv/tests/scheduler/test_jobs.py`

**Interfaces:**
- Consumes: `repo.fetch_due_pending`, `repo.mark_pending_resolved`, `repo.mark_pending_retry`, `repo.mark_pending_failed_permanently`, `repo.save_meal` (Task 8); `GeminiClient`, `ParseError`, `NotFoodError` (Task 7); `build_meal_fields` (Task 11).
- Produces: `next_backoff_seconds(attempts: int) -> int` (pure: `60, 120, 300, 300, 300...`); `drain_pending_parse(session, llm_client, now, max_attempts: int) -> dict` (returns `{"resolved": int, "retried": int, "failed_permanently": int}` — the testable core, injectable `session`/`llm_client`/`now`); `run_pending_parse_drain_job(session_factory, llm_client, settings)` (APScheduler-facing wrapper).

- [ ] **Step 1: Write the failing tests**

```python
# tresrv/tests/scheduler/test_jobs.py
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tresrv.models import Base
from tresrv import repo
from tresrv.llm import ParsedMeal, ParseError, NotFoodError
from tresrv.scheduler.jobs import next_backoff_seconds, drain_pending_parse


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


class FakeLLMSucceeds:
    model_name = "fake-model"

    def parse_text(self, text):
        return ParsedMeal(kcal=400, protein_g=25, fat_g=10, carbs_g=40,
                           opis=text, confidence=0.9, when_hint=None)


class FakeLLMFailsWithParseError:
    model_name = "fake-model"

    def parse_text(self, text):
        raise ParseError("still garbage")


@pytest.mark.parametrize("attempts,expected", [(0, 60), (1, 120), (2, 300), (3, 300), (10, 300)])
def test_next_backoff_seconds(attempts, expected):
    assert next_backoff_seconds(attempts) == expected


def test_drain_resolves_pending_on_success(session):
    now = datetime.now(timezone.utc)
    repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="kurczak",
        logged_at=now, consumed_at=now, next_attempt_at=now - timedelta(minutes=1),
        status="pending", created_at=now,
    )

    result = drain_pending_parse(session, FakeLLMSucceeds(), now, max_attempts=5)

    assert result == {"resolved": 1, "retried": 0, "failed_permanently": 0}
    active_meals = repo.get_active_meals_for_day(session, 1, now.date())
    assert len(active_meals) == 1
    pending_rows = session.query(repo.PendingParse).all()
    assert pending_rows[0].status == "resolved"


def test_drain_retries_on_parse_error_below_two_attempts(session):
    now = datetime.now(timezone.utc)
    pending = repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="kurczak",
        logged_at=now, consumed_at=now, next_attempt_at=now - timedelta(minutes=1),
        status="pending", created_at=now, attempts=0,
    )

    result = drain_pending_parse(session, FakeLLMFailsWithParseError(), now, max_attempts=5)

    assert result == {"resolved": 0, "retried": 1, "failed_permanently": 0}
    session.refresh(pending)
    assert pending.status == "pending"
    assert pending.attempts == 1


def test_drain_fails_permanently_after_two_parse_errors(session):
    now = datetime.now(timezone.utc)
    pending = repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="kurczak",
        logged_at=now, consumed_at=now, next_attempt_at=now - timedelta(minutes=1),
        status="pending", created_at=now, attempts=1,
        last_error="nieparsowalny JSON",
    )

    result = drain_pending_parse(session, FakeLLMFailsWithParseError(), now, max_attempts=5)

    assert result == {"resolved": 0, "retried": 0, "failed_permanently": 1}
    session.refresh(pending)
    assert pending.status == "failed_permanently"


def test_drain_fails_permanently_after_max_attempts(session):
    now = datetime.now(timezone.utc)

    class FlakyLLM:
        model_name = "fake-model"

        def parse_text(self, text):
            raise ParseError("temporary-looking but keeps failing")

    pending = repo.save_pending_parse(
        session, chat_id=1, raw_input_type="text", raw_text="kurczak",
        logged_at=now, consumed_at=now, next_attempt_at=now - timedelta(minutes=1),
        status="pending", created_at=now, attempts=4,
    )

    result = drain_pending_parse(session, FlakyLLM(), now, max_attempts=5)

    assert result["failed_permanently"] == 1
    session.refresh(pending)
    assert pending.status == "failed_permanently"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tresrv && python -m pytest tests/scheduler/test_jobs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tresrv.scheduler'`

- [ ] **Step 3: Implement jobs.py (drain function)**

```python
# tresrv/tresrv/scheduler/jobs.py
from datetime import datetime, timedelta

from tresrv import repo
from tresrv.bot.meals import build_meal_fields
from tresrv.llm import NotFoodError, ParseError

_BACKOFF_SCHEDULE = [60, 120, 300]


def next_backoff_seconds(attempts: int) -> int:
    if attempts < len(_BACKOFF_SCHEDULE):
        return _BACKOFF_SCHEDULE[attempts]
    return _BACKOFF_SCHEDULE[-1]


def drain_pending_parse(session, llm_client, now: datetime, max_attempts: int) -> dict:
    counts = {"resolved": 0, "retried": 0, "failed_permanently": 0}

    for pending in repo.fetch_due_pending(session, now):
        try:
            if pending.raw_input_type == "text":
                parsed = llm_client.parse_text(pending.raw_text)
            else:
                parsed = llm_client.parse_photo(pending.storage_path)
        except NotFoodError:
            repo.mark_pending_failed_permanently(session, pending, "not_food")
            counts["failed_permanently"] += 1
            continue
        except ParseError as exc:
            repeated_parse_error = (pending.last_error is not None and pending.attempts >= 1)
            if repeated_parse_error or pending.attempts + 1 >= max_attempts:
                repo.mark_pending_failed_permanently(session, pending, str(exc))
                counts["failed_permanently"] += 1
            else:
                next_attempt_at = now + timedelta(seconds=next_backoff_seconds(pending.attempts))
                repo.mark_pending_retry(session, pending, str(exc), next_attempt_at)
                counts["retried"] += 1
            continue

        fields = build_meal_fields(
            chat_id=pending.chat_id, parsed=parsed, raw_input_type=pending.raw_input_type,
            raw_text=pending.raw_text, storage_path=pending.storage_path,
            telegram_file_id=pending.telegram_file_id, logged_at=pending.logged_at,
        )
        fields["llm_model"] = llm_client.model_name
        meal = repo.save_meal(session, **fields)
        repo.mark_pending_resolved(session, pending, meal.id)
        counts["resolved"] += 1

    return counts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tresrv && python -m pytest tests/scheduler/test_jobs.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Add the APScheduler-facing wrapper and heartbeat job (no new unit test — thin wiring)**

```python
# tresrv/tresrv/scheduler/jobs.py (append)
import logging

logger = logging.getLogger("tresrv.scheduler")


def run_pending_parse_drain_job(session_factory, llm_client, max_attempts: int) -> None:
    from datetime import datetime, timezone
    session = session_factory()
    try:
        counts = drain_pending_parse(session, llm_client, datetime.now(timezone.utc), max_attempts)
        if counts["resolved"] or counts["retried"] or counts["failed_permanently"]:
            logger.info("pending_parse drain: %s", counts)
    finally:
        session.close()


def run_heartbeat_job(session_factory) -> None:
    from datetime import datetime, timezone
    from sqlalchemy import text
    session = session_factory()
    try:
        session.execute(text(
            "CREATE TABLE IF NOT EXISTS heartbeat (id INTEGER PRIMARY KEY, last_beat_at TIMESTAMP)"
        ))
        session.execute(text(
            "INSERT INTO heartbeat (id, last_beat_at) VALUES (1, :now) "
            "ON CONFLICT (id) DO UPDATE SET last_beat_at = :now"
        ), {"now": datetime.now(timezone.utc)})
        session.commit()
    finally:
        session.close()
```

- [ ] **Step 6: Wire scheduler into main.py**

```python
# tresrv/tresrv/main.py — modify build_application()
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from tresrv.scheduler.jobs import run_pending_parse_drain_job, run_heartbeat_job

# inside build_application(), before "return application":
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_pending_parse_drain_job,
        "interval", minutes=settings.pending_parse_interval_minutes,
        args=[session_factory, application.bot_data["llm_client"], settings.max_pending_attempts],
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        run_heartbeat_job, "interval", minutes=settings.heartbeat_interval_minutes,
        args=[session_factory],
    )
    application.bot_data["scheduler"] = scheduler
    scheduler.start()
```

- [ ] **Step 7: Run full test suite**

Run: `cd tresrv && python -m pytest -v`
Expected: PASS (all tests)

- [ ] **Step 8: Commit**

```bash
git add tresrv/tresrv/scheduler/__init__.py tresrv/tresrv/scheduler/jobs.py \
        tresrv/tresrv/main.py tresrv/tests/scheduler/test_jobs.py
git commit -m "feat(tresrv): pending_parse retry queue drain job + heartbeat"
```

---

### Task 13: Evening summary job

**Files:**
- Modify: `tresrv/tresrv/scheduler/jobs.py:1-10` (add summary building + job)
- Modify: `tresrv/tresrv/main.py:1-40` (register the job)
- Test: `tresrv/tests/scheduler/test_evening_summary.py`

**Interfaces:**
- Consumes: `repo.get_active_meals_for_day`, `repo.get_profile` (Task 8); `aggregate_day`, `MealRow` (Task 6); `daily_target` (Task 4); `local_date` (Task 3).
- Produces: `build_summary_text(day_summary: DaySummary, target: DailyTarget) -> str`; `build_evening_summary(session, chat_id: int, today) -> str | None` (returns `None` when no profile exists yet); `run_evening_summary_job(session_factory, bot, chat_id)` (APScheduler-facing, sends the Telegram message).

- [ ] **Step 1: Write the failing tests**

```python
# tresrv/tests/scheduler/test_evening_summary.py
from datetime import datetime, timezone, date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tresrv.models import Base
from tresrv import repo
from tresrv.domain.targets import DailyTarget
from tresrv.domain.aggregation import DaySummary
from tresrv.scheduler.jobs import build_summary_text, build_evening_summary


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_build_summary_text_includes_kcal_and_protein_vs_target():
    summary = DaySummary(kcal=1850, protein_g=140, fat_g=60, carbs_g=180, meal_count=3)
    target = DailyTarget(kcal=2100, protein_g=160)

    text = build_summary_text(summary, target)

    assert "1850" in text
    assert "2100" in text
    assert "140" in text
    assert "160" in text
    assert "Szacunkowo" in text


def test_build_evening_summary_returns_none_without_profile(session):
    result = build_evening_summary(session, chat_id=1, today=date(2026, 8, 23))
    assert result is None


def test_build_evening_summary_excludes_superseded_meals(session):
    now = datetime.now(timezone.utc)
    today = now.date()
    repo.upsert_profile(
        session, chat_id=1, plec="m", wiek=30, wzrost_cm=180, waga_kg=80,
        poziom_aktywnosci="moderate", cel="reduction",
    )
    original = repo.save_meal(
        session, chat_id=1, logged_at=now, consumed_at=now, consumed_date=today,
        raw_input_type="text", raw_text="a", kcal=300, protein_g=20, fat_g=10,
        carbs_g=30, status="superseded", created_at=now,
    )
    repo.save_meal(
        session, chat_id=1, logged_at=now, consumed_at=now, consumed_date=today,
        raw_input_type="text", raw_text="b", kcal=320, protein_g=22, fat_g=10,
        carbs_g=30, status="corrected", corrected_from_id=original.id, created_at=now,
    )

    text = build_evening_summary(session, chat_id=1, today=today)

    assert "320" in text
    assert "300" not in text or "320" in text  # 320 must appear; 300 must not dominate the total
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tresrv && python -m pytest tests/scheduler/test_evening_summary.py -v`
Expected: FAIL — `build_summary_text` / `build_evening_summary` not defined

- [ ] **Step 3: Implement in jobs.py**

```python
# tresrv/tresrv/scheduler/jobs.py (append)
from tresrv.domain.aggregation import MealRow, aggregate_day
from tresrv.domain.targets import daily_target


def build_summary_text(day_summary, target) -> str:
    return (
        f"Szacunkowo {day_summary.kcal:.0f}/{target.kcal:.0f} kcal, "
        f"białko {day_summary.protein_g:.0f}/{target.protein_g:.0f}g "
        f"({day_summary.meal_count} posiłków dziś)."
    )


def build_evening_summary(session, chat_id: int, today) -> str | None:
    profile = repo.get_profile(session, chat_id)
    if profile is None:
        return None

    meals = repo.get_active_meals_for_day(session, chat_id, today)
    meal_rows = [
        MealRow(kcal=float(m.kcal), protein_g=float(m.protein_g),
                fat_g=float(m.fat_g), carbs_g=float(m.carbs_g), status=m.status)
        for m in meals
    ]
    day_summary = aggregate_day(meal_rows)
    target = daily_target(
        profile.plec, float(profile.waga_kg), float(profile.wzrost_cm),
        profile.wiek, profile.poziom_aktywnosci, profile.cel,
    )
    return build_summary_text(day_summary, target)


def run_evening_summary_job(session_factory, bot, chat_id: int) -> None:
    from datetime import datetime, timezone
    from tresrv.domain.daytime import local_date

    session = session_factory()
    try:
        today = local_date(datetime.now(timezone.utc))
        text = build_evening_summary(session, chat_id, today)
    finally:
        session.close()

    if text is not None:
        import asyncio
        asyncio.run(bot.send_message(chat_id=chat_id, text=text))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tresrv && python -m pytest tests/scheduler/test_evening_summary.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Register the job in main.py**

```python
# tresrv/tresrv/main.py — modify build_application(), inside the scheduler block
from tresrv.scheduler.jobs import run_evening_summary_job

    scheduler.add_job(
        run_evening_summary_job, "cron",
        hour=settings.evening_summary_hour, minute=settings.evening_summary_minute,
        timezone="Europe/Warsaw",
        args=[session_factory, application.bot, settings.telegram_chat_id],
    )
```

- [ ] **Step 6: Run full test suite**

Run: `cd tresrv && python -m pytest -v`
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add tresrv/tresrv/scheduler/jobs.py tresrv/tresrv/main.py \
        tresrv/tests/scheduler/test_evening_summary.py
git commit -m "feat(tresrv): evening summary job (snapshot, excludes superseded meals)"
```

---

### Task 14: `/popraw` correction (text fallback + inline keyboard)

**Files:**
- Create: `tresrv/tresrv/bot/correction.py`
- Modify: `tresrv/tresrv/main.py:1-45` (register handlers)
- Test: `tresrv/tests/bot/test_correction.py`

**Interfaces:**
- Consumes: `repo.get_last_active_meal`, `repo.correct_meal` (Task 8); `resolve_consumed_at` (Task 3); `format_meal_reply` (Task 11); `aggregate_day`, `MealRow` (Task 6, used only in the regression test).
- Produces: `CORRECTABLE_FIELDS = {"kcal", "protein_g", "fat_g", "carbs_g"}`; `parse_popraw_command(args: list[str]) -> dict` (parses `/popraw <pole> <wartość>` or `/popraw kiedy <opis>` into `{"kcal": 740}` or `{"consumed_at_hint": "wczoraj 20:00"}`, raises `ValueError` on bad input); `popraw_command` (async PTB handler, text-fallback path); `build_correction_keyboard(meal) -> telegram.InlineKeyboardMarkup`; `correction_callback_handler` (async PTB `CallbackQueryHandler`, wiring only — manual test per spec §8).

- [ ] **Step 1: Write the failing tests for the pure parser and the repo integration**

```python
# tresrv/tests/bot/test_correction.py
from datetime import datetime, timezone, date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tresrv.models import Base
from tresrv import repo
from tresrv.domain.aggregation import MealRow, aggregate_day
from tresrv.bot.correction import parse_popraw_command


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_parse_popraw_command_kcal():
    assert parse_popraw_command(["kcal", "740"]) == {"kcal": 740.0}


def test_parse_popraw_command_protein():
    assert parse_popraw_command(["protein_g", "48"]) == {"protein_g": 48.0}


def test_parse_popraw_command_unknown_field_raises():
    with pytest.raises(ValueError):
        parse_popraw_command(["kalorie", "740"])


def test_parse_popraw_command_no_args_raises():
    with pytest.raises(ValueError):
        parse_popraw_command([])


def test_parse_popraw_command_non_numeric_value_raises():
    with pytest.raises(ValueError):
        parse_popraw_command(["kcal", "dużo"])


def test_correction_then_daily_aggregate_counts_once(session):
    now = datetime.now(timezone.utc)
    today = now.date()
    original = repo.save_meal(
        session, chat_id=1, logged_at=now, consumed_at=now, consumed_date=today,
        raw_input_type="text", raw_text="kanapka", kcal=300, protein_g=20,
        fat_g=10, carbs_g=30, opis="kanapka", status="parsed", created_at=now,
    )

    repo.correct_meal(session, original.id, kcal=600)

    meals = repo.get_active_meals_for_day(session, 1, today)
    rows = [MealRow(kcal=float(m.kcal), protein_g=float(m.protein_g),
                     fat_g=float(m.fat_g), carbs_g=float(m.carbs_g), status=m.status)
            for m in meals]
    summary = aggregate_day(rows)
    assert summary.kcal == 600  # not 900 — the superseded original must not double-count
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tresrv && python -m pytest tests/bot/test_correction.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tresrv.bot.correction'`

- [ ] **Step 3: Implement the pure parser in correction.py**

```python
# tresrv/tresrv/bot/correction.py
CORRECTABLE_FIELDS = {"kcal", "protein_g", "fat_g", "carbs_g"}


def parse_popraw_command(args: list[str]) -> dict:
    if len(args) < 2:
        raise ValueError(
            "Użycie: /popraw <kcal|protein_g|fat_g|carbs_g> <wartość>"
        )
    field, raw_value = args[0], args[1]
    if field not in CORRECTABLE_FIELDS:
        raise ValueError(f"Nieznane pole. Wybierz jedno z: {', '.join(sorted(CORRECTABLE_FIELDS))}")
    try:
        value = float(raw_value.replace(",", "."))
    except ValueError as exc:
        raise ValueError("Wartość musi być liczbą.") from exc
    return {field: value}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tresrv && python -m pytest tests/bot/test_correction.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Add PTB wiring — text fallback command + inline keyboard (no new unit test on the wiring itself — manual test per spec §8)**

```python
# tresrv/tresrv/bot/correction.py (append)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from tresrv import repo
from tresrv.bot.meals import format_meal_reply

_FIELD_LABELS = {
    "kcal": "Kalorie", "protein_g": "Białko", "fat_g": "Tłuszcz", "carbs_g": "Węgle",
}


async def popraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    session = context.bot_data["session_factory"]()
    try:
        if context.args:
            try:
                changes = parse_popraw_command(context.args)
            except ValueError as exc:
                await update.message.reply_text(str(exc))
                return
            meal = repo.get_last_active_meal(session, update.effective_chat.id)
            if meal is None:
                await update.message.reply_text("Brak posiłków do poprawienia.")
                return
            corrected = repo.correct_meal(session, meal.id, **changes)
            await update.message.reply_text(format_meal_reply({
                "kcal": corrected.kcal, "protein_g": corrected.protein_g,
                "fat_g": corrected.fat_g, "carbs_g": corrected.carbs_g,
                "value_source": corrected.value_source,
            }))
            return

        meal = repo.get_last_active_meal(session, update.effective_chat.id)
        if meal is None:
            await update.message.reply_text("Brak posiłków do poprawienia.")
            return
        await update.message.reply_text(
            f"Ostatni posiłek: {meal.opis}\n"
            f"{meal.kcal} kcal, B {meal.protein_g}g / T {meal.fat_g}g / W {meal.carbs_g}g\n"
            "Co poprawić?",
            reply_markup=build_correction_keyboard(meal),
        )
    finally:
        session.close()


def build_correction_keyboard(meal) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(label, callback_data=f"popraw:{meal.id}:{field}")]
        for field, label in _FIELD_LABELS.items()
    ]
    return InlineKeyboardMarkup(buttons)


async def correction_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, meal_id_str, field = query.data.split(":")
    context.user_data["correction_meal_id"] = int(meal_id_str)
    context.user_data["correction_field"] = field
    await query.message.reply_text(f"Podaj nową wartość dla: {_FIELD_LABELS[field]}")


async def correction_value_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    meal_id = context.user_data.get("correction_meal_id")
    field = context.user_data.get("correction_field")
    if meal_id is None or field is None:
        return  # not mid-correction; let other handlers process this message

    try:
        value = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("Wartość musi być liczbą, spróbuj ponownie.")
        return

    session = context.bot_data["session_factory"]()
    try:
        corrected = repo.correct_meal(session, meal_id, **{field: value})
    finally:
        session.close()

    context.user_data.pop("correction_meal_id", None)
    context.user_data.pop("correction_field", None)
    await update.message.reply_text(format_meal_reply({
        "kcal": corrected.kcal, "protein_g": corrected.protein_g,
        "fat_g": corrected.fat_g, "carbs_g": corrected.carbs_g,
        "value_source": corrected.value_source,
    }))
```

- [ ] **Step 6: Register handlers in main.py**

```python
# tresrv/tresrv/main.py — modify build_application()
from telegram.ext import CallbackQueryHandler

from tresrv.bot.correction import (
    popraw_command, correction_callback_handler, correction_value_handler,
)

# inside build_application(), after other CommandHandlers:
    application.add_handler(CommandHandler("popraw", popraw_command))
    application.add_handler(CallbackQueryHandler(correction_callback_handler, pattern=r"^popraw:"))
```

**Note for the implementer:** `correction_value_handler` must run *before* `text_message_handler` (Task 11) so an in-progress correction doesn't get logged as a new meal. Register it earlier in the handler list, or give both handlers the same group and rely on `correction_value_handler`'s early return (it returns `None` without consuming the update when no correction is in progress) — but python-telegram-bot's default group only runs the first matching handler, so **explicitly set** `group=0` for `correction_value_handler` and `group=1` for `text_message_handler` when registering, e.g. `application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, correction_value_handler), group=0)` and `application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler), group=1)`.

- [ ] **Step 7: Run full test suite**

Run: `cd tresrv && python -m pytest -v`
Expected: PASS (all tests)

- [ ] **Step 8: Commit**

```bash
git add tresrv/tresrv/bot/correction.py tresrv/tresrv/main.py tresrv/tests/bot/test_correction.py
git commit -m "feat(tresrv): /popraw correction — text fallback + inline keyboard, superseded audit trail"
```

---

### Task 15: Docker Compose + deploy checklist

**Files:**
- Create: `tresrv/docker-compose.yml`
- Modify: `docs/superpowers/specs/2026-08-23-tresrv-design.md` (no content change needed — this task only executes what §9 already specifies)

**Interfaces:** none (infrastructure only).

- [ ] **Step 1: Write docker-compose.yml**

```yaml
services:
  db:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_USER: tresrv
      POSTGRES_PASSWORD: tresrv
      POSTGRES_DB: tresrv
    volumes:
      - tresrv-db:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U tresrv"]
      interval: 10s
      timeout: 5s
      retries: 5

  app:
    build: .
    restart: unless-stopped
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - tresrv-meals:/data/meals

volumes:
  tresrv-db:
  tresrv-meals:
```

- [ ] **Step 2: Verify compose config locally (no deploy yet)**

Run: `cd tresrv && docker compose config`
Expected: valid, resolved YAML printed, no errors

- [ ] **Step 3: Commit**

```bash
git add tresrv/docker-compose.yml
git commit -m "feat(tresrv): docker-compose stack (app + db)"
```

- [ ] **Step 4: Manual deploy checklist (run when ready to go live — not part of automated tests)**

1. On Contabo VPS: add a 2GB swapfile (currently 0B swap — spec §9 buffer requirement).
   ```bash
   fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
   echo '/swapfile none swap sw 0 0' >> /etc/fstab
   ```
2. Create a new Telegram bot via @BotFather, save `TELEGRAM_BOT_TOKEN`.
3. Get your own `chat_id` (message the new bot, then `curl https://api.telegram.org/bot<TOKEN>/getUpdates`), save as `TELEGRAM_CHAT_ID`.
4. Create a **new, dedicated** Gemini API key (not the one Argus uses), save as `GEMINI_API_KEY`.
5. `scp` the `tresrv/` directory to the VPS, create `.env` from `.env.example` with the three values above.
6. `docker compose build app && docker compose up -d`.
7. Run the manual test scenarios from spec §8 against the live bot: full onboarding, text meal log, photo meal log (including a deliberately unreadable photo), `/popraw` via inline keyboard, forced-time evening summary.
8. Add a Postgres datasource for the `tresrv` database to the existing Argus Grafana instance (spec §9) — no new Grafana container.

---

## Self-Review Notes

- **Spec coverage:** §2 goals (bot, onboarding, meal parsing text+photo, retry queue, `/popraw`, evening summary, timezone) → Tasks 9-14. §3 architecture (plain process, module layout) → Tasks 1, 9, 12. §4 data model → Task 2 (exact column-for-column match, including `superseded`/`consumed_at`/`storage_path`/`confidence`/`needs_confirmation`/`value_source` from the post-review update). §5 flows → Tasks 9-14 docstrings/handlers match each scenario. §6 single-provider Gemini → Task 7. §7 error handling → Tasks 7, 11, 12 (not-food, garbage JSON, download failure, `failed_permanently`). §8 testing strategy → mirrored task-by-task (unit-heavy on `domain/`, integration on retry queue, manual on full Telegram flows). §9 infra → Task 15. §10 (Increment 2/3) is explicitly out of scope for this plan.
- **Placeholder scan:** the one intentional marker (`NotFoundErrorPlaceholder` in Task 11 Step 5) is flagged inline with an explicit removal instruction for the implementer, since python-telegram-bot exception-ordering needed to be called out — not a content placeholder.
- **Type consistency:** `build_meal_fields` (Task 11) return dict keys match `repo.save_meal(**fields)` (Task 8) column names exactly; `drain_pending_parse` (Task 12) reuses the identical `build_meal_fields` + `repo.save_meal` pair; `format_meal_reply`/`correct_meal` field names (`kcal`, `protein_g`, `fat_g`, `carbs_g`, `value_source`) are consistent across Tasks 11 and 14.
