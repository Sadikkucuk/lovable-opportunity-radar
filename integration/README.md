# AIStartup site integration

Canonical website feed:
https://raw.githubusercontent.com/Sadikkucuk/lovable-opportunity-radar/main/state/idea_catalog.json

Schema:
schemas/idea-catalog.schema.json

Supabase reference migration:
integration/aistartup_ideas.sql

Automatic sync:
.github/workflows/sync-aistartup.yml
scripts/sync_aistartup_supabase.py

## GitHub Secrets required after Lovable/Supabase migration

Add these repository secrets:

- AISTARTUP_SUPABASE_URL
- AISTARTUP_SUPABASE_SERVICE_ROLE_KEY

The service role key must remain only in GitHub Secrets. Never expose it in frontend code or commit it to the repository.

## Admin delete behavior

The site should implement Delete as a soft delete in Supabase:
is_deleted=true, deleted_at=now(), deleted_by=current admin user.

The GitHub sync never writes those three fields, so a deleted idea stays hidden and is not resurrected by the next automatic sync.

## Source of truth

- News retention remains 72 hours.
- idea_history.json is long-term semantic dedup memory.
- idea_catalog.json is the long-term full website catalog.
- The AIStartup web app reads only Supabase public rows where status=published and is_deleted=false.
