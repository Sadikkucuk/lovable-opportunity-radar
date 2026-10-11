"""Deterministic controller. Workers only create immutable claims and receipts.

Run with python -m radar.engine tick. All persistent state lives in Git.
Only the controller appends catalog/history rows. It never rewrites existing rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

POLICY = "radar-v2-no-runtime-services-20261010"
TERMINAL = {"done", "unverified", "rejected", "failed"}
MAX_ATTEMPTS = 3
LEASE_MINUTES = 90
RETRY_MINUTES = [5, 30, 120]
REPO = "Sadikkucuk/lovable-opportunity-radar"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def dt(value):
    d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return d.astimezone(timezone.utc)


def url_key(value):
    u = urlsplit(value)
    # Keep case-sensitive paths and meaningful parameters. Never collapse arbitrary URLs.
    query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path, urlencode(sorted(query)), ""))


def article_key(article):
    return digest(url_key(article.get("url", "")) or article.get("id") or article)[:24]


def article_signature(article):
    return digest({k: article.get(k) for k in ("url", "title", "summary", "published_at")})


def valid_url(value):
    return isinstance(value, str) and urlsplit(value).scheme in {"http", "https"} and bool(urlsplit(value).netloc)


class Engine:
    def __init__(self, root, now=None):
        self.root = Path(root)
        self.now = now or datetime.now(timezone.utc)
        self.errors = []

    def read(self, path, default=None):
        p = self.root / path
        return json.loads(p.read_text()) if p.exists() else default

    def write(self, path, value, immutable=False):
        p = self.root / path
        if p.exists() and self.read(path) == value:
            return
        if immutable and p.exists():
            raise ValueError(f"immutable artifact changed: {path}")
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        tmp.replace(p)

    def paths(self, pattern):
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.glob(pattern))

    def check_protected(self):
        baseline = self.read("state/v2/protection/baseline.json")
        if not baseline:
            raise ValueError("protection baseline missing")
        for path, expected in baseline["files"].items():
            rows = self.read(path)["ideas"]
            keys = [r["canonical_key"] for r in rows]
            if len(keys) != len(set(keys)):
                raise ValueError(f"duplicate catalog key: {path}")
            current = {r["canonical_key"]: digest(r) for r in rows}
            for key, sha in expected["records"].items():
                if current.get(key) != sha:
                    raise ValueError(f"protected record changed or missing: {path}: {key}")
        return baseline["protected_count"]

    def add_job(self, run_id, kind, payload, lane):
        input_hash = digest({"policy_version": POLICY, "kind": kind, "payload": payload})
        job_id = f"{run_id}-{kind}-{input_hash[:16]}"
        if self.read(f"state/v2/jobs/{job_id}.json"):
            return job_id
        job = {"schema_version": 2, "job_id": job_id, "run_id": run_id,
               "kind": kind, "lane": lane, "policy_version": POLICY,
               "input_hash": input_hash, "payload": payload}
        if kind == "validation":
            cached = self.read(f"state/v2/cache/candidates/{digest(payload['candidate'])}.json")
            if cached and cached["policy_version"] == POLICY and dt(cached["valid_until"]) > self.now:
                job["reuse"] = {"receipt_path": cached["receipt_path"], "checked_at": iso(self.now)}
        self.write(f"state/v2/jobs/{job_id}.json", job, immutable=True)
        return job_id

    def import_legacy(self, commit, run_date):
        run_id = f"{run_date}-migration"
        if self.read(f"state/v2/runs/{run_id}/manifest.json"):
            return
        raw = self.read(f"state/runs/{run_date}/merge/candidates.json")
        jobs = []
        for n, candidate in enumerate(raw["candidates"]):
            jobs.append(self.add_job(run_id, "validation", {
                "candidate": candidate, "source_commit": commit,
                "legacy_research_path": f"state/runs/{run_date}",
                "prior_evidence_is_not_v2_approval": True,
            }, n % 4 + 1))
        self.write(f"state/v2/runs/{run_id}/manifest.json", {
            "schema_version": 2, "run_id": run_id, "run_date": run_date,
            "kind": "legacy_migration", "source_commit": commit,
            "source_generation_reported": raw.get("source_batch_index_generated_at"),
            "source_freeze_note": "Pins the existing 95 candidate records and legacy research; does not retrospectively certify the old feed snapshot.",
            "created_at": iso(self.now), "initial_jobs": jobs,
            "candidate_count": len(jobs), "policy_version": POLICY,
        }, immutable=True)

    def create_run(self, commit):
        day = self.now.astimezone(ZoneInfo("Europe/Istanbul")).date().isoformat()
        # One immutable input snapshot per Istanbul day; carried jobs retain their own run.
        if self.paths(f"state/v2/runs/{day}*/manifest.json"):
            return
        latest = self.read("docs/latest.json")
        if not latest or not latest.get("items"):
            self.errors.append("feed missing or empty; keeping last valid publication")
            return
        run_id = day + "-" + commit[:10]
        unique = {}
        for a in latest["items"]:
            unique[article_key(a)] = a
        articles = [{"article_key": key, "content_hash": article_signature(a), "record": a}
                    for key, a in sorted(unique.items())]
        snapshot = {"source_commit": commit, "source_generated_at": latest.get("generated_at"),
                    "raw_count": len(latest["items"]), "unique_count": len(articles), "articles": articles}
        self.write(f"state/v2/runs/{run_id}/snapshot.json", snapshot, immutable=True)
        pending, reused = [], []
        for article in articles:
            cached = self.read(f"state/v2/cache/articles/{article['content_hash']}.json")
            if cached and cached["policy_version"] == POLICY and dt(cached["valid_until"]) > self.now:
                reused.append(cached)
            else:
                pending.append(article)
        self.write(f"state/v2/runs/{run_id}/reused.json", reused, immutable=True)
        jobs = []
        for start in range(0, len(pending), 10):
            jobs.append(self.add_job(run_id, "discovery", {
                "source_commit": commit, "articles": pending[start:start + 10],
            }, (start // 10) % 4 + 1))
        self.write(f"state/v2/runs/{run_id}/manifest.json", {
            "schema_version": 2, "run_id": run_id, "run_date": day, "kind": "daily",
            "created_at": iso(self.now), "source_commit": commit,
            "source_generation": latest.get("generated_at"), "snapshot_hash": digest(snapshot),
            "raw_count": len(latest["items"]), "unique_count": len(articles),
            "reused_articles": len(reused), "initial_jobs": jobs, "policy_version": POLICY,
        }, immutable=True)

    def validate_receipt(self, job, claim, receipt):
        for k in ("job_id", "input_hash"):
            if receipt.get(k) != job[k] or claim.get(k) != job[k]:
                raise ValueError(f"{k} mismatch")
        if claim.get("worker") != job["lane"] or receipt.get("token") != claim.get("token"):
            raise ValueError("worker or lease token mismatch")
        started, expires, finished = dt(claim["started_at"]), dt(claim["expires_at"]), dt(receipt["finished_at"])
        if not isinstance(claim.get("token"), str) or len(claim["token"]) < 16:
            raise ValueError("missing unique lease token")
        if expires <= started or expires - started > timedelta(minutes=LEASE_MINUTES):
            raise ValueError("invalid lease duration")
        if not started <= finished <= expires or finished > self.now + timedelta(minutes=5):
            raise ValueError("receipt outside lease or in future")
        if receipt.get("outcome") not in {"done", "unverified", "rejected", "retry"}:
            raise ValueError("invalid outcome")
        if not receipt.get("reason"):
            raise ValueError("reason required")
        if receipt["outcome"] == "done":
            self.validate_result(job, receipt["result"], as_of=finished)

    def validate_result(self, job, result, as_of=None):
        if job["kind"] == "discovery":
            expected = {a["article_key"] for a in job["payload"]["articles"]}
            decisions = result.get("articles", [])
            if len(decisions) != len(expected) or {d.get("article_key") for d in decisions} != expected:
                raise ValueError("every assigned article needs exactly one decision")
            raw_ids = set()
            for decision in decisions:
                if decision.get("decision") not in {"opportunity", "no_opportunity", "unverified"} or not decision.get("reason"):
                    raise ValueError("article decision/reason required")
                opportunities = decision.get("opportunities", [])
                if decision["decision"] == "opportunity" and not opportunities:
                    raise ValueError("opportunity decision has no opportunities")
                for raw in opportunities:
                    required = ("raw_id", "canonical_key", "idea_name", "core_job", "target_customer",
                                "product_mechanism", "why_now", "before_state", "after_state", "canonical_source_urls")
                    if any(not raw.get(k) for k in required) or raw["raw_id"] in raw_ids:
                        raise ValueError("incomplete or duplicate raw opportunity")
                    raw_ids.add(raw["raw_id"])
        elif job["kind"] == "merge":
            expected = {r["raw_id"] for r in job["payload"]["opportunities"]}
            covered, keys = [], []
            for candidate in result.get("candidates", []):
                for k in ("canonical_key", "idea_name", "core_job", "target_customer", "product_mechanism", "source_raw_ids"):
                    if not candidate.get(k):
                        raise ValueError(f"candidate missing {k}")
                covered.extend(candidate["source_raw_ids"])
                keys.append(candidate["canonical_key"])
            for suppressed in result.get("suppressed", []):
                if not suppressed.get("reason"):
                    raise ValueError("suppression needs reason")
                covered.extend(suppressed["source_raw_ids"])
            if set(covered) != expected or len(keys) != len(set(keys)):
                raise ValueError("merge must account for every raw opportunity and unique candidate key")
            if result.get("cross_article_review_completed") is not True:
                raise ValueError("cross-article review missing")
        elif job["kind"] == "validation":
            self.validate_qualification(job, result, as_of=as_of)
        else:
            raise ValueError("unknown job kind")

    def validate_qualification(self, job, result, as_of=None):
        reference_time = as_of or self.now
        candidate = job["payload"]["candidate"]
        if result.get("decision") not in {"qualified", "rejected", "unverified", "duplicate"}:
            raise ValueError("invalid validation decision")
        if not result.get("reason"):
            raise ValueError("validation reason required")
        if result["decision"] != "qualified":
            if result["decision"] == "duplicate" and not result.get("duplicate_of"):
                raise ValueError("duplicate target required")
            return
        evidence = result.get("evidence", [])
        roles = set()
        for e in evidence:
            if not valid_url(e.get("url")) or not e.get("claim") or not e.get("observation"):
                raise ValueError("evidence URL, claim and observation required")
            when = dt(e["accessed_at"])
            if when > reference_time + timedelta(minutes=5) or reference_time - when > timedelta(days=7):
                raise ValueError("evidence stale or from future")
            if e.get("page_read") is not True or e.get("support") != "supported":
                raise ValueError("headlines and inaccessible pages are not proof")
            roles.add(e.get("role"))
        if not {"trigger", "competition_tr", "competition_global", "feasibility"} <= roles:
            raise ValueError("missing evidence roles")
        comp = result.get("competition", {})
        for market in ("tr", "global"):
            c = comp.get(market, {})
            count = c.get("direct_count")
            if type(count) is not int or count < 0 or not c.get("queries") or not c.get("scope"):
                raise ValueError("unknown competition cannot be treated as zero")
            if c.get("search_complete") is not True:
                raise ValueError("competition search incomplete")
            if len(c.get("direct_competitors", [])) != count:
                raise ValueError("competitor count and list disagree")
            for competitor in c.get("direct_competitors", []):
                if not valid_url(competitor.get("url")) or not competitor.get("same_customer_job_workflow_reason"):
                    raise ValueError("direct competitor needs URL and matching rationale")
        if comp["tr"]["direct_count"] != 0 or comp["global"]["direct_count"] > 3:
            raise ValueError("competition threshold not met")
        feasible = result.get("feasibility", {})
        for k in ("runtime_external_api", "runtime_external_database", "runtime_ai_agent_or_model"):
            if feasible.get(k) is not False:
                raise ValueError(f"{k} must be explicitly false, not unknown")
        if not feasible.get("architecture") or not feasible.get("dependency_inventory"):
            raise ValueError("feasibility architecture and dependencies required")
        if result.get("history_review", {}).get("decision") != "new" or not result["history_review"].get("reason"):
            raise ValueError("semantic history review required")
        idea = result.get("catalog_record", {})
        if idea.get("canonical_key") != candidate["canonical_key"]:
            raise ValueError("catalog identity differs from candidate")
        required_text = ("idea_name", "scope_reason", "news_source", "news_title", "core_idea", "user_story",
                         "before_state", "after_state", "target_customer", "mvp", "working_logic", "marketing_strategy")
        if any(not isinstance(idea.get(k), str) or not idea[k].strip() for k in required_text):
            raise ValueError("incomplete catalog text fields")
        if idea.get("scope_tier") not in {"Lüleburgaz", "Türkiye", "Dünya", "Evren"} or not valid_url(idea.get("news_url")):
            raise ValueError("invalid catalog scope or source URL")
        if not idea.get("business_models") or not idea.get("technologies"):
            raise ValueError("business models and technologies required")
        for field, market in (("turkiye_direct_competitor_count", "tr"), ("global_direct_competitor_count", "global")):
            if type(idea.get(field)) is not int or idea[field] != comp[market]["direct_count"]:
                raise ValueError("catalog competitor count disagrees with evidence")
        credit = idea.get("lovable_credits_total")
        if credit is not None and (type(credit) is not int or credit < 0):
            raise ValueError("credit estimate must be nonnegative or null; no upper limit")
        cost = idea.get("external_cash_cost")
        if cost is not None and (type(cost) not in {int, float} or cost < 0):
            raise ValueError("cash estimate must be nonnegative or null")
        if idea.get("verification_status") != "qualified" or idea.get("status") != "published":
            raise ValueError("qualified catalog status required")

    def evaluate(self, job):
        expected = digest({"policy_version": POLICY, "kind": job["kind"], "payload": job["payload"]})
        if job["input_hash"] != expected or job["policy_version"] != POLICY:
            return {"state": "failed", "reason": "immutable input or policy mismatch"}
        if job.get("reuse"):
            try:
                receipt = self.read(job["reuse"]["receipt_path"])
                source = self.read(f"state/v2/jobs/{receipt['job_id']}.json")
                if source["policy_version"] != POLICY or source["payload"]["candidate"] != job["payload"]["candidate"]:
                    raise ValueError("reuse candidate mismatch")
                self.validate_result(job, receipt["result"], as_of=dt(job["reuse"]["checked_at"]))
                return {"state": "done", "receipt_path": job["reuse"]["receipt_path"], "receipt": receipt, "reused": True}
            except (ValueError, KeyError, TypeError, AttributeError):
                pass
        # Numbered claim paths are first-writer-wins. Overlapping invocations cannot own the same attempt.
        for attempt in range(1, MAX_ATTEMPTS + 1):
            claim_path = f"state/v2/claims/{job['job_id']}/{attempt:03}.json"
            result_path = f"state/v2/results/{job['job_id']}/{attempt:03}.json"
            retry_at = self.now
            try:
                claim = self.read(claim_path)
                if not claim:
                    return {"state": "ready", "attempt": attempt, "claim_path": claim_path, "result_path": result_path}
                if claim.get("job_id") != job["job_id"] or claim.get("input_hash") != job["input_hash"] or claim.get("worker") != job["lane"]:
                    raise ValueError("invalid claim identity")
                started, expires = dt(claim["started_at"]), dt(claim["expires_at"])
                if started > self.now + timedelta(minutes=5) or expires - started > timedelta(minutes=LEASE_MINUTES) or expires <= started:
                    raise ValueError("invalid claim time")
                receipt = self.read(result_path)
                if self.read(f"state/v2/claims/{job['job_id']}/{attempt + 1:03}.json"):
                    # A newer owner fences late writes from an expired attempt.
                    continue
                if receipt:
                    self.validate_receipt(job, claim, receipt)
                    if receipt["outcome"] != "retry":
                        return {"state": receipt["outcome"], "attempt": attempt,
                                "receipt_path": result_path, "receipt": receipt}
                    retry_at = dt(receipt["finished_at"]) + timedelta(minutes=RETRY_MINUTES[attempt-1])
                elif self.now < expires:
                    return {"state": "leased", "attempt": attempt, "expires_at": claim["expires_at"]}
                else:
                    retry_at = expires + timedelta(minutes=RETRY_MINUTES[attempt-1])
                reason = receipt.get("reason") if receipt else "worker lease expired without a receipt"
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                reason = "invalid attempt: " + str(exc)
                # Bad records remain available for audit; they never poison the whole controller.
                self.errors.append(f"{job['job_id']} attempt {attempt}: {reason}")
            if attempt == MAX_ATTEMPTS:
                return {"state": "failed", "reason": reason, "attempt": attempt}
            if self.now < retry_at:
                return {"state": "retry_wait", "attempt": attempt, "retry_at": iso(retry_at), "reason": reason}
        raise AssertionError("unreachable")

    def jobs(self):
        return {self.read(p)["job_id"]: self.read(p) for p in self.paths("state/v2/jobs/*.json")}

    def cache_discovery(self, job, state):
        if job["kind"] == "validation" and state["state"] == "done":
            receipt = state["receipt"]
            ttl = 1 if receipt["result"]["decision"] == "unverified" else 7
            self.write(f"state/v2/cache/candidates/{digest(job['payload']['candidate'])}.json", {
                "policy_version": POLICY, "receipt_path": state["receipt_path"],
                "valid_until": iso(dt(receipt["finished_at"]) + timedelta(days=ttl))})
            return
        if job["kind"] != "discovery" or state["state"] != "done":
            return
        receipt = state["receipt"]
        by_key = {a["article_key"]: a for a in job["payload"]["articles"]}
        for decision in receipt["result"]["articles"]:
            a = by_key[decision["article_key"]]
            ttl = 1 if decision["decision"] == "unverified" else 30
            cache = {"policy_version": POLICY, "content_hash": a["content_hash"],
                     "decision": decision, "receipt_path": state["receipt_path"],
                     "valid_until": iso(dt(receipt["finished_at"]) + timedelta(days=ttl))}
            self.write(f"state/v2/cache/articles/{a['content_hash']}.json", cache)

    def advance(self, jobs, states):
        for path in self.paths("state/v2/runs/*/manifest.json"):
            manifest = self.read(path)
            if manifest["kind"] != "daily":
                continue
            run_id = manifest["run_id"]
            initial = manifest["initial_jobs"]
            if not all(states[j]["state"] in TERMINAL for j in initial):
                continue
            raw = []
            for cached in self.read(f"state/v2/runs/{run_id}/reused.json", []):
                raw.extend(cached["decision"].get("opportunities", []))
            for j in initial:
                if states[j]["state"] == "done":
                    for a in states[j]["receipt"]["result"]["articles"]:
                        raw.extend(a.get("opportunities", []))
            # Identical cached raw IDs can occur in several articles; keep exact records once.
            unique = {r["raw_id"]: r for r in raw}
            if unique:
                self.add_job(run_id, "merge", {"source_commit": manifest["source_commit"],
                    "opportunities": list(unique.values()), "history_path": "state/idea_history.json"}, 5)
        for job_id, job in jobs.items():
            if job["kind"] == "merge" and states[job_id]["state"] == "done":
                for n, c in enumerate(states[job_id]["receipt"]["result"]["candidates"]):
                    self.add_job(job["run_id"], "validation", {
                        "source_commit": job["payload"]["source_commit"], "candidate": c,
                        "merge_receipt": states[job_id]["receipt_path"],
                    }, n % 4 + 1)

    def publish(self, jobs, states):
        self.check_protected()
        catalog = self.read("state/idea_catalog.json")
        history = self.read("state/idea_history.json")
        existing = {i["canonical_key"] for i in catalog["ideas"]}
        history_keys = {i["canonical_key"] for i in history["ideas"]}
        appended = []
        for job_id, job in sorted(jobs.items()):
            state = states[job_id]
            if job["kind"] != "validation" or state["state"] != "done":
                continue
            result = state["receipt"]["result"]
            if result["decision"] != "qualified":
                continue
            idea = result["catalog_record"].copy()
            key = idea["canonical_key"]
            if key in existing or key in history_keys:
                continue
            # Stale evidence holds only this candidate, never blocks unrelated publications.
            try:
                self.validate_qualification(job, result)
            except ValueError as exc:
                self.errors.append(f"{job_id}: publication withheld: {exc}")
                if "stale" in str(exc):
                    # A publication delayed past TTL gets a fresh, independent research
                    # job, without reopening or altering the completed old receipt.
                    self.add_job(job["run_id"], "validation", {
                        **job["payload"], "recheck_of": job_id,
                    }, job["lane"])
                continue
            date = state["receipt"]["finished_at"][:10]
            idea.setdefault("first_reported_at", date)
            idea.setdefault("last_updated_at", date)
            idea["radar_v2_provenance"] = {"job_id": job_id, "receipt_path": state["receipt_path"], "policy_version": POLICY}
            catalog["ideas"].append(idea)
            c = job["payload"]["candidate"]
            history["ideas"].append({"canonical_key": key, "idea_name": idea["idea_name"],
                "core_job": c.get("core_job"), "target_customer": c.get("target_customer"),
                "product_mechanism": c.get("product_mechanism"), "first_reported_at": date,
                "last_seen_at": date, "times_seen": 1, "status": "qualified",
                "source_titles": [idea["news_title"]], "radar_v2_job_id": job_id})
            existing.add(key)
            history_keys.add(key)
            appended.append(key)
        if appended:
            catalog["updated_at"] = iso(self.now)
            history["updated_at"] = iso(self.now)
            self.write("state/idea_catalog.json", catalog)
            self.write("state/idea_history.json", history)
        self.check_protected()
        # Publish a content-addressed static payload; pointer and bytes share one Git commit.
        # This public release derives ONLY from the already-public GitHub catalog.
        # The site preserves its legacy IDs using its own private baseline; never
        # publish a database export into this public repository.
        rows = []
        for idea in catalog["ideas"]:
            row = idea.copy()
            row["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, "radar:" + idea["canonical_key"]))
            row.update({"is_deleted": False, "source_system": "github_radar", "created_at": idea.get("first_reported_at")})
            rows.append(row)
        payload = {"schema_version": 2, "ideas": rows, "catalog_sha256": digest(catalog)}
        sha = digest(payload)
        release_path = f"docs/radar/releases/{sha}.json"
        self.write(release_path, payload, immutable=True)
        self.write("docs/radar/current.json", {"schema_version": 2, "release_id": sha,
                   "path": release_path, "idea_count": len(rows), "legacy_count": self.check_protected(),
                   "content_sha256": hashlib.sha256((self.root / release_path).read_bytes()).hexdigest()})
        return appended

    def tick(self, commit, create=True):
        protected = self.check_protected()
        config = self.read("state/v2/config.json", {})
        if config.get("mode") != "active":
            return {"mode": config.get("mode", "maintenance"), "protected_records": protected}
        seed = config.get("legacy_import")
        if seed:
            self.import_legacy(seed["commit"], seed["date"])
        if create:
            self.create_run(commit)
        # Two passes discover downstream jobs without waiting for another scheduled invocation.
        for _ in range(2):
            jobs = self.jobs()
            states = {k: self.evaluate(j) for k, j in jobs.items()}
            for k, j in jobs.items():
                self.cache_discovery(j, states[k])
            self.advance(jobs, states)
        jobs = self.jobs()
        states = {k: self.evaluate(j) for k, j in jobs.items()}
        appended = self.publish(jobs, states)
        for lane in range(1, 6):
            pending = []
            for k, job in sorted(jobs.items(), key=lambda kv: (kv[1]["run_id"], {"validation": 0, "merge": 1, "discovery": 2}[kv[1]["kind"]], kv[0])):
                if job["lane"] == lane and states[k]["state"] not in TERMINAL:
                    pending.append({"job_id": k, "path": f"state/v2/jobs/{k}.json", "kind": job["kind"],
                                    "input_hash": job["input_hash"], **states[k]})
            self.write(f"state/v2/inbox/worker-{lane}.json", {"schema_version": 2, "lane": lane, "jobs": pending})
        run_reports = []
        for path in self.paths("state/v2/runs/*/manifest.json"):
            manifest = self.read(path)
            run_id = manifest["run_id"]
            subset = {k: s for k, s in states.items() if jobs[k]["run_id"] == run_id}
            counts = Counter(s["state"] for s in subset.values())
            decisions = Counter(s["receipt"]["result"]["decision"] for k, s in subset.items()
                                if jobs[k]["kind"] == "validation" and s["state"] == "done")
            closed = all(s["state"] in TERMINAL for s in subset.values())
            gaps = counts["failed"] + counts["unverified"] + decisions["unverified"]
            discovery_seen = manifest.get("reused_articles", 0)
            article_decisions = Counter()
            for cached in self.read(f"state/v2/runs/{run_id}/reused.json", []):
                article_decisions[cached["decision"]["decision"]] += 1
            for k, s in subset.items():
                if jobs[k]["kind"] == "discovery" and s["state"] == "done":
                    discovery_seen += len(s["receipt"]["result"]["articles"])
                    article_decisions.update(a["decision"] for a in s["receipt"]["result"]["articles"])
            gaps += article_decisions["unverified"]
            report = {"run_id": run_id, "processing_status": ("complete_with_gaps" if gaps else "complete") if closed else "in_progress",
                      "job_counts": dict(counts), "validation_decisions": dict(decisions),
                      "article_decisions": dict(article_decisions),
                      "articles_processed": discovery_seen if manifest["kind"] == "daily" else None,
                      "articles_expected": manifest.get("unique_count"),
                      "publication_status": "github_release_available", "site_delivery": "not_observed_by_controller"}
            # Timestamp changes only when substantive state changes.
            old = self.read(f"state/v2/runs/{run_id}/report.json", {})
            report["state_changed_at"] = old.get("state_changed_at", iso(self.now)) if {k:v for k,v in old.items() if k != "state_changed_at"} == report else iso(self.now)
            self.write(f"state/v2/runs/{run_id}/report.json", report)
            run_reports.append(report)
        status = {"schema_version": 2, "policy_version": POLICY, "protected_records": protected,
                  "catalog_count": len(self.read("state/idea_catalog.json")["ideas"]),
                  "counts": dict(Counter(s["state"] for s in states.values())),
                  "runs": run_reports, "errors": sorted(set(self.errors))}
        self.write("state/v2/status.json", status)
        return {"jobs": len(jobs), "appended": len(appended), **status}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["tick", "check", "migrate"])
    p.add_argument("--root", default=".")
    p.add_argument("--commit")
    p.add_argument("--date", default="2026-10-10")
    p.add_argument("--no-create", action="store_true")
    a = p.parse_args()
    e = Engine(a.root)
    if a.command == "check":
        print(json.dumps({"protected_records_unchanged": e.check_protected()}))
    else:
        commit = a.commit or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=a.root, text=True).strip()
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("immutable 40-character Git commit required")
        if a.command == "migrate":
            e.import_legacy(commit, a.date)
        else:
            result = e.tick(commit, create=not a.no_create)
            print(json.dumps({k:v for k,v in result.items() if k != "runs"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
