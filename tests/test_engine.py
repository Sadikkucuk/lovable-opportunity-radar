import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from radar.engine import Engine, POLICY, digest, iso, article_key, article_signature


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = datetime(2026, 10, 10, 17, tzinfo=timezone.utc)
        self.e = Engine(self.root, self.now)
        self.old = {"canonical_key": "old|job|mechanism", "idea_name": "Original", "unknown": None, "details": {"a": [1, 2, 3]}}
        files = {}
        for p in ("state/idea_catalog.json", "state/idea_history.json"):
            self.e.write(p, {"ideas": [self.old], "schema_version": 1})
            files[p] = {"records": {self.old["canonical_key"]: digest(self.old)}}
        self.e.write("state/v2/protection/baseline.json", {"protected_count": 1, "files": files})
        self.e.write("state/v2/config.json", {"mode": "active"})

    def validation(self, key="new|job|mechanism"):
        candidate = {"canonical_key": key, "idea_name": "New", "core_job": "job", "target_customer": "buyer", "product_mechanism": "rule"}
        jid = self.e.add_job("2026-10-10-test", "validation", {"candidate": candidate, "source_commit": "a"*40}, 1)
        return self.e.read(f"state/v2/jobs/{jid}.json")

    def qualified(self, job):
        idea = {k: "Turkish detail" for k in ("idea_name", "scope_reason", "news_source", "news_title", "core_idea", "user_story", "before_state", "after_state", "target_customer", "mvp", "working_logic", "marketing_strategy")}
        idea.update({"canonical_key": job["payload"]["candidate"]["canonical_key"], "scope_tier": "Türkiye", "news_url": "https://example.org/news",
                     "business_models": ["license"], "technologies": ["browser"], "turkiye_direct_competitor_count": 0, "global_direct_competitor_count": 0,
                     "lovable_credits_total": 2000, "external_cash_cost": None, "verification_status": "qualified", "status": "published"})
        return {"decision": "qualified", "reason": "reason", "catalog_record": idea,
                "evidence": [{"role": r, "url": "https://example.org/"+r, "accessed_at": iso(self.now), "claim": "claim", "observation": "observed", "page_read": True, "support": "supported"} for r in ("trigger", "competition_tr", "competition_global", "feasibility")],
                "competition": {m: {"direct_count": 0, "queries": ["query"], "scope": "scope", "search_complete": True, "direct_competitors": []} for m in ("tr", "global")},
                "feasibility": {"runtime_external_api": False, "runtime_external_database": False, "runtime_ai_agent_or_model": False, "architecture": "local", "dependency_inventory": ["browser"]},
                "history_review": {"decision": "new", "reason": "reason"}}

    def claim(self, job, attempt=1, started=None):
        started = started or self.now
        c = {"schema_version": 2, "job_id": job["job_id"], "input_hash": job["input_hash"], "worker": job["lane"], "token": f"unique-token-{attempt}-123456", "started_at": iso(started), "expires_at": iso(started+timedelta(minutes=90))}
        self.e.write(f"state/v2/claims/{job['job_id']}/{attempt:03}.json", c, immutable=True)
        return c

    def receipt(self, job, result=None, outcome="done", attempt=1, claim=None, finished=None):
        c = claim or self.claim(job, attempt)
        r = {"schema_version": 2, "job_id": job["job_id"], "input_hash": job["input_hash"], "token": c["token"], "finished_at": iso(finished or self.now), "outcome": outcome, "reason": "recorded reason", "result": result or {"decision": "unverified", "reason": "insufficient evidence"}}
        self.e.write(f"state/v2/results/{job['job_id']}/{attempt:03}.json", r, immutable=True)
        return r

    def test_protected_field_change_or_deletion_rejected(self):
        self.assertEqual(self.e.check_protected(), 1)
        self.e.write("state/idea_catalog.json", {"ideas": [{**self.old, "unknown": 0}]})
        with self.assertRaises(ValueError): self.e.check_protected()
        self.e.write("state/idea_catalog.json", {"ideas": []})
        with self.assertRaises(ValueError): self.e.check_protected()

    def test_snapshot_frozen_and_ten_article_units(self):
        self.e.write("docs/latest.json", {"items": [{"id": str(n), "url": f"https://example.org/{n}", "title": str(n)} for n in range(23)]})
        self.e.create_run("a"*40)
        first = self.e.paths("state/v2/runs/*/snapshot.json")
        snapshot = self.e.read(first[0])
        self.e.write("docs/latest.json", {"items": [{"url": "https://example.org/new"}]})
        self.e.create_run("b"*40)
        self.assertEqual(self.e.paths("state/v2/runs/*/snapshot.json"), first)
        self.assertEqual(self.e.read(first[0]), snapshot)
        self.assertEqual(sorted(len(j["payload"]["articles"]) for j in self.e.jobs().values()), [3,10,10])

    def test_url_identity_stable_and_content_changes(self):
        a = {"url": "https://example.org/a?utm_source=x", "title": "one"}
        b = {"url": "https://example.org/a", "title": "two"}
        self.assertEqual(article_key(a), article_key(b))
        self.assertNotEqual(article_signature(a), article_signature(b))

    def test_worker_crash_and_late_result_fencing(self):
        j = self.validation()
        first = self.claim(j, started=self.now-timedelta(hours=2))
        self.assertEqual(self.e.evaluate(j)["attempt"], 2)
        second = self.claim(j, 2)
        self.receipt(j, claim=first, finished=self.now-timedelta(minutes=45))
        self.assertEqual(self.e.evaluate(j)["state"], "leased")
        self.receipt(j, attempt=2, claim=second)
        self.assertEqual(self.e.evaluate(j)["state"], "done")

    def test_claim_cannot_be_overwritten(self):
        j = self.validation(); c = self.claim(j)
        with self.assertRaises(ValueError):
            self.e.write(f"state/v2/claims/{j['job_id']}/001.json", {**c, "token": "another-token"}, immutable=True)

    def test_three_failures_do_not_become_qualified(self):
        j = self.validation()
        for n in range(1,4): self.claim(j, n, started=self.now-timedelta(hours=12-n))
        self.assertEqual(self.e.evaluate(j)["state"], "failed")
        self.e.tick("a"*40, create=False)
        self.assertEqual(len(self.e.read("state/idea_catalog.json")["ideas"]), 1)

    def test_retry_backoff(self):
        j = self.validation(); self.receipt(j, outcome="retry")
        self.assertEqual(self.e.evaluate(j)["state"], "retry_wait")
        self.e.now += timedelta(minutes=6)
        self.assertEqual(self.e.evaluate(j)["attempt"], 2)

    def test_wrong_generation_and_unknowns_rejected(self):
        j = self.validation(); good = self.qualified(j)
        self.e.validate_qualification(j, good)
        for mutation in ("count", "database", "evidence", "identity"):
            bad = copy.deepcopy(good)
            if mutation == "count": bad["competition"]["tr"]["direct_count"] = None
            if mutation == "database": bad["feasibility"]["runtime_external_database"] = None
            if mutation == "evidence": bad["evidence"][0]["page_read"] = False
            if mutation == "identity": bad["catalog_record"]["canonical_key"] = "other"
            with self.assertRaises(ValueError): self.e.validate_qualification(j, bad)
        j["input_hash"] = "wrong"
        self.assertEqual(self.e.evaluate(j)["state"], "failed")

    def test_one_bad_candidate_does_not_block_good_and_repeat_is_idempotent(self):
        good, bad = self.validation(), self.validation("other|job|mechanism")
        self.receipt(good, self.qualified(good)); self.receipt(bad)
        self.e.tick("a"*40, create=False)
        catalog = (self.root/"state/idea_catalog.json").read_bytes()
        self.e.tick("b"*40, create=False)
        self.assertEqual(catalog, (self.root/"state/idea_catalog.json").read_bytes())
        self.assertEqual(len(self.e.read("state/idea_catalog.json")["ideas"]), 2)
        self.assertEqual(self.e.read("state/idea_catalog.json")["ideas"][0], self.old)
        payload = self.e.read(self.e.read("docs/radar/current.json")["path"])
        self.assertEqual(payload["ideas"][0]["canonical_key"], self.old["canonical_key"])
        self.assertIsNone(payload["ideas"][1]["external_cash_cost"])

    def test_duplicate_never_updates_original(self):
        j = self.validation(self.old["canonical_key"]); self.receipt(j, self.qualified(j))
        self.e.tick("a"*40, create=False)
        self.assertEqual(self.e.read("state/idea_catalog.json")["ideas"], [self.old])

    def test_midnight_keeps_old_work(self):
        j = self.validation(); self.e.now += timedelta(days=1)
        self.e.tick("b"*40, create=False)
        inbox = self.e.read("state/v2/inbox/worker-1.json")
        self.assertEqual(inbox["jobs"][0]["job_id"], j["job_id"])

    def test_malformed_receipt_is_retried_not_global_crash(self):
        j = self.validation(); self.claim(j)
        self.e.write(f"state/v2/results/{j['job_id']}/001.json", {"wrong": True})
        self.e.tick("a"*40, create=False)
        self.assertEqual(self.e.evaluate(j)["attempt"], 2)

    def test_same_candidate_reuses_valid_research_without_resetting_ttl(self):
        j = self.validation(); self.receipt(j)
        self.e.tick("a"*40, create=False)
        jid = self.e.add_job("2026-10-11-new", "validation", j["payload"], 1)
        reused = self.e.read(f"state/v2/jobs/{jid}.json")
        self.assertTrue(self.e.evaluate(reused)["reused"])
        self.e.now += timedelta(days=2)
        jid2 = self.e.add_job("2026-10-13-new", "validation", j["payload"], 1)
        self.assertNotIn("reuse", self.e.read(f"state/v2/jobs/{jid2}.json"))

    def test_receipt_remains_valid_after_time_passes_but_unpublished_stale_proof_is_held(self):
        j = self.validation(); self.receipt(j, self.qualified(j))
        self.e.now += timedelta(days=10)
        self.assertEqual(self.e.evaluate(j)["state"], "done")
        self.e.tick("a"*40, create=False)
        self.assertEqual(len(self.e.read("state/idea_catalog.json")["ideas"]), 1)

    def test_merge_cannot_silently_drop_raw_opportunities(self):
        j = {"kind": "merge", "payload": {"opportunities": [{"raw_id": "one"}, {"raw_id": "two"}]}}
        with self.assertRaises(ValueError):
            self.e.validate_result(j, {"cross_article_review_completed": True, "candidates": [], "suppressed": [{"source_raw_ids": ["one"], "reason": "reason"}]})

    def test_maintenance_preserves_last_release(self):
        self.e.tick("a"*40, create=False)
        before = (self.root/"docs/radar/current.json").read_bytes()
        self.e.write("state/v2/config.json", {"mode": "maintenance"})
        self.e.tick("b"*40)
        self.assertEqual(before, (self.root/"docs/radar/current.json").read_bytes())

    def test_end_to_end_discovery_merge_validation_publication(self):
        self.e.write("docs/latest.json", {"items": [{"url": "https://example.org/article", "title": "trigger"}]})
        self.e.tick("a"*40)
        discovery = next(j for j in self.e.jobs().values() if j["kind"] == "discovery")
        article = discovery["payload"]["articles"][0]
        raw = {k: k for k in ("raw_id", "canonical_key", "idea_name", "core_job", "target_customer", "product_mechanism", "why_now", "before_state", "after_state")}
        raw["canonical_source_urls"] = ["https://example.org/article"]
        self.receipt(discovery, {"articles": [{"article_key": article["article_key"], "decision": "opportunity", "reason": "reason", "opportunities": [raw]}]})
        self.e.tick("b"*40)
        merge = next(j for j in self.e.jobs().values() if j["kind"] == "merge")
        candidate = {**raw, "source_raw_ids": [raw["raw_id"]]}
        self.receipt(merge, {"cross_article_review_completed": True, "candidates": [candidate], "suppressed": []})
        self.e.tick("c"*40)
        validation = next(j for j in self.e.jobs().values() if j["kind"] == "validation")
        self.receipt(validation, self.qualified(validation))
        self.e.tick("d"*40)
        self.assertEqual(len(self.e.read("state/idea_catalog.json")["ideas"]), 2)
        self.assertEqual(self.e.read("state/v2/status.json")["runs"][0]["processing_status"], "complete")

    def test_unverified_articles_are_visible_as_research_gaps(self):
        self.e.write("docs/latest.json", {"items": [{"url": "https://example.org/article", "title": "trigger"}]})
        self.e.tick("a"*40)
        discovery = next(iter(self.e.jobs().values()))
        article = discovery["payload"]["articles"][0]
        self.receipt(discovery, {"articles": [{"article_key": article["article_key"], "decision": "unverified", "reason": "not accessible", "opportunities": []}]})
        self.e.tick("b"*40)
        report = self.e.read("state/v2/status.json")["runs"][0]
        self.assertEqual(report["processing_status"], "complete_with_gaps")
        self.assertEqual(report["article_decisions"]["unverified"], 1)

    def test_wrong_json_type_does_not_crash_controller(self):
        j = self.validation(); self.claim(j)
        self.e.write(f"state/v2/results/{j['job_id']}/001.json", ["invalid-type"])
        self.e.tick("a"*40, create=False)
        self.assertEqual(self.e.evaluate(j)["attempt"], 2)


if __name__ == "__main__":
    unittest.main()
