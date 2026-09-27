-- AIStartup canonical ideas table
-- Apply from Lovable/Supabase after reviewing the existing project schema.
-- Preserve the existing auth/admin user setup; this migration only defines the ideas data model.

create extension if not exists pgcrypto;

create table if not exists public.ideas (
  id uuid primary key default gen_random_uuid(),
  canonical_key text not null unique,
  idea_name text not null,
  scope_tier text not null check (scope_tier in ('Lüleburgaz','Türkiye','Dünya','Evren')),
  scope_reason text,
  news_source text,
  news_title text,
  news_date date,
  news_url text,
  source_links jsonb not null default '[]'::jsonb,
  core_idea text not null,
  user_story text,
  before_state text,
  after_state text,
  why_now text,
  target_customer text,
  buyer text,
  market text,
  turkiye_direct_competitor_count integer not null default 0 check (turkiye_direct_competitor_count >= 0),
  global_direct_competitor_count integer not null default 0 check (global_direct_competitor_count >= 0),
  direct_competitors jsonb not null default '[]'::jsonb,
  adjacent_competitors jsonb not null default '[]'::jsonb,
  market_gap text,
  business_models jsonb not null default '[]'::jsonb,
  lovable_credits_total integer check (lovable_credits_total between 0 and 500),
  lovable_credit_breakdown jsonb not null default '{}'::jsonb,
  technologies jsonb not null default '[]'::jsonb,
  external_cash_cost numeric not null default 0 check (external_cash_cost = 0),
  mvp text,
  working_logic text,
  build_time text,
  marketing_strategy text,
  first_customer_plan text,
  main_risk text,
  validation_assumption text,
  evidence_strength text,
  competition_confidence text,
  verification_status text not null default 'qualified'
    check (verification_status in ('qualified','competition_not_verified')),
  status text not null default 'published'
    check (status in ('published','archived')),
  source_system text not null default 'github_radar',
  is_deleted boolean not null default false,
  deleted_at timestamptz,
  deleted_by uuid references auth.users(id),
  first_reported_at date,
  last_updated_at date,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_ideas_visible
  on public.ideas (is_deleted, status, first_reported_at desc);

create index if not exists idx_ideas_scope
  on public.ideas (scope_tier);

alter table public.ideas enable row level security;

-- Public site: read published, non-deleted ideas only.
drop policy if exists "public read published ideas" on public.ideas;
create policy "public read published ideas"
on public.ideas for select
using (status = 'published' and is_deleted = false);

-- IMPORTANT:
-- Reuse the EXISTING admin-role mechanism in the Lovable project for update/delete rights.
-- Do not create a second conflicting role system if one already exists.
-- The UI "Sil" action should SOFT DELETE:
--   is_deleted=true, deleted_at=now(), deleted_by=auth.uid()
-- The GitHub sync script intentionally never writes is_deleted/deleted_at/deleted_by,
-- so a deleted idea will not reappear on the next sync.
