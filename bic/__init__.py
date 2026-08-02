"""Business Intelligence Core — deterministic layer.

Governed by docs/BUSINESS-INTELLIGENCE-CORE-v1.0.md (FROZEN).

Slice 1B provides:
  config  — env-driven settings
  db      — the single Supabase access point (+ query counting)
  policy  — identity and authorization; fails closed; contains NO AI
  tools   — the only path by which a business tool may execute

Execution contract, with no bypass:

    Policy → Tool Registry → Tool → Audit → Response

Import `tools.invoke`; never a handler directly. Handlers are private by
construction — nothing else exports them.
"""

from . import config, db, policy, tools  # noqa: F401

__all__ = ["config", "db", "policy", "tools"]
