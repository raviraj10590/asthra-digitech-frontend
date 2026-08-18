-- BIC — Decision Record: enforce append-only in the database
--
-- The Decision Record has been immutable BY CONVENTION since it was built:
-- bic/decision.py holds no update path, and the retention invariant (IDD-3D
-- I5, §3.3) forbids deletion outright — which is why this table has no pruner.
--
-- Convention was sufficient while Python was the only writer. Adding
-- db.update() for the semantic registry's DRAFT → ACTIVE transition changes
-- that: a mutation primitive now exists in the shared data layer. It is kept
-- out of decision.py's namespace by a by-name import (and a test), but an
-- import rule protects against accident, not intent.
--
-- This closes the gap the same way bic_claims does. RLS is bypassed by
-- service_role; triggers are not — so this binds every caller, including a
-- direct console session.
--
-- STRICTLY ADDITIVE. No column changes, no data touched, no policy added, no
-- pruning introduced. The 15 existing records are unaffected and remain
-- readable exactly as written.

drop trigger if exists bic_decision_records_no_mutation on bic_decision_records;
create trigger bic_decision_records_no_mutation
  before update or delete on bic_decision_records
  for each row execute function bic_reject_mutation();

comment on trigger bic_decision_records_no_mutation on bic_decision_records is
  'IDD-3D I5: decisions are immutable and never deleted. Corrections supersede,
   they do not edit. Blocks UPDATE and DELETE for every caller including
   service_role, which bypasses RLS but not triggers.';
