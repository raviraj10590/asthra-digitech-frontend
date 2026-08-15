-- BIC — Decision Record: branch_id (IDD-3D §4.4)
--
-- WHY
-- ---
-- The record proved that A deterministic rule settled a turn, but not WHICH.
-- Identifying it meant md5-matching a reply marker in whatsapp_messages — a
-- table with its own retention that is full of customer data.
--
-- That is exactly the coupling 3D §4.4 warns about: an explanation that needs
-- a second store is an explanation that expires. This column makes the
-- deterministic record self-explanatory.
--
-- ADDITIVE ONLY (3D §10.1)
-- ------------------------
-- One nullable column. No existing row is rewritten, no constraint on
-- historical data changes, and rows written at schema_version 1 remain
-- readable exactly as they are — they simply carry NULL here.
--
-- NO PII
-- ------
-- The vocabulary is CLOSED and names the RULE, never the message. A branch id
-- is a property of the code path, not of anything the customer typed, so no
-- customer input can reach this column. bic/decision.py validates against the
-- same closed set before writing; this CHECK is the second line of defence.

alter table bic_decision_records
  add column if not exists branch_id text;

-- The five deterministic branches that exist in run_client_pipeline today.
-- Adding a branch to the code means adding it here — deliberately, in a
-- migration — rather than a new value appearing silently in production.
alter table bic_decision_records
  drop constraint if exists bic_decision_branch_id_check;
alter table bic_decision_records
  add constraint bic_decision_branch_id_check
  check (branch_id is null or branch_id in (
    'MENU_REQUEST',
    'OFF_TOPIC',
    'CHAT_PAUSED',
    'BROCHURE_REQUEST',
    'NEW_CONTACT'));

-- NULL is meaningful here and must stay queryable: it means no deterministic
-- branch claimed the turn (the AI path), which is as much a fact as a named
-- branch is.
create index if not exists bic_decision_branch_idx
  on bic_decision_records (branch_id);

comment on column bic_decision_records.branch_id is
  'Which deterministic branch settled the turn. NULL when none did (AI path).
   Set explicitly at the branch itself — never inferred from AI absence,
   response text, or another table. Independent of decisive_rung: a branch
   that fired before a policy denial is recorded here AND rung RUNG_2_POLICY,
   because both are true.';
