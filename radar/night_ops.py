"""Timezone-aware overnight operating window (no third-party dependencies).

GitHub Actions schedules are not hard deadlines. This module provides a second,
deterministic window check that scheduled tasks and the controller can share.
"""
from datetime import datetime, timedelta, timezone, time
from zoneinfo import ZoneInfo


def local_now(now, settings):
    return now.astimezone(ZoneInfo(settings.get("timezone", "Europe/Istanbul")))


def clock(value):
    hour, minute = map(int, value.split(":"))
    return time(hour, minute)


def within_night_window(now, settings):
    """Use a half-open local window; supports legacy hour-only configurations."""
    local = local_now(now, settings)
    if not settings.get("start_local") or not settings.get("end_local"):
        return local.hour in settings.get("hours", list(range(7, 24)))
    return clock(settings["start_local"]) <= local.time().replace(tzinfo=None) < clock(settings["end_local"])


def last_expected_slot(now, enabled_at, settings, worker=None):
    """Most recent due slot with the configured startup grace applied.

    In the new schedule each worker's minute is distinct. An expected start
    for W1 at :01 must not falsely make W4 (scheduled at :10) look late.
    """
    grace = timedelta(minutes=settings.get("startup_grace_minutes", 15))
    zone = ZoneInfo(settings.get("timezone", "Europe/Istanbul"))
    local = now.astimezone(zone)
    configured_minutes = settings.get("worker_minutes", {})
    minute = int(configured_minutes.get(str(worker), settings.get("minute", 5)))
    hours = settings.get("hours", list(range(7, 24)))
    result = []
    for offset in (1, 0):
        day = local.date() - timedelta(days=offset)
        for hour in hours:
            slot = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone).astimezone(timezone.utc)
            if enabled_at <= slot <= now - grace:
                result.append(slot)
    return max(result, default=None)


def nightly_boundary(now, settings):
    """The latest Istanbul 07:00 boundary, including yesterday before 07:00."""
    local = local_now(now, settings)
    end = clock(settings.get("end_local", "07:00"))
    boundary = datetime.combine(local.date(), end, tzinfo=local.tzinfo)
    if boundary > local:
        boundary -= timedelta(days=1)
    return boundary.astimezone(timezone.utc)


def daily_report_due(now, settings):
    local = local_now(now, settings)
    return local.time().replace(tzinfo=None) >= clock(settings.get("morning_report_local", "07:15"))
