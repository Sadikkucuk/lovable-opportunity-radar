"""Deterministic pre-write identity check and conservative GitHub error routing.

This is advisory before first-writer create_file. The engine remains the
final authority when the controller reads a persisted claim/receipt.
"""
from datetime import timedelta
from radar.engine import POLICY, digest, dt


def preflight_claim(job, inbox_entry, worker, started_event, claim, config):
    """Return concrete issues before a write; never manufacture missing values."""
    errors = []
    allowed = config.get("research_workers", [1, 2, 3, 4])
    if config.get("mode") != "active" or not config.get("shared_queue"):
        errors.append("configuration_not_active")
    if type(worker) is not int or worker not in allowed:
        errors.append("worker_not_authorized")
    expected_hash = digest({"policy_version": POLICY, "kind": job.get("kind"), "payload": job.get("payload")})
    if job.get("policy_version") != POLICY or job.get("input_hash") != expected_hash:
        errors.append("job_input_hash_mismatch")
    if inbox_entry.get("job_id") != job.get("job_id") or inbox_entry.get("input_hash") != job.get("input_hash"):
        errors.append("inbox_job_mismatch")
    if inbox_entry.get("state") != "ready":
        errors.append("job_not_ready")
    attempt = inbox_entry.get("attempt")
    expected_claim_path = (f"state/v2/claims/{job.get('job_id')}/{attempt:03}.json"
                           if type(attempt) is int and 1 <= attempt <= 3 else None)
    expected_result_path = (f"state/v2/results/{job.get('job_id')}/{attempt:03}.json"
                            if expected_claim_path else None)
    if (not expected_claim_path or inbox_entry.get("claim_path") != expected_claim_path
            or inbox_entry.get("result_path") != expected_result_path):
        errors.append("claim_path_or_attempt_mismatch")
    if claim.get("job_id") != job.get("job_id") or claim.get("input_hash") != expected_hash:
        errors.append("claim_identity_mismatch")
    if claim.get("schema_version") != 3 or claim.get("worker") != worker:
        errors.append("claim_worker_or_schema_mismatch")
    if (started_event.get("event") != "started" or started_event.get("worker") != worker
            or not started_event.get("invocation_id")
            or started_event.get("invocation_id") != claim.get("invocation_id")):
        errors.append("start_event_mismatch")
    if not isinstance(claim.get("token"), str) or len(claim["token"]) < 16:
        errors.append("invalid_claim_token")
    try:
        start = dt(claim["started_at"])
        expires = dt(claim["expires_at"])
        event_time = dt(started_event["at"])
        if expires <= start or expires - start > timedelta(minutes=30):
            errors.append("invalid_lease")
        if event_time > start:
            errors.append("claim_precedes_start_event")
    except (ValueError, TypeError, KeyError, AttributeError):
        errors.append("invalid_claim_timestamp")
    return errors


def classify_write_failure(status_code=None, error_type=""):
    """Classification never treats a permission denial as transient."""
    if status_code in (401, 403):
        return "stop_permission_denied"
    if status_code in (409, 422):
        return "read_back_and_skip_if_claimed"
    if status_code in (429, 500, 502, 503, 504) or error_type in ("timeout", "connection_reset"):
        return "read_back_then_retry_max_3"
    return "stop_and_report_exact_error"
