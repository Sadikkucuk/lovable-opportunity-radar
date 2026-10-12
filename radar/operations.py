"""Shared scheduling and observable progress, without another service or database.

Health is separate from research state: a missing start never becomes a failed
research decision. Reports at the two-hour boundary never close unfinished jobs.
"""
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from radar.engine import TERMINAL, POOL_LEASE_MINUTES, dt, iso


def interleave(buckets, cycle):
    queues = {k: deque(v) for k, v in buckets.items()}
    result = []
    while any(queues.values()):
        for key in cycle:
            if queues[key]:
                result.append(queues[key].popleft())
    return result


def fair_order(records, worker):
    groups = {}
    for group in ("current", "backlog"):
        kinds = {}
        for kind in ("merge", "validation", "discovery"):
            subset = [r for r in records if r["queue_group"] == group and r["kind"] == kind]
            # Different first choices, but EVERY worker can eventually take EVERY
            # job. A preferred worker is a collision hint, never an ownership lock.
            kinds[kind] = sorted(subset, key=lambda r: (
                r["preferred_worker"] != worker, r["run_id"], r["job_id"]))
        groups[group] = interleave(kinds, ("merge", "validation", "discovery"))
    return interleave(groups, ("current", "current", "backlog"))


def write_inboxes(e, jobs, states, config):
    manifests = [e.read(p) for p in e.paths("state/v2/runs/*/manifest.json")]
    daily = [m["run_id"] for m in manifests if m["kind"] == "daily"]
    current = max(daily, default=max((j["run_id"] for j in jobs.values()), default=None))
    records = []
    for key, job in jobs.items():
        if states[key]["state"] in TERMINAL:
            continue
        records.append({"job_id": key, "path": f"state/v2/jobs/{key}.json",
                        "run_id": job["run_id"], "kind": job["kind"],
                        "input_hash": job["input_hash"], "legacy_lane": job["lane"],
                        "queue_group": "current" if job["run_id"] == current else "backlog",
                        "preferred_worker": int(job["input_hash"][:8], 16) % 5 + 1,
                        **states[key]})
    shared = config.get("shared_queue", False)
    for worker in range(1, 6):
        eligible = records if shared else [r for r in records if r["legacy_lane"] == worker]
        ready = [r for r in eligible if r["state"] == "ready"]
        waiting = sorted((r for r in eligible if r["state"] != "ready"), key=lambda r: r["job_id"])
        ordered = fair_order(ready, worker) + waiting if shared else sorted(eligible, key=lambda r: (r["run_id"], r["job_id"]))
        inbox = {"schema_version": 3 if shared else 2, "lane": worker,
                 "queue_mode": "shared" if shared else "legacy",
                 "current_run": current, "lease_minutes": POOL_LEASE_MINUTES if shared else 90,
                 "ready_count": len(ready), "jobs": ordered}
        e.write(f"state/v2/inbox/worker-{worker}.json", inbox)
        if worker == 1 and shared:
            e.write("state/v2/queue.json", {k: v for k, v in inbox.items() if k != "lane"})


def read_events(e, enabled_at):
    events, invalid = [], []
    for path in e.paths("state/v2/worker-events/*/*/*.json"):
        try:
            event = e.read(path)
            worker, invocation, name = path.split("/")[-3:]
            if (type(event["worker"]) is not int or str(event["worker"]) != worker
                    or event["worker"] not in range(1, 6)
                    or event["invocation_id"] != invocation
                    or not re.fullmatch(r"[a-zA-Z0-9_-]{16,80}", invocation)
                    or event["event"] not in {"started", "progress", "finished", "blocked"}
                    or (event["event"] == "started") != (name == "000-started.json")):
                raise ValueError("invalid event identity")
            at = dt(event["at"])
            if at > e.now + timedelta(minutes=5):
                raise ValueError("future event")
            if at >= enabled_at:
                events.append({**event, "path": path})
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            invalid.append({"path": path, "reason": str(exc)})
    return sorted(events, key=lambda event: (event["at"], event["path"])), invalid


def due_start(now, enabled_at, settings):
    """Last scheduled slot whose startup grace has elapsed, or the live probe.

    No expectation is invented before deployment. Local time comes from the
    same explicit schedule saved into the five existing ChatGPT tasks.
    """
    grace = timedelta(minutes=settings.get("startup_grace_minutes", 15))
    zone = ZoneInfo(settings.get("timezone", "Europe/Istanbul"))
    local = now.astimezone(zone)
    slots = []
    for day_offset in (1, 0):
        day = local.date() - timedelta(days=day_offset)
        for hour in settings.get("hours", list(range(7, 24))):
            slot = datetime(day.year, day.month, day.day, hour, settings.get("minute", 5), tzinfo=zone).astimezone(timezone.utc)
            if enabled_at <= slot <= now - grace:
                slots.append(slot)
    probe = settings.get("startup_probe")
    if probe and enabled_at <= dt(probe["requested_at"]) <= now - grace:
        slots.append(dt(probe["requested_at"]))
    return max(slots, default=None)


def observed_receipts(e, jobs, states):
    records = []
    for key, state in states.items():
        # Reuse is useful but not new research capacity. Only accepted receipts
        # count; a worker's self-reported totals do not prove persistence.
        if state["state"] not in TERMINAL or not state.get("receipt") or state.get("reused"):
            continue
        receipt = state["receipt"]
        claim = e.read(f"state/v2/claims/{key}/{state['attempt']:03}.json")
        records.append({"job_id": key, "kind": jobs[key]["kind"], "worker": claim["worker"],
                        "invocation_id": claim.get("invocation_id"),
                        "started_at": claim["started_at"], "finished_at": receipt["finished_at"],
                        "outcome": receipt["outcome"], "receipt_path": state["receipt_path"]})
    return records


def capacity(e, jobs, states, receipts, enabled_at):
    start = max(enabled_at, e.now - timedelta(minutes=120))
    minutes = max(0, (e.now - start).total_seconds() / 60)
    stages = {}
    for kind in ("discovery", "merge", "validation"):
        completed = [r for r in receipts if r["kind"] == kind and dt(r["finished_at"]) >= start]
        pending = sum(j["kind"] == kind and states[k]["state"] not in TERMINAL for k, j in jobs.items())
        rate = len(completed) / minutes if minutes >= 15 and len(completed) >= 3 else None
        stages[kind] = {"completed_in_window": len(completed), "known_remaining": pending,
                        "observed_jobs_per_hour": round(rate * 60, 2) if rate else None,
                        "estimated_minutes_for_stage": round(pending / rate, 1) if rate else (0 if not pending else None)}
    downstream_unknown = any(stages[k]["known_remaining"] for k in ("discovery", "merge"))
    estimates = [s["estimated_minutes_for_stage"] for s in stages.values()]
    eta = sum(estimates) if not downstream_unknown and all(x is not None for x in estimates) else None
    return {"window_minutes": round(minutes, 1), "stages": stages,
            "estimated_minutes_remaining": round(eta, 1) if eta is not None else None,
            "estimate_reason": "downstream_work_unknown" if downstream_unknown else ("insufficient_observations" if eta is None else "observed_rate_not_a_guarantee")}


def report_windows(e, settings, status):
    windows = []
    minutes = settings.get("report_after_minutes", 120)
    probe = settings.get("startup_probe")
    if probe:
        windows.append(("deployment-" + dt(probe["requested_at"]).strftime("%Y%m%dT%H%M%SZ"), dt(probe["requested_at"])))
    zone = ZoneInfo(settings.get("timezone", "Europe/Istanbul"))
    enabled_at = dt(settings["enabled_at"])
    for path in e.paths("state/v2/runs/*/manifest.json"):
        manifest = e.read(path)
        if manifest["kind"] != "daily" or manifest["run_date"] < enabled_at.astimezone(zone).date().isoformat():
            continue
        day = datetime.fromisoformat(manifest["run_date"]).date()
        first_slot = datetime(day.year, day.month, day.day, min(settings.get("hours", [7])), settings.get("minute", 5), tzinfo=zone)
        start = max(first_slot.astimezone(timezone.utc), dt(manifest["created_at"]), enabled_at)
        windows.append((manifest["run_id"], start))
    summaries = []
    for window_id, start in windows:
        deadline = start + timedelta(minutes=minutes)
        path = f"state/v2/windows/{window_id}.json"
        report = e.read(path)
        if e.now >= deadline and not report:
            report = {"schema_version": 1, "window_id": window_id, "started_at": iso(start),
                      "target_at": iso(deadline), "observed_at": iso(e.now),
                      "scheduler_delay_minutes": round((e.now - deadline).total_seconds() / 60, 1),
                      "research_complete": not any(count for state, count in status["counts"].items() if state not in TERMINAL),
                      "counts": status["counts"], "runs": status["runs"],
                      "catalog_count": status["catalog_count"],
                      "publication": e.read("docs/radar/current.json"),
                      "unfinished_work": "continues_automatically_no_candidates_discarded"}
            e.write(path, report, immutable=True)
        summaries.append({"window_id": window_id, "target_at": iso(deadline),
                          "report_path": path if report else None,
                          "state": "reported" if report else "scheduled"})
    return summaries


def reconcile_health(e, jobs, states, config, status):
    settings = config.get("operations")
    if not settings:
        return
    enabled_at = dt(settings["enabled_at"])
    events, invalid = read_events(e, enabled_at)
    receipts = observed_receipts(e, jobs, states)
    expected = due_start(e.now, enabled_at, settings)
    unfinished = sum(s["state"] not in TERMINAL for s in states.values())
    ready = sum(s["state"] == "ready" for s in states.values())
    zone = ZoneInfo(settings.get("timezone", "Europe/Istanbul"))
    scheduled_hours = settings.get("hours", list(range(7, 24)))
    active = e.now.astimezone(zone).hour in scheduled_hours
    probe = settings.get("startup_probe")
    if probe:
        probe_start = dt(probe["requested_at"])
        active |= probe_start <= e.now <= probe_start + timedelta(minutes=settings.get("report_after_minutes", 120))
    alerts, workers = [], {}

    def alert(code, worker=None, action="Görev geçmişindeki hata veya bağlantı/onay isteğini kontrol edin."):
        alerts.append({"code": code, "worker": worker, "severity": "critical", "user_action": action})

    for worker in range(1, 6):
        own = [event for event in events if event["worker"] == worker]
        starts = [event for event in own if event["event"] == "started"]
        start = starts[-1] if starts else None
        invocation = start["invocation_id"] if start else None
        invocation_events = [event for event in own if event["invocation_id"] == invocation] if start else []
        last = invocation_events[-1] if invocation_events else None
        saved = [r for r in receipts if r["worker"] == worker and r["invocation_id"] == invocation] if start else []
        verified = [r for r in receipts if r["worker"] == worker and r["invocation_id"] and dt(r["finished_at"]) >= enabled_at]
        workers[str(worker)] = {"last_started_at": start["at"] if start else None,
                                "last_event": last, "receipts_this_invocation": len(saved),
                                "write_and_receipt_verified": bool(verified),
                                "last_receipt_at": max((r["finished_at"] for r in verified), default=None)}
        alive = last and last["event"] == "progress" and e.now - dt(last["at"]) <= timedelta(minutes=settings.get("heartbeat_grace_minutes", 20))
        if unfinished and expected and not alive and (not start or dt(start["at"]) < expected - timedelta(minutes=5)):
            alert("worker_not_started", worker)
        if last and last["event"] == "blocked" and unfinished:
            alert("worker_blocked", worker)
        if active and unfinished and last and last["event"] not in {"finished", "blocked"}:
            if e.now - dt(last["at"]) > timedelta(minutes=settings.get("heartbeat_grace_minutes", 20)):
                alert("worker_heartbeat_missing", worker)
        if active and ready and last and last["event"] == "finished" and not saved:
            alert("worker_finished_without_receipt", worker)
    recent = [dt(r["finished_at"]) for r in receipts if dt(r["finished_at"]) >= enabled_at]
    # Avoid an immediate false alarm on a new work day after an overnight pause.
    local = e.now.astimezone(zone)
    first_today = local.replace(hour=min(scheduled_hours), minute=settings.get("minute", 5), second=0, microsecond=0).astimezone(timezone.utc)
    active_start = max(enabled_at, first_today) if e.now >= first_today else enabled_at
    if probe and dt(probe["requested_at"]) <= e.now:
        active_start = max(active_start, dt(probe["requested_at"]))
    last_progress = max(recent + [active_start])
    if active and unfinished and e.now - last_progress > timedelta(minutes=settings.get("progress_grace_minutes", 45)):
        alert("queue_no_progress", action="Diğer çalışanlar kuyruğu devralır; görev geçmişinde erişim/kota hatası varsa belirtilen işlemi tamamlayın.")
    if invalid:
        alert("invalid_worker_event", action="Geçersiz başlangıç/ilerleme kaydı onarılmalı; araştırma kayıtları korunuyor.")
    if status["errors"]:
        alert("controller_rejected_record", action="Durum raporundaki hatalı kayıt incelenmeli; doğrulanmış fikirler yayında kalır.")
    windows = report_windows(e, settings, status)
    health = {"schema_version": 1, "controller_observed_at": iso(e.now),
              "stale_after_minutes": 40,
              "state": "attention_required" if alerts else ("observing" if unfinished else "idle"),
              "expected_start_at": iso(expected) if expected else None,
              "ready_jobs": ready, "unfinished_jobs": unfinished,
              "last_verified_progress_at": iso(max(recent)) if recent else None,
              "workers": workers, "all_five_receipt_verified": all(w["write_and_receipt_verified"] for w in workers.values()),
              "capacity": capacity(e, jobs, states, receipts, enabled_at),
              "report_windows": windows, "alerts": alerts, "invalid_events": invalid}
    e.write("state/v2/health.json", health)


def check_health(root=".", now=None):
    """Actions annotations + task summary; delivery depends on account settings."""
    now = now or datetime.now(timezone.utc)
    root = Path(root)
    config = json.loads((root / "state/v2/config.json").read_text())
    if config.get("mode") != "active" or not config.get("operations"):
        return 0
    path = root / "state/v2/health.json"
    if not path.exists():
        print("::error title=Radar müdahale gerekli::Sağlık kaydı yok; controller çalışmasını kontrol edin.")
        return 1
    health = json.loads(path.read_text())
    alerts = list(health["alerts"])
    if now - dt(health["controller_observed_at"]) > timedelta(minutes=health["stale_after_minutes"]):
        alerts.append({"code": "controller_stale", "worker": None, "user_action": "GitHub Actions controller çalışmasını kontrol edin."})
    summary = ["## Radar çalışma durumu", f"Kalıcı sonucu doğrulanan çalışan: {sum(w['write_and_receipt_verified'] for w in health['workers'].values())}/5",
               f"Bekleyen iş: {health['unfinished_jobs']}", f"Son kontrol: {health['controller_observed_at']}"]
    for alert in alerts:
        label = f"{alert['code']} (worker={alert.get('worker')})"
        print(f"::error title=Radar müdahale gerekli::{label}: {alert['user_action']}")
        summary.append(f"- {label}: {alert['user_action']}")
    summary.append("İki saat bir raporlama hedefidir; bitmeyen araştırmalar devam eder. Bildirim teslimi hesap ayarlarına bağlıdır.")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as output:
            output.write("\n".join(summary) + "\n")
    print(json.dumps({"alerts": len(alerts), "state": health["state"]}))
    return 1 if alerts else 0


if __name__ == "__main__":
    raise SystemExit(check_health())
