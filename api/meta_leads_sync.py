"""Fetch recent Meta form leads and reach the ones who never messaged (see
meta_leads.py for the why and the rules).

Runs from api/recovery.py after each authenticated sweep. META_LEADS_MODE:

    off      (default) nothing at all
    dry_run  read from Meta, decide, COUNT. No writes, no sends. Logs the
             form's field NAMES once, never values.
    crm      dry_run + claim the lead and add it to the CRM (Calls page).
    send     crm + open the conversation with the approved template.

Never raises. Logs carry counts, Meta error codes and the last 4 digits of a
phone at most — never a name, a token or a form answer.
"""
import json
import os
from datetime import datetime, timezone

import requests

import bairavi
import meta_leads as ml
import webhook as w

GRAPH = "https://graph.facebook.com/v19.0"
MODES = ("off", "dry_run", "crm", "send")
# The ad account the CRM's Meta page reports on (not a secret).
DEFAULT_AD_ACCOUNT = "325030182"


def mode() -> str:
    m = os.environ.get("META_LEADS_MODE", "off").strip().lower()
    return m if m in MODES else "off"


def _token() -> str:
    return (os.environ.get("FACEBOOK_ACCESS_TOKEN", "").strip()
            or os.environ.get("WHATSAPP_TOKEN", "").strip())


class MetaError(RuntimeError):
    """Carries Meta's error code only."""


def _graph(path: str, params: dict, token: str = None):
    r = requests.get(f"{GRAPH}/{path}", params=params,
                     headers={"Authorization": f"Bearer {token or _token()}"}, timeout=10)
    if not r.ok:
        try:
            code = (r.json().get("error") or {}).get("code")
        except ValueError:
            code = None
        raise MetaError(f"http={r.status_code} code={code}")
    return r.json()


# Leads per ad in the one request. A day's leads on one ad is far below this.
LEADS_PER_AD = 25


def fetch_leads(now) -> list:
    """Leads created in the last MAX_AGE_HOURS on the account's active ads.

    ONE REQUEST. The first version asked each ad for its leads separately; on
    the first production run that was one request per active ad, and the
    second run was refused with Meta error 17 (request limit reached). Field
    expansion returns every active ad with its newest leads nested, and the
    time window is applied here.
    """
    account = os.environ.get("META_AD_ACCOUNT_ID", DEFAULT_AD_ACCOUNT).strip()
    ads = _graph(f"act_{account}/ads", {
        "fields": f"id,leads.limit({LEADS_PER_AD}){{id,created_time,field_data,form_id}}",
        "effective_status": json.dumps(["ACTIVE"]),
        "limit": "100"}).get("data") or []
    cutoff = ml.since(now)
    leads, seen = [], set()
    for ad in ads:
        for lead in (ad.get("leads") or {}).get("data") or []:
            created = ml._ts(lead.get("created_time"))
            if not lead.get("id") or lead["id"] in seen:
                continue
            if created is None or created.timestamp() <= cutoff:
                continue
            seen.add(lead["id"])
            leads.append(lead)
    return leads


def template_status() -> tuple:
    """(status, waba_last4) of the template in the WhatsApp account that owns
    the BOT'S OWN phone number — the only account it can be sent from.

    WHY THIS EXISTS (2026-10-03). The template was created through the CRM,
    whose create function uses its configured account; the bot's number
    belongs to a different one, where the template did not exist at all. A
    send would have failed for every lead and marked each one as handled.
    So "approved" is checked from the sender's side, every run, before any
    lead is claimed. Status words are Meta's (APPROVED, PENDING, REJECTED…);
    MISSING means it is not in that account at all.
    """
    phone = _graph(w.PHONE_NUMBER_ID, {"fields": "health_status"}, token=w.WHATSAPP_TOKEN)
    waba = next((e.get("id") for e in (phone.get("health_status") or {}).get("entities") or []
                 if e.get("entity_type") == "WABA"), None)
    if not waba:
        return "NO_ACCOUNT", ""
    rows = _graph(f"{waba}/message_templates",
                  {"name": ml.TEMPLATE_NAME, "fields": "name,status,language"},
                  token=w.WHATSAPP_TOKEN).get("data") or []
    match = [r for r in rows if r.get("name") == ml.TEMPLATE_NAME
             and r.get("language") == ml.TEMPLATE_LANGUAGE]
    return (match[0].get("status") or "UNKNOWN") if match else "MISSING", str(waba)[-4:]


def wrote_before(phone: str) -> bool:
    """Has this lead already written to us — from THIS number, or from any
    number, carrying this number in the form handoff?

    THE SECOND CHECK (live, 2026-10-03). A lead typed 9194…0033 on the form
    but messages from 9195…0033; the handoff they sent on 2 Oct carried
    "Phone number: +91944…0033" in its body. Matching the sender's number
    alone missed it, and the template went to the second number.
    """
    base = {"direction": "eq.inbound", "user_id": f"eq.{w.CRM_OWNER_USER_ID}",
            "select": "id", "limit": "1"}
    for extra in ({"phone": f"eq.{phone}"},
                  {"body": f"ilike.*{phone[-10:]}*",
                   "created_at": f"gte.{ml.since_iso(days=7)}"}):
        r = requests.get(f"{w.CRM_SUPABASE_URL}/rest/v1/whatsapp_messages",
                         headers=w._crm_headers(), params=dict(base, **extra), timeout=5)
        r.raise_for_status()
        if r.json():
            return True
    return False


def handled(phone: str, lead_id: str) -> bool:
    r = requests.get(f"{w.SUPABASE_URL}/rest/v1/whatsapp_messages",
                     headers=w._supa_headers(),
                     params={"phone": f"eq.{phone}", "role": "eq.system",
                             "content": f"like.{ml.MARK}{lead_id}::*",
                             "select": "id", "limit": "1"}, timeout=5)
    r.raise_for_status()
    return bool(r.json())


def send_template(phone: str, params) -> dict:
    payload = {
        "messaging_product": "whatsapp", "to": phone, "type": "template",
        "template": {"name": ml.TEMPLATE_NAME,
                     "language": {"code": ml.TEMPLATE_LANGUAGE},
                     "components": [{"type": "body", "parameters": [
                         {"type": "text", "text": p} for p in params]}]},
    }
    try:
        delivery = w.classify_delivery(w._wa_post(payload))
    except requests.RequestException as e:
        delivery = w.classify_delivery(exc=e)
    # The CRM shows what the customer received, with WhatsApp's verdict.
    w._mirror_outbound_to_crm(phone, message_type="template", body=ml.rendered(params),
                              wa_message_id=delivery["wamid"],
                              status=w._CRM_STATUS[delivery["verdict"]])
    return delivery


def contact(lead: dict, phone: str, m: str):
    """Claim, add to the CRM, and (send) open the conversation.
    Returns (name, kva, sent_ok) or None when the claim failed."""
    lid = lead["id"]
    # THE CLAIM COMES FIRST. If it cannot be written, nothing else happens:
    # an unrecorded send could be repeated by the next run.
    if w.save_message(phone, "system", ml.marker(lid, "claimed")) != w.SAVE_OK:
        return None
    text = ml.form_text(lead)
    parsed = bairavi.parse(text)
    w.sync_lead_to_crm(phone, {
        "name": parsed.get("name") or None,
        "city": parsed.get("location") or None,
        "service_needed": (f"Transformer {parsed['capacity_kva']} kVA"
                           if parsed.get("capacity_kva") else "Transformer"),
        "source": "bairavi-transformer",
    })
    if m != "send":
        w.save_message(phone, "system", ml.marker(lid, "crm"))
        return parsed.get("name"), parsed.get("capacity_kva"), True
    params = ml.template_params(parsed)
    delivery = send_template(phone, params)
    ok = delivery["verdict"] == w.DELIVERY_ACCEPTED
    if ok:
        # The transcript the bot will read when they reply: their form, then
        # our message, under the Bairavi flow marker.
        w.save_messages([(phone, "user", text),
                         (phone, "assistant", bairavi.flow_marker(()))])
    w.save_message(phone, "system", ml.marker(lid, "sent" if ok else
                                              "rejected_" + delivery["verdict"].lower()))
    return parsed.get("name"), parsed.get("capacity_kva"), ok


def run(now=None) -> dict:
    """One pass. Returns counts by decision (no PII). Never raises."""
    m = mode()
    if m == "off":
        return {"mode": "off"}
    now = now or datetime.now(timezone.utc)
    counts = {"mode": m}
    try:
        leads = fetch_leads(now)
    except MetaError as e:
        print(f"META_LEADS fetch_failed {e}")
        return dict(counts, error="meta_fetch_failed")
    except Exception as e:
        print(f"META_LEADS fetch_failed type={type(e).__name__}")
        return dict(counts, error="meta_fetch_failed")
    counts["fetched"] = len(leads)
    # THE SENDER'S VIEW OF THE TEMPLATE. Reported in every mode; in "send" a
    # template that is not APPROVED stops the run before any lead is claimed.
    try:
        status, waba = template_status()
    except Exception as e:
        print(f"META_LEADS template_check_failed {e if isinstance(e, MetaError) else type(e).__name__}")
        status, waba = "CHECK_FAILED", ""
    counts["template"] = status
    counts["waba"] = waba
    if m == "send" and status != "APPROVED":
        print(f"META_LEADS send_blocked template={status}")
        counts["blocked"] = "template_not_approved"
        m = "dry_run"
    if leads and m == "dry_run":
        names = sorted({str(f.get("name")) for f in leads[0].get("field_data") or []})
        print("META_LEADS field_names " + json.dumps(names, ensure_ascii=False))
    contacted = []
    for lead in sorted(leads, key=lambda x: x.get("created_time") or ""):
        if len(contacted) >= ml.MAX_PER_RUN:
            counts["deferred"] = counts.get("deferred", 0) + 1
            continue
        phone = ml.normalize_phone(ml.phone_of(lead))
        try:
            internal = bool(phone) and w.get_role(phone)[0] != "CLIENT"
            first = ml.decide(lead, now, wrote_before=False, handled=False, internal=internal)
            if first == ml.CONTACT:
                decision = ml.decide(lead, now, internal=internal,
                                     handled=handled(phone, lead["id"]),
                                     wrote_before=wrote_before(phone))
            else:
                decision = first
        except Exception as e:
            print(f"META_LEADS check_failed type={type(e).__name__}")
            counts["check_failed"] = counts.get("check_failed", 0) + 1
            continue
        counts[decision] = counts.get(decision, 0) + 1
        if decision != ml.CONTACT or m == "dry_run":
            continue
        try:
            result = contact(lead, phone, m)
        except Exception as e:
            print(f"META_LEADS contact_failed type={type(e).__name__} phone=...{phone[-4:]}")
            counts["contact_failed"] = counts.get("contact_failed", 0) + 1
            continue
        if result is None:
            counts["claim_failed"] = counts.get("claim_failed", 0) + 1
            continue
        name, kva, ok = result
        contacted.append((name, phone, f"{kva} kVA" if kva else None, ok))
    counts["contacted"] = len(contacted)
    if contacted:
        try:
            w.notify_owner(ml.owner_summary(contacted))
        except Exception as e:
            print(f"META_LEADS owner_alert_failed type={type(e).__name__}")
    print("META_LEADS " + json.dumps(counts, sort_keys=True))
    return counts
