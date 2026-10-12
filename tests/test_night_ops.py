import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from radar.night_ops import within_night_window, last_expected_slot, daily_report_due
from radar.alert_watch import evaluate
from radar.morning_report import build, render


class NightOperationsTests(unittest.TestCase):
    def setUp(self):
        self.ops = {
            "timezone": "Europe/Istanbul", "hours": list(range(7)),
            "start_local": "00:01", "end_local": "07:00",
            "worker_minutes": {"1": 1, "2": 4, "3": 7, "4": 10, "5": 15},
            "startup_grace_minutes": 15,
            "minimum_completed_receipt_interval_minutes": 30
        }
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, path, obj):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj), encoding="utf-8")

    def when(self, hh, mm):
        # UTC + 3 equals local Istanbul clock on this date.
        return datetime(2026, 10, 12, hh, mm, tzinfo=timezone.utc) - timedelta(hours=3)

    def test_research_window_has_exact_half_open_boundaries(self):
        self.assertFalse(within_night_window(self.when(0, 0), self.ops))
        self.assertTrue(within_night_window(self.when(0, 1), self.ops))
        self.assertTrue(within_night_window(self.when(6, 59), self.ops))
        self.assertFalse(within_night_window(self.when(7, 0), self.ops))
        self.assertTrue(daily_report_due(self.when(7, 15), self.ops))

    def test_worker_start_grace_is_independent_per_worker(self):
        enabled = self.when(0, 0)
        self.assertIsNone(last_expected_slot(self.when(0, 16), enabled, self.ops, worker=4))
        self.assertEqual(last_expected_slot(self.when(0, 16), enabled, self.ops, worker=1), self.when(0, 1))
        self.assertEqual(last_expected_slot(self.when(0, 25), enabled, self.ops, worker=4), self.when(0, 10))

    def test_alert_once_then_recover_without_touching_catalog(self):
        self.write("state/v2/config.json", {"mode": "active", "operations": self.ops})
        self.write("state/v2/health.json", {"unfinished_jobs": 20, "ready_jobs": 20,
            "controller_observed_at": self.when(0, 35).isoformat(),
            "last_verified_progress_at": self.when(0, 1).isoformat(), "stale_after_minutes": 40})
        event, incident, reasons = evaluate(self.root, self.when(0, 36))
        self.assertEqual(event, "opened")
        self.assertEqual(incident["state"], "open")
        self.assertEqual(reasons[0]["code"], "no_verified_activity_30m")
        self.assertEqual(evaluate(self.root, self.when(0, 37))[0], "unchanged")
        self.write("state/v2/health.json", {"unfinished_jobs": 20, "ready_jobs": 20,
            "controller_observed_at": self.when(0, 39).isoformat(),
            "last_verified_progress_at": self.when(0, 39).isoformat(), "stale_after_minutes": 40})
        self.assertEqual(evaluate(self.root, self.when(0, 40))[0], "recovered")

    def test_active_worker_heartbeat_prevents_false_stall_email(self):
        self.write("state/v2/config.json", {"mode": "active", "operations": self.ops})
        self.write("state/v2/health.json", {"unfinished_jobs": 5,
            "controller_observed_at": self.when(0, 35).isoformat(),
            "last_verified_progress_at": self.when(0, 1).isoformat(),
            "workers": {"1": {"last_event": {"at": self.when(0, 35).isoformat()}}},
            "stale_after_minutes": 40})
        self.assertEqual(evaluate(self.root, self.when(0, 36))[0], "unchanged")

    def test_night_end_does_not_fake_recovery(self):
        self.write("state/v2/config.json", {"mode": "active", "operations": self.ops})
        self.write("state/v2/health.json", {"unfinished_jobs": 5,
            "controller_observed_at": self.when(6, 30).isoformat(),
            "last_verified_progress_at": self.when(6, 1).isoformat(),
            "stale_after_minutes": 40})
        self.assertEqual(evaluate(self.root, self.when(6, 45))[0], "opened")
        event, state, _ = evaluate(self.root, self.when(7, 0))
        self.assertEqual(event, "window_closed")
        self.assertEqual(state["state"], "closed_unresolved")

    def test_maintenance_never_opens_a_new_incident(self):
        self.write("state/v2/config.json", {"mode": "maintenance", "operations": self.ops})
        self.assertEqual(evaluate(self.root, self.when(0, 50))[0], "unchanged")

    def test_morning_report_uses_actual_counts_not_assumptions(self):
        self.write("state/v2/config.json", {"mode": "active", "operations": self.ops})
        self.write("state/v2/status.json", {"counts": {"done": 20, "ready": 272},
            "runs": [{"run_id": "2026-10-12-current", "processing_status": "in_progress",
                      "articles_processed": 30, "articles_expected": 1000}]})
        self.write("state/v2/health.json", {"state": "attention_required", "alerts": [],
                      "last_verified_progress_at": self.when(6, 50).isoformat()})
        self.write("docs/status.json", {"source_count": 181, "successful_sources": 180, "failed_sources": 1})
        self.write("docs/latest.json", {"item_count": 1000})
        self.write("state/idea_catalog.json", {"ideas": [{} for _ in range(91)]})
        report = build(self.root, self.when(7, 20))
        self.assertEqual(report["source_success"], 180)
        self.assertEqual(report["catalog_ideas"], 91)
        self.assertFalse(report["research_complete"])
        text = render(report)
        self.assertIn("180/181", text)
        self.assertIn("30 / 1000", text)


if __name__ == "__main__":
    unittest.main()
