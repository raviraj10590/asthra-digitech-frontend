-- ═══════════════════════════════════════════════════════════════════════
-- Hourly Bairavi follow-up sweep — the scheduler, NOT the logic
--
-- WHY IT IS HERE AND NOT IN vercel.json. Vercel Hobby caps at two cron jobs
-- and both are in use (api/digest at 03:30 UTC, api/evaluate at 04:00 UTC).
-- A once-a-day cron cannot run an hourly sweep, so the schedule lives in
-- Postgres instead — the same net.http_post pattern the CRM's Supabase
-- already uses for its daily report and template-health jobs.
--
-- IT ALSO FIXES A SECOND GAP. The bot health check runs once a day at ~09:00
-- IST. On 2026-09-17 the bot went silent at 08:28 and the operator noticed at
-- 15:00 — six and a half hours later — because the alarm had already run for
-- the day and found only one quiet hour. An hourly heartbeat against this
-- endpoint is the natural place to notice that sooner.
--
-- NOT APPLIED AUTOMATICALLY. It needs a secret (VERIFY_TOKEN) that must not
-- be committed, so the token below is a placeholder and this migration is
-- deliberately left for an operator to run by hand after substituting it.
-- Applying it as-is would create a job that is rejected 403 every hour.
--
-- Run against the BRAIN's project (kpzprllzgqlqkqgcgrbp), not the CRM's.
-- ═══════════════════════════════════════════════════════════════════════

-- Requires: pg_cron and pg_net, both available on Supabase.
create extension if not exists pg_cron;
create extension if not exists pg_net;

-- Hourly, on the hour. The endpoint itself refuses to act outside 09:00-19:00
-- IST, so a run at 03:00 costs one HTTP call and sends nothing — the quiet
-- hours are enforced in code rather than in the schedule, where they can be
-- tested.
select cron.schedule(
  'bairavi-nudge-hourly',
  '0 * * * *',
  $$
  select net.http_post(
    url := 'https://asthra-digitech-frontend.vercel.app/api/nudge'
           || '?key=' || 'REPLACE_WITH_VERIFY_TOKEN',
    headers := '{"Content-Type": "application/json"}'::jsonb,
    timeout_milliseconds := 25000
  );
  $$
);

-- To remove:  select cron.unschedule('bairavi-nudge-hourly');
-- To inspect: select jobname, schedule, active from cron.job;
