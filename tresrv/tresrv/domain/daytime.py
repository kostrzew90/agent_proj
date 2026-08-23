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
