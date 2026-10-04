-- Add cache-write token count to thalamus_harness_runs (cache writes are billed above normal input).
alter table public.thalamus_harness_runs
  add column if not exists cache_write_tokens integer;

comment on column public.thalamus_harness_runs.cache_write_tokens is
  'Prompt tokens written to the provider prompt cache on this run (Anthropic cache_creation_input_tokens). input_tokens includes them.';
