-- Phase 1B — Brain RLS lockdown (owner-approved 2026-10-01).
--
-- The project's public key ships in AI Kannada's browser JavaScript, and the
-- Brain's private tables were readable/writable with it through `true`
-- policies. Phase 1A (5ca1c65, deployed dpl_HbrDywvQ4QFwKxtPDQ9HJNeFXDwb)
-- moved every Brain call to the service role, which bypasses RLS, so these
-- public paths have no legitimate user left.
--
-- leads: the anon INSERT policy and the INSERT/SELECT/UPDATE grants are KEPT
-- (owner decision): Realty Launch-Kit api/lead.js posts there with the public
-- key. Its upsert form already fails RLS today and no Realty lead exists; that
-- is a separate phase. With no SELECT/UPDATE/DELETE policy, the public key can
-- still read, change or delete nothing. TRUNCATE is revoked because TRUNCATE
-- is not subject to RLS. No row is deleted or modified.
begin;

drop policy if exists "bot can read messages"   on public.whatsapp_messages;
drop policy if exists "bot can insert messages" on public.whatsapp_messages;
revoke all on public.whatsapp_messages from anon, authenticated;

drop policy if exists bot_roles_anon_select on public.bot_roles;
drop policy if exists bot_roles_anon_insert on public.bot_roles;
drop policy if exists bot_roles_anon_update on public.bot_roles;
revoke all on public.bot_roles from anon, authenticated;

revoke all on public.bic_webhook_events from anon, authenticated;

revoke delete, truncate, references, trigger on public.leads from anon, authenticated;

commit;
