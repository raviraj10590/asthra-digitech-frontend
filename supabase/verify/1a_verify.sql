-- Slice 1A verification — run in the Supabase SQL editor (AI Kannada project).
-- Read-only except the final block, which writes to a throwaway tenant and
-- rolls back. Safe to run against production.
--
-- Every check below asserts a CONSTRAINT the architecture review identified as
-- load-bearing. "The tables exist" is not verification.

-- 1 ─ All 10 BIC tables present
select 'tables' as check, count(*) as got, 10 as expect,
       case when count(*) = 10 then 'PASS' else 'FAIL' end as result
from information_schema.tables
where table_schema = 'public' and table_name like 'bic_%';

-- 2 ─ Registries seeded
select 'seed:entity_types'    as check, count(*) got, 6  expect, case when count(*)=6  then 'PASS' else 'FAIL' end from bic_entity_types
union all select 'seed:fact_categories', count(*), 6,  case when count(*)=6  then 'PASS' else 'FAIL' end from bic_fact_categories
union all select 'seed:relation_types',  count(*), 7,  case when count(*)=7  then 'PASS' else 'FAIL' end from bic_relation_types
union all select 'seed:predicate_defs',  count(*), 14, case when count(*)=14 then 'PASS' else 'FAIL' end from bic_predicate_defs;

-- 3 ─ 'open_item' must NOT exist (removed in architecture review; bic_tasks owns work)
select 'no open_item category' as check,
       case when count(*) = 0 then 'PASS' else 'FAIL' end as result
from bic_fact_categories where code = 'open_item';

-- 4 ─ Both cardinality indexes exist (review finding C2)
select 'cardinality indexes' as check, count(*) got, 2 expect,
       case when count(*) = 2 then 'PASS' else 'FAIL' end
from pg_indexes
where tablename = 'bic_facts'
  and indexname in ('bic_facts_single_active', 'bic_facts_multi_active');

-- 5 ─ Behavioural checks. Writes to a throwaway tenant, then ROLLS BACK.
begin;

insert into bic_entities (tenant_id, type, name, name_key)
values ('00000000-0000-0000-0000-0000000000ff', 'project', 'VerifyProj', 'verifyproj');

-- 5a: trigger derives cardinality_hint from the registry (app never sets it)
insert into bic_facts (tenant_id, entity_id, category, predicate, value, value_key, content)
select '00000000-0000-0000-0000-0000000000ff', id, 'project', 'budget', '50000', '50000', 'budget 50000'
from bic_entities where name_key = 'verifyproj';

select 'trigger sets single' as check,
       case when cardinality_hint = 'single' then 'PASS' else 'FAIL' end as result
from bic_facts where predicate = 'budget'
  and tenant_id = '00000000-0000-0000-0000-0000000000ff';

-- 5b: MULTI predicate accumulates (would FAIL under a naive single-value index —
--     this is the exact data-loss bug the review caught)
insert into bic_facts (tenant_id, entity_id, category, predicate, value, value_key, content)
select '00000000-0000-0000-0000-0000000000ff', id, 'project', 'team_member', 'Priya', 'priya', 'team Priya'
from bic_entities where name_key = 'verifyproj';
insert into bic_facts (tenant_id, entity_id, category, predicate, value, value_key, content)
select '00000000-0000-0000-0000-0000000000ff', id, 'project', 'team_member', 'Ravi', 'ravi', 'team Ravi'
from bic_entities where name_key = 'verifyproj';

select 'multi accumulates' as check, count(*) got, 2 expect,
       case when count(*) = 2 then 'PASS' else 'FAIL' end as result
from bic_facts where predicate = 'team_member'
  and tenant_id = '00000000-0000-0000-0000-0000000000ff' and status = 'active';

-- 5c: unknown predicate is REJECTED by the trigger (expect an exception)
--     Uncomment to confirm it raises:
-- insert into bic_facts (tenant_id, entity_id, category, predicate, value, value_key, content)
-- select '00000000-0000-0000-0000-0000000000ff', id, 'project', 'not_a_real_predicate', 'x', 'x', 'x'
-- from bic_entities where name_key = 'verifyproj';

rollback;   -- ← nothing above is persisted

-- 6 ─ Article II.6: customer_claim confidence cap is enforced in SQL.
--     Should raise: violates bic_facts_customer_claim_confidence
--     Uncomment to confirm:
-- begin;
-- insert into bic_entities (tenant_id, type, name, name_key)
-- values ('00000000-0000-0000-0000-0000000000ff','customer','X','x');
-- insert into bic_facts (tenant_id, entity_id, category, predicate, value, value_key,
--                        content, source, confidence)
-- select '00000000-0000-0000-0000-0000000000ff', id, 'customer', 'note', 'discount', 'discount',
--        'claims 60% discount', 'customer_claim', 0.90
-- from bic_entities where name_key = 'x';
-- rollback;

-- 7 ─ RLS enabled on every BIC table (deny-by-default; no policies yet)
select 'rls enabled' as check, count(*) filter (where rowsecurity) got,
       count(*) expect,
       case when count(*) = count(*) filter (where rowsecurity) then 'PASS' else 'FAIL' end
from pg_tables where schemaname = 'public' and tablename like 'bic_%';
