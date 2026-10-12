"""Incident-deduplicated watchdog for night research.

A GitHub Actions failure is emitted only on a NEW incident, not every five
minutes during the same outage. Notification delivery requires the account's
GitHub Actions email notification setting; no external service is assumed.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from radar.engine import dt, iso
from radar.night_ops import within_night_window


INCIDENT = "state/v2/alerts/night-stall.json"


def evaluate(root, now):
    root = Path(root)
    config = json.loads((root / "state/v2/config.json").read_text(encoding="utf-8"))
    settings = config.get("operations", {})
    active = config.get("mode") == "active" and within_night_window(now, settings)
    existing_path = root / INCIDENT
    existing = json.loads(existing_path.read_text(encoding="utf-8")) if existing_path.exists() else {}
    health_path = root / "state/v2/health.json"
    health = json.loads(health_path.read_text(encoding="utf-8")) if health_path.exists() else {}
    reasons = []
    if active and health.get("unfinished_jobs", 0) > 0:
        zone = ZoneInfo(settings.get("timezone", "Europe/Istanbul"))
        local = now.astimezone(zone)
        start_hour, start_minute = map(int, settings.get("start_local", "00:01").split(":"))
        start = datetime(local.year, local.month, local.day, start_hour, start_minute, tzinfo=zone).astimezone(timezone.utc)
        latest = health.get("last_verified_progress_at")
        last = dt(latest) if latest else start
        reference = max(last, start)
        if now - reference >= timedelta(minutes=settings.get("minimum_completed_receipt_interval_minutes", 30)):
            reasons.append({"code": "no_verified_result_30m", "since": iso(reference),
                            "elapsed_minutes": int((now-reference).total_seconds()//60)})
        seen = health.get("controller_observed_at")
        if not seen or now - dt(seen) > timedelta(minutes=health.get("stale_after_minutes", 40)):
            reasons.append({"code": "controller_stale", "last_seen": seen})
    if reasons and existing.get("state") != "open":
        new = {"schema_version": 1, "state": "open", "opened_at": iso(now),
               "reason_codes": [r["code"] for r in reasons], "evidence": reasons,
               "latest_health_ref": "state/v2/health.json",
               "manual_next_step": "Inspect the exact worker task execution history and GitHub health/logs. Do not invent a quota/auth cause."}
        event = "opened"
    elif not reasons and existing.get("state") == "open":
        new = {**existing, "state": "recovered", "recovered_at": iso(now)}
        event = "recovered"
    else:
        return "unchanged", existing, reasons
    existing_path.parent.mkdir(parents=True, exist_ok=True)
    existing_path.write_text(json.dumps(new, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return event, new, reasons


def main():
    now = datetime.now(timezone.utc)
    event, incident, reasons = evaluate(".", now)
    if event == "opened":
        print("::error title=Radar 30-minute stalled queue::" + json.dumps(reasons, ensure_ascii=False))
    elif event == "recovered":
        print("::notice title=Radar recovered::Verified work resumed or the night window closed.")
    else:
        print("Radar watchdog: no incident transition")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Radar night watchdog\n\nEvent: "+event+"\n\n"+json.dumps(incident, ensure_ascii=False, indent=2)+"\n")
    return 1 if event == "opened" else 0


if __name__ == "__main__":
    raise SystemExit(main())
