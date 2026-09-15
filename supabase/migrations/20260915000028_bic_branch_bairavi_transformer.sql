-- BIC — Decision Record: a sixth deterministic branch, BAIRAVI_TRANSFORMER
--
-- WHY THIS MIGRATION EXISTS AT ALL
-- --------------------------------
-- 20260815000001 wrote the rule this obeys: "Adding a branch to the code means
-- adding it here — deliberately, in a migration — rather than a new value
-- appearing silently in production." The CHECK constraint is the mechanism
-- that makes that non-optional, and it worked: adding the branch in Python
-- failed two guard tests before any of it could reach production.
--
-- WHAT THE BRANCH IS
-- ------------------
-- Between 2026-09-12 and 2026-09-15, sixteen Meta Lead Ads handoffs about
-- transformers reached this WhatsApp number. Fifteen were answered with
-- Asthra DigiTech's digital-marketing services menu — social media, websites,
-- election campaigns — sent to people who had just stated a kVA requirement.
-- Those enquiries belong to Bairavi Trans Solutions, a related transformer
-- manufacturer reached on a shared number.
--
-- WHY IT IS NOT 'OFF_TOPIC'
-- -------------------------
-- Reusing OFF_TOPIC was the first implementation and it was wrong. A
-- transformer enquiry is not off-topic — it is a DIFFERENT BUSINESS. Labelling
-- it OFF_TOPIC would send anyone reading the decision record hunting for a
-- redirect rule when the answer is a routing boundary, and it would make the
-- volume of Bairavi traffic unqueryable: 15 of Asthra's 36 September
-- "enquiries" were Bairavi's, and nothing in the record would have said so.
--
-- CONSTRAINT ONLY. No column is added, no row is touched, no data is
-- rewritten. The allowed set is WIDENED, so every existing row stays valid and
-- the change is backwards compatible in both directions: older code writing
-- one of the five original values still passes.
--
-- APPLY THIS BEFORE DEPLOYING THE CODE. The order matters and is not
-- cosmetic. With the code live and the constraint un-widened, every Bairavi
-- turn's decision-record insert violates the CHECK and the turn loses its
-- audit row — the customer would still be answered correctly, but the record
-- of why would be gone, which is the one thing 3D exists to prevent.

alter table bic_decision_records
  drop constraint if exists bic_decision_branch_id_check;

alter table bic_decision_records
  add constraint bic_decision_branch_id_check
  check (branch_id is null or branch_id in (
    'MENU_REQUEST',
    'OFF_TOPIC',
    'CHAT_PAUSED',
    'BROCHURE_REQUEST',
    'NEW_CONTACT',
    -- Bairavi Trans Solutions — transformer enquiry on a shared number.
    'BAIRAVI_TRANSFORMER'));

comment on constraint bic_decision_branch_id_check on bic_decision_records is
  'The deterministic branches that exist in run_client_pipeline. Widened
   2026-09-15 with BAIRAVI_TRANSFORMER. NULL still means no deterministic
   branch claimed the turn (the AI path), which is as much a fact as a named
   branch is.';
