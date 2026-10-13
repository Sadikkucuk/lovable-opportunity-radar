import copy
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from radar.engine import Engine, digest, iso
from radar.operations import check_health, due_start


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = datetime(2026, 10, 12, 4, 5, tzinfo=timezone.utc)  # 07:05 Istanbul
        self.e = Engine(self.root, self.now)
        old = {"canonical_key": "preserved", "detail": [None, "original"]}
        files = {}
        for path in ("state/idea_catalog.json", "state/idea_history.json"):
            self.e.write(path, {"ideas": [old]})
            files[path] = {"records": {"preserved": digest(old)}}
        self.e.write("state/v2/protection/baseline.json", {"protected_count": 1, "files": files})
        self.config = {"mode": "active", "shared_queue": True, "operations": {
            "enabled_at": iso(self.now), "timezone": "Europe/Istanbul",
            "hours": list(range(7, 24)), "minute": 5, "startup_grace_minutes": 15,
            "heartbeat_grace_minutes": 20, "progress_grace_minutes": 45,
            "report_after_minutes": 120}}
        self.e.write("state/v2/config.json", self.config)

    def job(self, number=0, run="2026-10-12-current", kind="validation", lane=1):
        payload = {"candidate": {"canonical_key": str(number)}, "source_commit": "a" * 40}
        if kind == "discovery":
            payload = {"articles": [{"article_key": str(number), "content_hash": str(number),
                                     "record": {"url": f"https://example.org/{number}"}}]}
        if kind == "merge":
            payload = {"opportunities": [{"raw_id": str(number)}]}
        key = self.e.add_job(run, kind, payload, lane)
        return self.e.read(f"state/v2/jobs/{key}.json")

    def event(self, worker=1, event="started", invocation=None, at=None):
        invocation = invocation or f"worker-{worker}-invocation-0001"
        name = {"started": "000-started", "progress": "001-progress", "finished": "999-finished", "blocked": "999-blocked"}[event]
        value = {"schema_version": 1, "worker": worker, "invocation_id": invocation,
                 "event": event, "at": iso(at or self.e.now)}
        self.e.write(f"state/v2/worker-events/{worker}/{invocation}/{name}.json", value, immutable=True)
        return invocation

    def claim(self, job, worker=1, attempt=1, at=None, invocation=None):
        at = at or self.e.now
        invocation = invocation or self.event(worker, at=at)
        value = {"schema_version": 3, "job_id": job["job_id"], "input_hash": job["input_hash"],
                 "worker": worker, "invocation_id": invocation, "token": f"worker-{worker}-lease-token-{attempt}",
                 "started_at": iso(at), "expires_at": iso(at + timedelta(minutes=30))}
        self.e.write(f"state/v2/claims/{job['job_id']}/{attempt:03}.json", value, immutable=True)
        return value

    def receipt(self, job, claim, attempt=1, finished=None):
        value = {"schema_version": 2, "job_id": job["job_id"], "input_hash": job["input_hash"],
                 "token": claim["token"], "finished_at": iso(finished or self.e.now),
                 "outcome": "done", "reason": "evidence insufficient",
                 "result": {"decision": "unverified", "reason": "bounded research did not verify"}}
        self.e.write(f"state/v2/results/{job['job_id']}/{attempt:03}.json", value, immutable=True)

    def tick(self):
        self.e.tick("a" * 40, create=False)
        return self.e.read("state/v2/health.json")

    def inbox_jobs(self, worker):
        page = self.e.read(f"state/v2/inbox/worker-{worker}.json")
        revision = page["queue_revision"]
        result = []
        while page:
            self.assertEqual(page["queue_revision"], revision)
            self.assertLessEqual(len(page["jobs"]), 20)
            result.extend(page["jobs"])
            page = self.e.read(page["next_page"]) if page["next_page"] else None
        return result

    def test_all_five_workers_can_take_other_lanes_without_rewriting_jobs(self):
        originals = {}
        for worker in range(1, 6):
            job = self.job(worker, lane=worker % 4 + 1)
            path = f"state/v2/jobs/{job['job_id']}.json"
            originals[path] = (self.root / path).read_bytes()
            claim = self.claim(job, worker)
            self.receipt(job, claim)
            self.assertEqual(self.e.evaluate(job)["state"], "done")
        health = self.tick()
        self.assertTrue(health["all_five_receipt_verified"])
        self.assertFalse(health["alerts"])
        for path, raw in originals.items():
            self.assertEqual((self.root / path).read_bytes(), raw)

    def test_all_four_research_workers_can_claim_after_0700_manually(self):
        # 14:30 Istanbul: outside the automatic night-start window.
        # The window must NOT reject fresh first-writer claims/receipts.
        from radar.night_ops import within_night_window
        self.e.now = datetime(2026, 10, 13, 11, 30, tzinfo=timezone.utc)
        self.config["operations"].update({
            "start_local": "00:01", "end_local": "07:00",
            "hours": list(range(7)), "manual_claims_anytime": True,
            "manual_research_workers": [1, 2, 3, 4],
            "automatic_starts_only_in_night_window": True,
            "claim_cutoff_after_0700": False
        })
        self.e.write("state/v2/config.json", self.config)
        self.assertFalse(within_night_window(self.e.now, self.config["operations"]))
        for worker in range(1, 5):
            with self.subTest(worker=worker):
                job = self.job(100 + worker, lane=(worker % 4) + 1)
                claim = self.claim(job, worker=worker)
                self.e.validate_claim(job, claim)
                self.receipt(job, claim)
                self.assertEqual(self.e.evaluate(job)["state"], "done")
        self.assertEqual(self.e.check_protected(), 1)

    def test_manual_receipt_reconciliation_does_not_create_daytime_news_run(self):
        from radar.night_ops import within_night_window
        self.e.now = datetime(2026, 10, 13, 11, 30, tzinfo=timezone.utc)
        self.config["operations"].update({
            "start_local": "00:01", "end_local": "07:00",
            "hours": list(range(7)), "manual_claims_anytime": True
        })
        self.e.write("state/v2/config.json", self.config)
        job = self.job(222)
        claim = self.claim(job, worker=2)
        self.receipt(job, claim)
        self.assertFalse(within_night_window(self.e.now, self.config["operations"]))
        self.e.tick("a" * 40, create=True)
        self.assertEqual(self.e.evaluate(job)["state"], "done")
        self.assertFalse(self.e.paths("state/v2/runs/2026-10-13*/manifest.json"))
        self.assertEqual(self.e.check_protected(), 1)

    def test_pool_claim_requires_matching_saved_start_and_short_lease(self):
        job = self.job()
        claim = self.claim(job)
        for change in ({"worker": 6}, {"worker": True}, {"invocation_id": "missing-start-000000"},
                       {"expires_at": iso(self.now + timedelta(minutes=90))}):
            with self.subTest(change=change), self.assertRaises((ValueError, KeyError)):
                self.e.validate_claim(job, {**claim, **change})

    def test_expired_pool_lease_can_be_stolen_and_fences_late_result(self):
        job = self.job(lane=4)
        first = self.claim(job, worker=1)
        self.e.now += timedelta(minutes=36)
        self.assertEqual(self.e.evaluate(job)["attempt"], 2)
        second = self.claim(job, worker=5, attempt=2)
        self.receipt(job, first, finished=self.now + timedelta(minutes=20))
        self.assertEqual(self.e.evaluate(job)["state"], "leased")
        self.receipt(job, second, attempt=2)
        state = self.e.evaluate(job)
        self.assertEqual(state["attempt"], 2)
        self.assertEqual(state["state"], "done")

    def test_shared_fair_queue_keeps_today_and_backlog_and_all_phases(self):
        ids = set()
        for group, run in (("current", "2026-10-12-current"), ("backlog", "2026-10-10-migration")):
            for kind in ("merge", "validation", "discovery"):
                for n in range(10):
                    ids.add(self.job(n, run, kind, lane=1)["job_id"])
        self.tick()
        for worker in range(1, 6):
            pending = self.inbox_jobs(worker)
            self.assertEqual({r["job_id"] for r in pending}, ids)
            self.assertEqual(len(pending), len(ids))
            first = pending[:9]
            self.assertEqual([r["queue_group"] for r in first], ["current", "current", "backlog"] * 3)
            self.assertEqual({r["kind"] for r in first}, {"merge", "validation", "discovery"})

    def test_unclaimed_jobs_raise_missing_start_alarm_without_becoming_failed(self):
        job = self.job()
        self.assertFalse(self.tick()["alerts"])
        self.e.now += timedelta(minutes=16)
        health = self.tick()
        missing = [a for a in health["alerts"] if a["code"] == "worker_not_started"]
        self.assertEqual({a["worker"] for a in missing}, {1, 2, 3, 4, 5})
        self.assertEqual(self.e.evaluate(job)["state"], "ready")
        self.assertIsNone(health["capacity"]["estimated_minutes_remaining"])
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(check_health(self.root, self.e.now), 1)
        self.assertIn("Radar müdahale gerekli", output.getvalue())

    def test_schedule_uses_istanbul_and_does_not_invent_night_starts(self):
        night = datetime(2026, 10, 11, 22, tzinfo=timezone.utc)  # next day 01:00
        settings = self.config["operations"]
        self.assertIsNone(due_start(night, night - timedelta(minutes=30), settings))
        self.assertEqual(due_start(self.now + timedelta(minutes=16), self.now, settings), self.now)

    def test_start_marker_does_not_count_as_result_and_stall_is_detected(self):
        self.job()
        self.event(1)
        self.e.now += timedelta(minutes=21)
        health = self.tick()
        self.assertFalse(health["workers"]["1"]["write_and_receipt_verified"])
        self.assertIn("worker_heartbeat_missing", {a["code"] for a in health["alerts"] if a["worker"] == 1})
        self.e.now += timedelta(minutes=25)
        self.assertIn("queue_no_progress", {a["code"] for a in self.tick()["alerts"]})

    def test_finished_without_receipt_is_visible_even_when_scheduler_says_done(self):
        self.job()
        invocation = self.event()
        self.e.now += timedelta(seconds=30)
        self.event(event="finished", invocation=invocation)
        health = self.tick()
        self.assertIn("worker_finished_without_receipt", {a["code"] for a in health["alerts"]})

    def test_empty_queue_does_not_alarm_about_idle_workers(self):
        self.e.now += timedelta(hours=2)
        health = self.tick()
        self.assertFalse(health["alerts"])
        self.assertEqual(health["state"], "idle")

    def test_probe_monitors_outside_schedule_and_reports_two_hours_without_closing_jobs(self):
        self.e.now = datetime(2026, 10, 11, 22, tzinfo=timezone.utc)
        self.config["operations"]["enabled_at"] = iso(self.e.now)
        self.config["operations"]["startup_probe"] = {"requested_at": iso(self.e.now)}
        self.e.write("state/v2/config.json", self.config)
        job = self.job()
        self.e.now += timedelta(minutes=16)
        self.assertEqual(len([a for a in self.tick()["alerts"] if a["code"] == "worker_not_started"]), 5)
        self.e.now += timedelta(minutes=105)
        health = self.tick()
        report = self.e.read(health["report_windows"][0]["report_path"])
        self.assertEqual(report["counts"], {"ready": 1})
        self.assertFalse(report["research_complete"])
        self.assertEqual(self.e.evaluate(job)["state"], "ready")
        before = copy.deepcopy(report)
        self.e.now += timedelta(minutes=10)
        self.tick()
        self.assertEqual(before, self.e.read(health["report_windows"][0]["report_path"]))

    def test_daily_two_hour_report_starts_at_first_worker_slot_not_midnight(self):
        self.e.now = self.now.replace(hour=0, minute=0)
        self.config["operations"]["enabled_at"] = iso(self.e.now)
        self.e.write("state/v2/config.json", self.config)
        self.e.write("docs/latest.json", {"items": [{"url": "https://example.org/today"}]})
        self.e.tick("a" * 40)
        health = self.e.read("state/v2/health.json")
        self.assertEqual(health["report_windows"][0]["target_at"], "2026-10-12T06:05:00Z")
        self.assertIsNone(health["report_windows"][0]["report_path"])

    def test_future_or_malformed_event_cannot_forge_worker_health(self):
        self.job()
        self.event(at=self.now + timedelta(hours=1))
        health = self.tick()
        self.assertIsNone(health["workers"]["1"]["last_started_at"])
        self.assertIn("invalid_worker_event", {a["code"] for a in health["alerts"]})

    def test_live_long_invocation_is_not_mistaken_for_missing_start(self):
        self.job()
        invocation = self.event()
        self.e.now += timedelta(hours=1, minutes=16)
        self.event(event="progress", invocation=invocation)
        health = self.tick()
        self.assertNotIn("worker_not_started", {a["code"] for a in health["alerts"] if a["worker"] == 1})

    def test_upgrade_after_daily_snapshot_still_reports_today(self):
        self.e.write("docs/latest.json", {"items": [{"url": "https://example.org/today"}]})
        self.e.create_run("a" * 40)
        self.e.now += timedelta(minutes=20)
        self.config["operations"]["enabled_at"] = iso(self.e.now)
        self.e.write("state/v2/config.json", self.config)
        health = self.tick()
        self.assertEqual(health["report_windows"][0]["target_at"], iso(self.e.now + timedelta(hours=2)))

    def test_health_reader_detects_controller_stopped_running(self):
        self.tick()
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(check_health(self.root, self.now + timedelta(minutes=41)), 1)
        self.assertIn("controller_stale", output.getvalue())

    def test_queue_pages_change_revision_and_remove_only_stale_derived_pages(self):
        for n in range(21):
            self.job(n)
        self.tick()
        revision = self.e.read("state/v2/inbox/worker-1.json")["queue_revision"]
        self.assertTrue(self.e.paths("state/v2/inbox/worker-1-page-*.json"))
        job = next(iter(self.e.jobs().values()))
        claim = self.claim(job)
        # A rejected job becomes terminal without creating an evidence
        # followup; an unverified validation would correctly replace itself
        # with a ready followup and keep this second inbox page populated.
        self.e.write(f"state/v2/results/{job['job_id']}/001.json", {
            "schema_version": 2, "job_id": job["job_id"],
            "input_hash": job["input_hash"], "token": claim["token"],
            "finished_at": iso(self.e.now), "outcome": "rejected",
            "reason": "ineligible", "result": {}
        }, immutable=True)
        self.tick()
        self.assertNotEqual(revision, self.e.read("state/v2/inbox/worker-1.json")["queue_revision"])
        self.assertFalse(self.e.paths("state/v2/inbox/worker-1-page-*.json"))
        self.assertEqual(len(self.inbox_jobs(1)), 20)
        self.assertTrue(self.e.read(f"state/v2/results/{job['job_id']}/001.json"))

    def test_extended_checkpoint_protects_post_baseline_ideas(self):
        rows = self.e.read("state/idea_catalog.json")
        extra = {"canonical_key": "recent", "detail": None}
        rows["ideas"].append(extra)
        self.e.write("state/idea_catalog.json", rows)
        self.e.write("state/v2/protection/checkpoints/upgrade.json", {"files": {
            "state/idea_catalog.json": {"records": {"recent": digest(extra)}}}})
        self.e.check_protected()
        rows["ideas"][1]["detail"] = "changed"
        self.e.write("state/idea_catalog.json", rows)
        with self.assertRaises(ValueError):
            self.e.check_protected()


if __name__ == "__main__":
    unittest.main()
