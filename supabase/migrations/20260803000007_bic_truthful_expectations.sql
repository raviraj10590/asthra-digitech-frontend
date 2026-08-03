-- BIC v1.0 — Slice 1C · Correct expected_latency_ms from measured production
--
-- First live run (2026-08-03, 7 invocations) measured:
--   leads_today       96ms avg / 142ms max   (declared 700)  ✅ realistic
--   crm_list_clients 385ms avg / 421ms max   (declared 900)  ✅ realistic
--   roles_list        53ms                   (declared 600)  ✅ realistic
--   memory_show       87ms                   (declared 500)  ✅ realistic
--   aitest          7347ms                   (declared 3000) ❌ 2.4x optimistic
--
-- aitest probes every configured AI provider SERIALLY, so seconds is its
-- normal cost, not a regression. It passed the SLOW check only because the
-- threshold is 3x — a declared expectation that a healthy run nearly breaches
-- is not a baseline, it is a future false alarm. Corrected to 8000ms so a real
-- regression (a hanging provider) actually trips the alert.
--
-- Declarations are corrected from measurement, never the reverse: widening a
-- threshold to silence a genuinely slow tool would be the anti-pattern.

update bic_tool_defs set expected_latency_ms = 8000 where code = 'aitest';

-- ── db_queries reads 0 for every row — accurate, but easy to misread ────────
-- bic/db.py counts queries made THROUGH bic.db. Every handler wraps a legacy
-- function that calls Supabase with `requests` directly, so the counter
-- correctly reports zero BIC-layer queries while real queries did happen.
-- Recorded on the column so nobody later reads 0 as "no database work".
comment on column bic_tool_invocations.db_queries is
  'Queries issued through bic/db.py ONLY. Handlers wrapping legacy functions
   that use `requests` directly will correctly report 0 despite querying
   Supabase. Becomes meaningful when business functions move onto bic.db.';
