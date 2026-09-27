#!/usr/bin/env python3
"""Upsert the canonical AIStartup idea catalog into Supabase.

Required environment variables:
  AISTARTUP_SUPABASE_URL
  AISTARTUP_SUPABASE_SERVICE_ROLE_KEY

The script deliberately does NOT write is_deleted/deleted_at/deleted_by.
Therefore an admin soft-deletion remains deleted after future GitHub syncs.
"""

import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "state" / "idea_catalog.json"

URL = os.getenv("AISTARTUP_SUPABASE_URL", "").rstrip("/")
KEY = os.getenv("AISTARTUP_SUPABASE_SERVICE_ROLE_KEY", "")

if not URL or not KEY:
    print("AIStartup Supabase secrets are not configured; skipping sync.")
    sys.exit(0)

data = json.loads(CATALOG.read_text(encoding="utf-8"))
ideas = data.get("ideas", [])
if not ideas:
    print("Catalog is empty; nothing to sync.")
    sys.exit(0)

allowed = {
    "canonical_key","idea_name","scope_tier","scope_reason","news_source","news_title",
    "news_date","news_url","source_links","core_idea","user_story","before_state",
    "after_state","why_now","target_customer","buyer","market",
    "turkiye_direct_competitor_count","global_direct_competitor_count",
    "direct_competitors","adjacent_competitors","market_gap","business_models",
    "lovable_credits_total","lovable_credit_breakdown","technologies",
    "external_cash_cost","mvp","working_logic","build_time","marketing_strategy",
    "first_customer_plan","main_risk","validation_assumption","evidence_strength",
    "competition_confidence","verification_status","status","first_reported_at",
    "last_updated_at"
}

rows = []
for idea in ideas:
    if idea.get("scope_tier") not in {"Lüleburgaz","Türkiye","Dünya","Evren"}:
        raise SystemExit(f"Invalid scope_tier for {idea.get('idea_name')}: {idea.get('scope_tier')}")
    if idea.get("external_cash_cost") != 0:
        raise SystemExit(f"external_cash_cost must be 0 for {idea.get('idea_name')}")
    if int(idea.get("lovable_credits_total", 999999)) > 500:
        raise SystemExit(f"Lovable credits exceed 500 for {idea.get('idea_name')}")
    rows.append({k:v for k,v in idea.items() if k in allowed})

endpoint = f"{URL}/rest/v1/ideas?on_conflict=canonical_key"
headers = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal",
}
resp = requests.post(endpoint, headers=headers, json=rows, timeout=60)
if resp.status_code >= 300:
    print(resp.text)
    raise SystemExit(f"Supabase sync failed with HTTP {resp.status_code}")

print(f"Synced {len(rows)} ideas to AIStartup.")
