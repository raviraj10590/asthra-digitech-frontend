"""Collect the Brain's health and publish it to the CRM (see brain_health.py).

Called from api/recovery.py after an authenticated sweep. Never raises: a
health snapshot that cannot be built or written must not turn a successful
recovery sweep into a failure. Every read is narrow (named columns, one key
of app_settings — that table also holds another project's credential, so it
is never read wholesale).
"""
import os
from datetime import datetime, timezone

import requests

import brain_health as bh

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://kpzprllzgqlqkqgcgrbp.supabase.co")
TABLE = "brain_health_snapshots"


def _brain_headers():
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def _get(path, params):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{path}", headers=_brain_headers(),
                     params=params, timeout=5)
    r.raise_for_status()
    return r.json()


def collect(sweep=None, now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    events = _get("bic_webhook_events", {
        "created_at": f"gte.{bh.since(now, hours=24)}",
        "select": "state,failure_class,created_at,updated_at,completed_at",
        "limit": "5000"})
    last = _get("bic_webhook_events", {"select": "created_at",
                                       "order": "created_at.desc", "limit": "1"})
    accepted = _get("bic_webhook_events", {"state": "eq.ACCEPTED", "select": "state",
                                           "limit": "1000"})
    recovery = _get("whatsapp_messages", {
        "role": "eq.system", "content": "like.RECOVERY::*",
        "created_at": f"gte.{bh.since(now, days=7)}", "select": "content", "limit": "2000"})
    health = _get("app_settings", {"key": "eq.bot_health_last_check", "select": "value",
                                   "limit": "1"})
    return bh.build(
        now=now, events_24h=events,
        last_event_at=(last[0]["created_at"] if last else None),
        accepted_total=len(accepted),
        # Only the marker text is counted; brain_health keeps the result word.
        recovery_contents=[r.get("content") or "" for r in recovery],
        health_value=(health[0].get("value") if health else None),
        sweep=sweep, commit=os.environ.get("VERCEL_GIT_COMMIT_SHA", ""),
        source="recovery")


def publish(snapshot: dict) -> bool:
    url = os.environ.get("CRM_SUPABASE_URL", "")
    key = os.environ.get("CRM_SUPABASE_SERVICE_KEY", "")
    owner = os.environ.get("CRM_OWNER_USER_ID", "")
    if not (url and key and owner):
        print("HEALTH_SNAPSHOT skipped=crm_not_configured")
        return False
    r = requests.post(f"{url}/rest/v1/{TABLE}",
                      headers={"apikey": key, "Authorization": f"Bearer {key}",
                               "Content-Type": "application/json", "Prefer": "return=minimal"},
                      json={"user_id": owner, "source": snapshot.get("source", "recovery"),
                            "snapshot": snapshot},
                      timeout=5)
    if not r.ok:
        # STATUS ONLY — never r.text.
        print(f"HEALTH_SNAPSHOT publish_failed status={r.status_code}")
    return r.ok


def run(sweep=None) -> str:
    """'ok' / 'failed'. Never raises."""
    try:
        ok = publish(collect(sweep))
    except Exception as e:
        print(f"HEALTH_SNAPSHOT failed type={type(e).__name__}")
        return "failed"
    return "ok" if ok else "failed"
