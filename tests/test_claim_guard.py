import copy
import unittest
from datetime import datetime, timedelta, timezone

from radar.claim_guard import preflight_claim, classify_write_failure
from radar.engine import POLICY, digest, iso


class ClaimGuardTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 13, 11, tzinfo=timezone.utc)
        self.payload = {"candidate": {"canonical_key": "buyer|job|rule"}}
        self.job_hash = digest({"policy_version": POLICY, "kind": "validation", "payload": self.payload})
        self.job = {"policy_version": POLICY, "kind": "validation", "payload": self.payload,
                    "job_id": "test-validation-abcd", "input_hash": self.job_hash}
        self.invocation = "manual-worker-1-invocation-0001"
        self.started = {"event": "started", "worker": 1, "invocation_id": self.invocation,
                        "at": iso(self.now)}
        self.inbox = {"job_id": self.job["job_id"], "input_hash": self.job_hash,
                      "state": "ready", "attempt": 1,
                      "claim_path": "state/v2/claims/test-validation-abcd/001.json",
                      "result_path": "state/v2/results/test-validation-abcd/001.json"}
        self.claim = {"schema_version": 3, "job_id": self.job["job_id"],
                      "input_hash": self.job_hash, "worker": 1,
                      "invocation_id": self.invocation, "token": "fresh-unique-claim-token-1234",
                      "started_at": iso(self.now), "expires_at": iso(self.now + timedelta(minutes=30))}
        self.config = {"mode": "active", "shared_queue": True, "research_workers": [1, 2, 3, 4]}

    def test_valid_manual_claim_at_any_hour_and_all_workers(self):
        for worker in (1, 2, 3, 4):
            with self.subTest(worker=worker):
                started = {**self.started, "worker": worker}
                claim = {**self.claim, "worker": worker}
                self.assertEqual(preflight_claim(self.job, self.inbox, worker,
                                                 started, claim, self.config), [])

    def test_identity_mismatch_is_detected_before_creating_claim(self):
        wrong = {**self.claim, "input_hash": "different"}
        self.assertIn("claim_identity_mismatch",
                      preflight_claim(self.job, self.inbox, 1, self.started, wrong, self.config))
        wrong_inbox = {**self.inbox, "claim_path": "state/v2/claims/unrelated/001.json"}
        self.assertIn("claim_path_or_attempt_mismatch",
                      preflight_claim(self.job, wrong_inbox, 1, self.started, self.claim, self.config))
        wrong_job = copy.deepcopy(self.job)
        wrong_job["payload"]["candidate"]["canonical_key"] = "changed"
        self.assertIn("job_input_hash_mismatch",
                      preflight_claim(wrong_job, self.inbox, 1, self.started, self.claim, self.config))
        self.assertIn("worker_not_authorized",
                      preflight_claim(self.job, self.inbox, 5, self.started, self.claim, self.config))

    def test_invalid_lease_and_existing_job_not_ready(self):
        claim = {**self.claim, "expires_at": iso(self.now + timedelta(minutes=45))}
        self.assertIn("invalid_lease",
                      preflight_claim(self.job, self.inbox, 1, self.started, claim, self.config))
        inbox = {**self.inbox, "state": "leased"}
        self.assertIn("job_not_ready",
                      preflight_claim(self.job, inbox, 1, self.started, self.claim, self.config))

    def test_write_errors_are_classified_without_unsafe_retries(self):
        for code in (401, 403):
            self.assertEqual(classify_write_failure(code), "stop_permission_denied")
        for code in (409, 422):
            self.assertEqual(classify_write_failure(code), "read_back_and_skip_if_claimed")
        for code in (429, 500, 502, 503, 504):
            self.assertEqual(classify_write_failure(code), "read_back_then_retry_max_3")
        self.assertEqual(classify_write_failure(error_type="timeout"), "read_back_then_retry_max_3")
        self.assertEqual(classify_write_failure(400), "stop_and_report_exact_error")


if __name__ == "__main__":
    unittest.main()
