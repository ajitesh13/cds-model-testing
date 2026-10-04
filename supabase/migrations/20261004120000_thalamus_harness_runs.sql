-- Thalamus CDS harness runs -- one row per `ask` (CLI or web) of the Thalamus CDS test harness.
--
-- Written by the harness (cds repo, thalamus/store.py SupabaseStore) with the service_role key,
-- one row per question after the pipeline finishes (including error runs). Nothing in the browser
-- touches this table: RLS is on and there are deliberately NO policies, so the anon and
-- authenticated roles can neither read nor write it. Read it from the Supabase dashboard or with
-- the service_role key.
--
-- Separate from thalamus_chat_log (a different service with a different shape). Rows hold
-- questions and answers about synthetic patients plus the caller's IP; treat as sensitive.

create table if not exists public.thalamus_harness_runs (
  id                   uuid primary key default gen_random_uuid(),
  created_at           timestamptz not null default now(),
  source               text,
  session_id           text,
  turn_index           integer,
  patient              text,
  question_id          text,
  question_text        text not null,
  rater_label          text,
  config_id            text,
  provider             text,
  model_requested      text,
  model_returned       text,
  effort               text,
  prompt_version       text,
  record_hash          text,
  status               text not null
                       check (status in ('verified', 'unverified', 'failed_schema', 'error')),
  answer_json          jsonb,
  verification_json    jsonb,
  format_checks_json   jsonb,
  raw_response_json    jsonb,
  error                text,
  input_tokens         integer,
  output_tokens        integer,
  cached_input_tokens  integer,
  cost_usd             numeric,
  latency_ms           integer,
  retries              integer,
  client_ip            text,
  origin               text,
  user_agent           text,
  canonical_question   text,   -- phase 3 (determinism); null in phase 1
  cache_hit            boolean -- phase 3 (determinism); null in phase 1
);

comment on table public.thalamus_harness_runs is
  'One row per question asked through the Thalamus CDS harness: config, prompt and record versions, cited answer, citation verification, tokens, cost, latency.';
comment on column public.thalamus_harness_runs.session_id is
  'Web session id (Streamlit) or null for CLI runs. Group turns with (session_id, turn_index).';
comment on column public.thalamus_harness_runs.status is
  'verified | unverified (a cited value did not match its row) | failed_schema (no valid JSON after one retry) | error (provider failure or model-ID mismatch; see error).';
comment on column public.thalamus_harness_runs.record_hash is
  'SHA-256 of the serialized patient record the model saw. With prompt_version and config_id it identifies the run for reproducibility.';
comment on column public.thalamus_harness_runs.raw_response_json is
  'Array of raw provider responses, one per model call (first call, schema retry, citation retry).';
comment on column public.thalamus_harness_runs.cost_usd is
  'Null when pricing for the model is unknown.';
comment on column public.thalamus_harness_runs.client_ip is
  'Last X-Forwarded-For entry, as seen by the web host; null for CLI runs.';

create index if not exists thalamus_harness_runs_session_idx
  on public.thalamus_harness_runs (session_id, created_at);
create index if not exists thalamus_harness_runs_config_idx
  on public.thalamus_harness_runs (config_id, created_at desc);
create index if not exists thalamus_harness_runs_question_idx
  on public.thalamus_harness_runs (question_id, config_id);
create index if not exists thalamus_harness_runs_status_idx
  on public.thalamus_harness_runs (status, created_at desc);

alter table public.thalamus_harness_runs enable row level security;
-- No policies on purpose: only service_role (which bypasses RLS) can read or write.
