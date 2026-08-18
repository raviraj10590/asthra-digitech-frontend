-- BIC 2B hardening — D13: a MERGED party must name its survivor.
--
-- THE DEFECT
-- ----------
-- bic_parties.resolution_state already admits 'MERGED' (IDD-2D §2.1), but no
-- column records WHICH party absorbed it. A party could therefore be marked
-- MERGED and become an orphan: claims still reference its knowledge_id and
-- nothing says where to redirect them. The state is reachable today and the
-- pointer is not — that asymmetry is the bug.
--
-- IDD-2D §6.1 step 3: "Absorbed party is marked MERGED with a merged_into
-- pointer — never deleted." This adds exactly that pointer and nothing else.
--
-- WHAT THIS MIGRATION DELIBERATELY DOES NOT DO
-- --------------------------------------------
-- No merge. No auto-merge. No scoring. No dispute resolution. No unmerge.
-- Those are 2D, and 2D has no sovereign or controlled evidence to operate on
-- yet — production holds only CONTACT-class WhatsApp phone numbers, which
-- §3.4 R1 forbids from merging anything at any confidence. This migration
-- makes the merge STATE safe to exist; it grants no ability to enter it.
--
-- SAFE ON LIVE DATA: the column is nullable and every existing row is
-- PROVISIONAL, so the constraint below is satisfied by all of them (0 rows in
-- production at time of writing, but this would hold at any row count).

alter table bic_parties
  add column if not exists merged_into uuid references bic_parties(knowledge_id);

comment on column bic_parties.merged_into is
  'IDD-2D §6.1: the survivor that absorbed this party. Set only when
   resolution_state = MERGED. The absorbed party is NEVER deleted and its
   knowledge_id stays valid forever, resolving to the survivor — which is what
   makes a merge reversible (§6.2). No ON DELETE action: losing a survivor
   must fail loudly, not cascade.';

-- The biconditional. MERGED without a survivor is the orphan this fixes;
-- merged_into without MERGED is a pointer nothing honours.
alter table bic_parties
  drop constraint if exists bic_parties_merged_pair;
alter table bic_parties
  add constraint bic_parties_merged_pair
  check ((resolution_state = 'MERGED') = (merged_into is not null));

-- A party cannot absorb itself: that is a one-node cycle, and the resolver
-- would spin on it forever.
alter table bic_parties
  drop constraint if exists bic_parties_no_self_merge;
alter table bic_parties
  add constraint bic_parties_no_self_merge
  check (merged_into is null or merged_into <> knowledge_id);

create index if not exists bic_parties_merged_into_idx
  on bic_parties (merged_into) where merged_into is not null;
