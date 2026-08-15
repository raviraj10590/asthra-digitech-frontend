-- BIC — Decision Record: tool_results (execution outcome capture)
--
-- WHY
-- ---
-- The record proved a tool was AUTHORIZED and INVOKED, never whether it
-- SUCCEEDED. Verifying the 2026-08-15 brochure turn required md5-matching a
-- reply marker in whatsapp_messages — the same coupling branch_id removed,
-- reappearing one level down. An explanation that needs a second store is an
-- explanation that expires (IDD-3D §4.4).
--
-- SCOPE — EXECUTION RESULT ONLY
-- -----------------------------
-- "Did the capability succeed, just now." NOT whether it was a good decision,
-- NOT whether the customer converted, NOT revenue. Business outcome is 2I and
-- stays outside the runtime; this column must never drift into it.
--
-- NULL vs [] — THE DISTINCTION IS THE POINT
-- -----------------------------------------
--   NULL  no execution result recorded (a v1/v2 row, written before this
--         column existed) — we do not know
--   []    recorded, and no tool executed this turn — we know, and it is none
--   [...] one entry per capability that actually ran
--
-- DELIBERATELY NO DEFAULT. A default of '[]' would make every historical row
-- appear to assert "nothing executed", which is a claim the data cannot
-- support. Absence is data (2C §5.6); manufacturing it is not.
--
-- ENTRY SHAPE
-- -----------
--   {"tool":"send_brochure","status":"SUCCEEDED","failure_class":null,
--    "latency_ms":812}
--
-- An entry exists ONLY when a handler actually ran. A denied tool and a
-- missing handler both produce NO entry, because neither executed — the
-- denial lives in denied_tools, the missing handler in gate_results.capability.
--
-- NO RAW ERROR TEXT. `failure_class` is a bounded vocabulary
-- (TIMEOUT / CONNECTION / DATABASE / VALUE / PERMISSION / UNKNOWN) assigned in
-- bic/tools.py. Exception strings, stack traces and tool arguments never reach
-- this column — any of them could carry customer data, and this table has no
-- pruner.
--
-- CONSTRAINT ASYMMETRY, STATED RATHER THAN HIDDEN
-- -----------------------------------------------
-- branch_id gets a full value CHECK; this column gets only an array-type
-- check. Validating the status of each array ELEMENT requires a subquery, and
-- PostgreSQL forbids subqueries in CHECK constraints. The closed vocabulary is
-- therefore enforced in Python at the boundary, and the database enforces
-- shape. That is a real gap in defence-in-depth, not an oversight.

alter table bic_decision_records
  add column if not exists tool_results jsonb;

alter table bic_decision_records
  drop constraint if exists bic_decision_tool_results_check;
alter table bic_decision_records
  add constraint bic_decision_tool_results_check
  check (tool_results is null or jsonb_typeof(tool_results) = 'array');

comment on column bic_decision_records.tool_results is
  'Execution result per capability that ACTUALLY RAN. NULL = not recorded
   (v1/v2 rows); [] = recorded, nothing executed. Denied tools and missing
   handlers produce no entry because neither executed. failure_class is a
   bounded vocabulary — raw exception text, stack traces and tool arguments
   are never stored. Execution result only: business outcome is 2I.';
