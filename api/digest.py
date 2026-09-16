"""
Asthra DigiTech — Daily WhatsApp Bot Digest
Runs via Vercel Cron (9:00 AM IST daily) → sends yesterday's bot summary
to the owner's WhatsApp.
"""

import json, os, sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

import requests

import health

# IDD-2I: the daily cron is the only scheduler on this plan (Vercel Hobby
# caps at 2 crons, both already in use — see the rollup/prune blocks below),
# so the customer_reply timeout sweep rides here rather than adding a third.
# Guarded exactly like webhook.py's BIC import: a bundling failure must
# degrade to a log line, never break the digest that already works.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from bic import (commitment as bic_commitment, config as bic_config,
                     conversion_evidence as bic_conversion_evidence,
                     outcome_producers as bic_outcome_producers,
                     pipeline_evidence as bic_pipeline_evidence)
    BIC_AVAILABLE = True
except Exception as _bic_err:  # pragma: no cover - environment dependent
    BIC_AVAILABLE = False
    print(f"BIC: package import FAILED ({_bic_err}) — timeout sweep skipped")

VERIFY_TOKEN    = os.environ.get("VERIFY_TOKEN",    "asthra_secret_2024")
WHATSAPP_TOKEN  = os.environ.get("WHATSAPP_TOKEN",  "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
SUPABASE_URL    = os.environ.get("SUPABASE_URL",    "https://kpzprllzgqlqkqgcgrbp.supabase.co")
SUPABASE_KEY    = os.environ.get("SUPABASE_KEY",    "")  # anon key — set in Vercel env vars
# OWNER_PHONE may be a comma-separated list (same env var the webhook uses).
OWNER_PHONES    = [p.strip() for p in
    os.environ.get("OWNER_PHONE", "918884448141").split(",") if p.strip()]


def _supa_get(table: str, params: dict) -> list:
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
        params=params,
        timeout=10,
    )
    return r.json() if r.ok else []


def build_digest() -> str:
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    msgs = _supa_get("whatsapp_messages", {
        "created_at": f"gte.{since}",
        "select": "phone,role,content",
    })
    leads = _supa_get("leads", {
        "select": "phone,name,company,service_needed,budget,city",
    })

    user_msgs  = [m for m in msgs if m.get("role") == "user"]
    phones     = sorted({m["phone"] for m in user_msgs})
    brochures  = sum(1 for m in msgs if m.get("role") == "assistant" and "ಬ್ರೋಚರ್ PDF" in m.get("content", ""))
    meetings   = sum(1 for m in msgs if m.get("role") == "system" and m.get("content") == "MEETING_REQUESTED")
    vip_alerts = sum(1 for m in msgs if m.get("role") == "system" and m.get("content") == "VIP_ALERTED")

    lines = [
        "☀️ ಆಸ್ತ್ರ AI — Daily Bot Report",
        "",
        f"💬 Conversations: {len(phones)}",
        f"📨 Messages received: {len(user_msgs)}",
        f"📄 Brochures sent: {brochures}",
        f"🤝 Meeting requests: {meetings}",
        f"👑 VIP/Election alerts: {vip_alerts}",
        f"📋 Total leads in DB: {len(leads)}",
    ]
    if phones:
        lines += ["", "Active chats:"]
        lines += [f"• wa.me/{p}" for p in phones[:10]]
    return "\n".join(lines)


def probe_whatsapp() -> tuple:
    """(probe_state, expires_at) — READ-ONLY. Sends no message to anyone.

    Liveness is a GET on the phone-number object: a 401/403 here is the exact
    signature of the 2026-09-08 outage. Probing by SENDING would make the
    health check itself into traffic, and a daily "still alive" message is
    spam the owner would mute within a week.

    expires_at comes from debug_token and answers the question the owner keeps
    asking — will this happen again? 0 means a permanent System User token.
    """
    if not (WHATSAPP_TOKEN and PHONE_NUMBER_ID):
        return health.UNKNOWN, None
    probe = health.UNKNOWN
    try:
        r = requests.get(
            f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}",
            params={"fields": "id"},
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=10,
        )
        probe = health.classify_probe(r.status_code, r.ok)
        # STATUS ONLY. r.text can echo account identifiers, and a health line
        # is not a place for them.
        print(f"health: whatsapp probe {r.status_code} -> {probe}")
    except Exception as e:
        print(f"health: whatsapp probe failed ({type(e).__name__}) -> UNKNOWN")

    expires_at = None
    try:
        d = requests.get(
            "https://graph.facebook.com/v19.0/debug_token",
            params={"input_token": WHATSAPP_TOKEN,
                    "access_token": WHATSAPP_TOKEN},
            timeout=10,
        )
        if d.ok:
            expires_at = ((d.json().get("data") or {}).get("expires_at"))
    except Exception as e:
        print(f"health: debug_token failed ({type(e).__name__})")
    return probe, expires_at


def probe_meta_ads() -> str:
    """Can this token actually READ an ad account? READ-ONLY, sends nothing.

    WHY THIS IS SEPARATE FROM probe_whatsapp(). The CRM's Meta dashboard was
    blind from 2026-04-08 to 2026-09-16 — five months — because its token had
    expired and nothing watched it. Liveness alone would not have been enough
    either: the dashboard calls /me/adaccounts, and a perfectly live token
    returns an empty list when `ads_read` was never granted or the ad account
    was never attached to its system user as an asset.

    WHICH COPY THIS CHECKS. The dashboard's token lives in the CRM project's
    edge-function secrets, which this process cannot read. Expiry, however, is
    a property of the TOKEN rather than of where it is stored, so probing the
    copy available here answers the question for every copy of the same value.
    The health line says "bot-side copy" rather than claiming to have checked
    the CRM's, because the two can silently diverge if only one is rotated.

    Falls back to WHATSAPP_TOKEN when FACEBOOK_ACCESS_TOKEN is unset, since
    they are currently the same value; returns None when neither exists so the
    line reads "not checked" instead of "fine".
    """
    token = (os.environ.get("FACEBOOK_ACCESS_TOKEN", "").strip()
             or WHATSAPP_TOKEN)
    if not token:
        return None
    try:
        r = requests.get(
            "https://graph.facebook.com/v19.0/me/adaccounts",
            params={"fields": "id", "limit": "1"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        count = None
        if r.ok:
            try:
                count = len(r.json().get("data") or [])
            except ValueError:
                count = None
        state = health.classify_ads_access(r.status_code, r.ok, count)
        # COUNT AND STATE ONLY — never r.text, which carries account ids.
        print(f"health: meta ads probe {r.status_code} accounts={count} -> {state}")
        return state
    except Exception as e:
        print(f"health: meta ads probe failed ({type(e).__name__}) -> UNKNOWN")
        return health.UNKNOWN


def last_inbound_at():
    """When a customer last messaged us, or None. Timestamp only — no phone,
    no content."""
    rows = _supa_get("whatsapp_messages",
                     {"role": "eq.user", "order": "created_at.desc",
                      "limit": "1", "select": "created_at"})
    if not rows:
        return None
    try:
        return datetime.fromisoformat(
            str(rows[0]["created_at"]).replace("Z", "+00:00"))
    except (ValueError, KeyError):
        return None


def record_health(value: str) -> bool:
    """Persist the verdict to app_settings — the part that outlives the logs.

    Vercel keeps runtime logs for roughly an hour, which is why the 2026-09-08
    outage left no evidence of when it began. This row is the answer to "since
    when?", and it is an UPSERT on one key rather than an append, so it cannot
    grow without bound and needs no retention rule.

    NO TOKEN, NO PHONE, NO CUSTOMER DATA — see health.compose_record. This
    table already holds a plaintext credential for another project; it must
    not gain one from here.
    """
    # SERVICE ROLE, NOT ANON — and this was verified against the live
    # database, not assumed. app_settings has RLS ENABLED WITH ZERO POLICIES,
    # so the anon key this module uses for reads is denied every write. Using
    # it here would reproduce the exact silent 401 that left `leads` empty for
    # weeks: PostgREST maps insufficient_privilege to 401, requests.post does
    # not raise on it, and the failure would look identical to success.
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not key:
        # Fail loudly rather than fall back to anon, which cannot work.
        print("health: record SKIPPED — no service-role credential")
        return False
    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/app_settings",
            headers={"apikey": key, "Authorization": f"Bearer {key}",
                     "Content-Type": "application/json",
                     "Prefer": "resolution=merge-duplicates"},
            json={"key": "bot_health_last_check", "value": value,
                  "updated_at": datetime.now(timezone.utc).isoformat()},
            timeout=5,
        )
        # CHECKED. The one discipline this codebase learned the hard way.
        if not r.ok:
            print(f"health: record failed {r.status_code}")
        return r.ok
    except Exception as e:
        print(f"health: record failed ({type(e).__name__})")
        return False


def send_to_owner(text: str):
    ok_any = False
    for phone in OWNER_PHONES:
        # One phone failing (network error, bad number) must not block the rest.
        try:
            r = requests.post(
                f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages",
                headers={
                    "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                    "Content-Type": "application/json",
                },
                json={
                    "messaging_product": "whatsapp",
                    "to": phone,
                    "type": "text",
                    "text": {"body": text, "preview_url": False},
                },
                timeout=10,
            )
            print(f"digest WA send to {phone} {r.status_code}: {r.text[:120]}")
            ok_any = ok_any or r.ok
        except Exception as e:
            print(f"digest WA send to {phone} FAILED: {e}")
    return ok_any


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        # Allow only Vercel Cron or a manual call with ?key=<VERIFY_TOKEN>
        ua  = self.headers.get("User-Agent", "")
        key = parse_qs(urlparse(self.path).query).get("key", [""])[0]
        if "vercel-cron" not in ua and key != VERIFY_TOKEN:
            self.send_response(403)
            self.end_headers()
            return

        try:
            digest = build_digest()
            ok = send_to_owner(digest)
            body = {"ok": ok, "digest": digest}
        except Exception as e:
            print(f"digest error: {e}")
            body = {"ok": False, "error": str(e)}

        # BIC Slice 1C: 30-day retention for the replay diagnostic table.
        # Rides the existing daily cron rather than adding a fourth scheduler,
        # and does not depend on pg_cron (not guaranteed on the free tier).
        # Strictly best-effort — retention must never affect the digest, and a
        # failure here is a housekeeping miss, not an incident.
        # Audit finding M-3: bic_rollup_tool_invocations has existed since
        # Slice 1A and was NEVER CALLED, so the audit table grew without
        # bound. Wired onto the existing daily cron rather than adding a
        # scheduler — Vercel Hobby caps at 2 crons and both are in use.
        try:
            r = requests.post(
                f"{SUPABASE_URL}/rest/v1/rpc/bic_rollup_tool_invocations",
                headers={
                    "apikey": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
                    "Authorization": f"Bearer {os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')}",
                    "Content-Type": "application/json",
                },
                json={"retain_days": 90},
                timeout=20,
            )
            print(f"bic tool-invocation rollup: {r.status_code} {r.text[:80]}")
        except Exception as e:
            print(f"bic tool-invocation rollup failed (ignored): {e}")

        try:
            r = requests.post(
                f"{SUPABASE_URL}/rest/v1/rpc/bic_prune_replay_records",
                headers={
                    "apikey": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
                    "Authorization": f"Bearer {os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')}",
                    "Content-Type": "application/json",
                },
                json={"retain_days": 30},
                timeout=10,
            )
            print(f"bic replay retention: {r.status_code} {r.text[:80]}")
        except Exception as e:
            print(f"bic replay retention failed (ignored): {e}")

        # IDD-2I Step 5: sweep customer_reply expectations whose window
        # closed with no reply. Reports as data (I7) rather than discarding —
        # every swept row becomes a NO_RESPONSE/TIMED_OUT observation.
        # No-ops harmlessly until migration 17 is applied (table won't exist
        # yet) and BIC_AVAILABLE is False if the import failed — either way
        # this must never affect the digest send above, which already ran.
        if BIC_AVAILABLE:
            try:
                result = bic_outcome_producers.sweep_customer_reply_timeouts()
                print(f"bic outcome timeout sweep: {result}")
            except Exception as e:
                print(f"bic outcome timeout sweep failed (ignored): {e}")

        # IDD-2B: "what have we promised and are we about to miss it?" — the
        # question Commitment exists to answer. READ-ONLY, deliberately.
        #
        # NOTHING IS MARKED MISSED HERE. "`missed` is recorded, never
        # deleted... missed commitments are the reliability signal", and a
        # cron that transitioned rows would manufacture that judgement from a
        # clock tick, with no reason and no actor. A real miss goes through
        # the transition RPC with both. This only reports.
        #
        # Rides the existing daily cron — no third scheduler, per the note at
        # the top of this file.
        if BIC_AVAILABLE:
            try:
                due = bic_commitment.overdue(bic_config.DEFAULT_TENANT_ID)
                if due:
                    # Short references, not raw UUIDs — the SAME handles
                    # `#commitment <ref> ...` accepts, so the digest names
                    # exactly what the owner can act on. Never a phone, never
                    # a party id.
                    refs = ", ".join(bic_commitment.reference(c)
                                     for c in due[:10])
                    kinds = sorted({str(c.get("obligation")) for c in due})
                    send_to_owner(
                        f"⏰ {len(due)} overdue commitment(s): "
                        f"{', '.join(kinds)}\n"
                        f"{refs}{' …' if len(due) > 10 else ''}\n"
                        f"👉 Close with #commitment <ref> met — nothing is "
                        f"marked missed automatically.")
                print(f"bic overdue commitments: {len(due)}")
            except Exception as e:
                print(f"bic overdue commitment check failed (ignored): "
                      f"{type(e).__name__}")

        # IDD-2A/2C: refresh the business pipeline evidence.
        #
        # biz.pipeline.new_enquiries_per_month@1 is volatility `fast` — a 24h
        # staleness bound — so a value nobody recomputes goes STALE within a
        # day and 2H correctly stops accepting it. This cron runs at 09:00 IST
        # daily, which is inside every calendar month it measures, so the
        # producer's "current month only" rule always holds.
        #
        # RIDES THE EXISTING SCHEDULER. Vercel Hobby caps at 2 crons and both
        # are in use, so this is a fourth best-effort block on the daily job
        # rather than a third cron — the same move the rollup, retention and
        # sweep blocks above already made.
        #
        # RECOMPUTATION IS SAFE. record() writes valid_from = the measurement
        # instant, so today's reading supersedes yesterday's instead of
        # competing with it. Running twice in one day is therefore harmless.
        #
        # A FAILURE MUST NOT FABRICATE A ZERO. record() returns None when the
        # store refuses; nothing here converts that into a recorded value. The
        # previous measurement simply stands and ages into STALE, which is the
        # honest outcome — a false zero would read as "no enquiries this
        # month" and is exactly the failure this predicate was built to avoid.
        if BIC_AVAILABLE:
            try:
                claim = bic_pipeline_evidence.record(
                    bic_config.DEFAULT_TENANT_ID)
                if claim is None:
                    print("bic pipeline evidence: NOT recorded (store refused) "
                          "— previous measurement stands and will age to STALE")
                else:
                    # Value and window only. No party ids, no subject list.
                    print(f"bic pipeline evidence: "
                          f"new_enquiries_per_month={claim['value']} "
                          f"valid_until={claim['valid_until']}")
            except Exception as e:
                print(f"bic pipeline evidence failed (ignored): "
                      f"{type(e).__name__}")

        # ── 5 · CONVERSION COHORT FINALIZATION ────────────────────────────
        #
        # THE BRAIN OWNS THE MEASUREMENT LIFECYCLE. A cohort closes 30 days
        # after its LAST enquirer's first contact, which is a different date
        # for every month and is nobody's job to remember. Without this block
        # the conversion metric would exist, be correct, and never be written.
        #
        # RIDES THE EXISTING SCHEDULER, like the four blocks above. Vercel
        # Hobby caps at 2 crons and both are in use, so this is a fifth
        # best-effort block on the daily job rather than a third cron.
        #
        # SAFE TO RUN EVERY DAY. finalize() is idempotent per COHORT, not
        # merely per run: a cohort that already carries a claim is never asked
        # again, so the daily job writes nothing on the vast majority of days
        # and exactly one claim on the day a cohort closes.
        #
        # SELF-HEALING. The months it considers run from the registry epoch to
        # now, derived from evidence rather than from when this last ran — so
        # an outage of any length is repaired on the next successful run
        # instead of leaving a permanent hole.
        #
        # A FAILURE MUST NOT FABRICATE A RATE. finalize() records nothing it
        # could not measure, and an unmeasurable or open cohort is reported,
        # never written as a zero.
        if BIC_AVAILABLE:
            try:
                fin = bic_conversion_evidence.finalize(
                    bic_config.DEFAULT_TENANT_ID)
                # Cohort labels and counts only. No party ids, no subject list.
                print(f"bic conversion evidence: considered={fin['considered']} "
                      f"recorded={[r['cohort'] for r in fin['recorded']]} "
                      f"provisional={fin['provisional']} "
                      f"unmeasurable={len(fin['unmeasurable'])} "
                      f"already_final={len(fin['already_final'])}")
                for r in fin["recorded"]:
                    print(f"bic conversion evidence: FINALIZED {r['cohort']} "
                          f"rate={r['rate']} "
                          f"n={r['numerator']}/{r['denominator']}")
            except Exception as e:
                print(f"bic conversion evidence failed (ignored): "
                      f"{type(e).__name__}")

        # ── Bot health ────────────────────────────────────────────────
        # SIXTH best-effort block on the same daily cron. Vercel Hobby caps at
        # 2 crons and both are in use, so this rides the existing job exactly
        # as the rollup, retention, sweep, pipeline-evidence and conversion
        # blocks above do.
        #
        # LAST, deliberately. It reports on the transport the digest itself
        # needs, so running it after the send means the probe describes the
        # same credential state the send just exercised.
        #
        # THE CIRCULARITY IS ACCEPTED, NOT HIDDEN: if the token is dead this
        # alert cannot be delivered either. That is why the verdict is written
        # to app_settings first — a durable row survives the ~1h log retention
        # and answers "since when?", which is the question nobody could answer
        # on 2026-09-08.
        try:
            probe, expires_at = probe_whatsapp()
            expiry = health.classify_expiry(expires_at)
            silence = health.classify_silence(last_inbound_at())
            ads = probe_meta_ads()
            record_health(health.compose_record(probe, expiry, silence, ads=ads))
            line = health.compose_health_line(probe, expiry, silence, ads=ads)
            print(f"health: {line}")
            # Only escalate a real problem. A daily "all fine" message is how
            # an alert channel becomes noise the owner filters out.
            if (probe == health.DEAD or silence[0]
                    or expiry[0] in (health.EXPIRED, health.EXPIRING)
                    or ads in (health.DEAD, health.ADS_NO_ACCOUNTS,
                               health.ADS_FORBIDDEN)):
                send_to_owner(line)
        except Exception as e:
            print(f"health check failed (ignored): {type(e).__name__}")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, format, *args):
        pass
