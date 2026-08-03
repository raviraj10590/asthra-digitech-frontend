"""Brain runtime — the single entry point for one inbound turn.

    BrainRequest → Policy → flow selection → BrainResponse

Phase 1C scope ONLY. This is deliberately NOT the orchestrator loop (Phase 2):
there is no planning, no reasoning, no tool selection here. 1C moves the
*request pipeline*, nothing else, so behaviour must stay byte-identical.

Dependency direction is inverted on purpose: the Brain never imports
application code. Flows are INJECTED by the caller. That keeps the security
layer independent of the transport, avoids a circular import with webhook.py,
and means existing business functions stay the source of truth — wrapped, never
rewritten.
"""

from dataclasses import dataclass
from typing import Callable

from . import identity, policy
from .contract import BrainRequest, BrainResponse

# A flow takes the resolved identity plus the normalised request and returns a
# response. Implementations live with the business functions they wrap.
Flow = Callable[[policy.Principal, BrainRequest], BrainResponse]


@dataclass(frozen=True)
class Flows:
    """The two pipelines that exist today. Injected, never imported."""
    owner: Flow
    client: Flow


# Roles that receive the internal/executive pipeline. CLIENT and anything
# unrecognised fall to the customer pipeline — the fail-closed default, since an
# unknown role resolves to CLIENT in the policy layer.
#
# THE single definition — webhook.py imports this rather than repeating the
# tuple (review M1). MANAGER was removed 2026-08-03: it was listed here but not
# in do_POST's legacy fork, so a MANAGER's pipeline depended on the feature
# flag. 1C must be byte-identical, and legacy never routed MANAGER internally.
#
# MANAGER is still a real rank in policy.ROLE_ORDER and still authorizes tools
# at min_role STAFF/MANAGER. It is only the PIPELINE choice that excludes it.
# Adding it back is a behaviour change requiring owner approval — 1D.
INTERNAL_ROLES = ("OWNER", "STAFF")


def handle(request: BrainRequest, flows: Flows) -> BrainResponse:
    """Resolve identity, choose the pipeline, delegate.

    Identity is resolved from request.sender_id, which the ADAPTER must take
    from the transport's verified payload — never from message text
    (Article II.1). The Brain cannot enforce that on its own; it is asserted in
    the adapter and covered by characterization tests.

    Resolution goes through bic.identity — the ONE canonical resolver shared
    with the legacy path. That is what makes Decision Replay meaningful: a
    disagreement can only indicate a real logic difference, never two lookup
    implementations differing.
    """
    principal = identity.resolve(request.sender_id, channel=request.channel)

    internal = principal.role in INTERNAL_ROLES
    flow = flows.owner if internal else flows.client

    response = flow(principal, request)

    # Diagnostics for the 1C old-vs-new comparison. Never user-visible.
    response.meta.setdefault("role", principal.role)
    response.meta.setdefault("flow", "owner" if internal else "client")
    if principal.degraded:
        # Role resolution fell back — the reply may differ from a healthy run,
        # so the comparison harness must not treat it as a clean sample.
        response.meta["degraded_identity"] = True
    return response
