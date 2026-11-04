-- Recovery sweep every 5 minutes from the database (owner 2026-11-04: "1 maadu").
-- GitHub's */5 schedule really ran every 3-9 h. pg_cron is on time; pg_net makes the call.
-- The Bearer secret lives in Supabase Vault as 'brain_cron_secret' (same value as Vercel's
-- CRON_SECRET) and is created outside this file, so it is never committed.
create extension if not exists pg_cron;
create extension if not exists pg_net;

select cron.unschedule(jobid) from cron.job where jobname = 'brain-recovery';
select cron.schedule('brain-recovery', '*/5 * * * *', $job$
  select net.http_post(
    url := 'https://asthra-digitech-frontend.vercel.app/api/recovery',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || (select decrypted_secret from vault.decrypted_secrets
                                     where name = 'brain_cron_secret'),
      'Content-Type', 'application/json'),
    body := '{}'::jsonb,
    timeout_milliseconds := 300000)
$job$);

-- pg_net keeps every response; keep a week of them.
select cron.unschedule(jobid) from cron.job where jobname = 'brain-recovery-net-cleanup';
select cron.schedule('brain-recovery-net-cleanup', '17 3 * * *',
  $job$ delete from net._http_response where created < now() - interval '7 days' $job$);
