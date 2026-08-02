"""Decision Replay Mode — predict without executing (ADR 0004).

The new pipeline records what it WOULD do. It never sends, writes, mutates,
syncs or notifies. Production state is unchanged during comparison.

The safety property is STRUCTURAL, not disciplinary: a flow running in replay
mode is handed recorders in place of the real sender and writers, so it holds
no reference to anything that can mutate state. It cannot write even if a
future edit tries to — the same reasoning behind the Tool Registry's no-bypass
guarantee.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

REPLAY = "REPLAY"
LIVE = "LIVE"


@dataclass(frozen=True)
class RecordedOp:
    """An operation the pipeline intended to perform but did not."""
    operation: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    mode: str = REPLAY

    def key(self) -> str:
        """Stable identity for comparison — operation plus sorted arguments."""
        return f"{self.operation}({json.dumps(self.arguments, sort_keys=True, default=str)})"


class Recorder:
    """Collects intended operations instead of performing them."""

    def __init__(self) -> None:
        self.ops: List[RecordedOp] = []

    def record(self, operation: str, **arguments) -> None:
        self.ops.append(RecordedOp(operation=operation, arguments=arguments))

    def stub(self, operation: str, return_value: Any = None) -> Callable:
        """A drop-in replacement for a side-effecting callable.

        Accepts any signature, records the call, performs nothing, and returns
        a benign default so the surrounding flow continues normally.
        """
        def _stub(*args, **kwargs):
            payload = dict(kwargs)
            if args:
                payload["_positional"] = [str(a)[:200] for a in args]
            self.record(operation, **payload)
            return return_value
        return _stub

    def keys(self) -> List[str]:
        return [op.key() for op in self.ops]

    def as_dicts(self) -> List[Dict[str, Any]]:
        return [{"tool": o.operation, "arguments": o.arguments, "mode": o.mode}
                for o in self.ops]


@dataclass
class Decision:
    """The deterministic outcome of one turn — what gets compared.

    Deliberately EXCLUDES generated LLM text. Model output is
    non-deterministic, so comparing it would report a difference on every
    message even when both pipelines are correct, and a harness that always
    fails gets switched off. We compare the inputs and the choices instead
    (ADR 0004).
    """
    route: str                                  # owner | client
    role: str
    policy_result: str = "allowed"
    tools: List[str] = field(default_factory=list)
    intended_ops: List[str] = field(default_factory=list)
    prompt_fingerprint: Optional[str] = None    # hash of assembled model input
    branch: Optional[str] = None                # menu | off_topic | brochure | ...

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route": self.route,
            "role": self.role,
            "policy_result": self.policy_result,
            "tools": sorted(self.tools),
            "intended_ops": sorted(self.intended_ops),
            "prompt_fingerprint": self.prompt_fingerprint,
            "branch": self.branch,
        }


def fingerprint(messages: Any) -> str:
    """Stable hash of the assembled model input.

    This is what "identical behaviour" actually means for a non-deterministic
    component: not that the model said the same words, but that both pipelines
    handed it the same thing.
    """
    try:
        blob = json.dumps(messages, sort_keys=True, default=str, ensure_ascii=False)
    except Exception:
        blob = str(messages)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def decision_hash(decision: "Decision") -> str:
    """Stable hash of a Decision — one token that says "same decision or not".

    Lets log scanning answer "did anything change?" without diffing fields, and
    makes an accepted baseline citable as a single value.
    """
    return fingerprint(decision.to_dict())


def compare(legacy: Decision, replay: Decision) -> List[str]:
    """Field-by-field diff. Empty list means the pipelines agree.

    Returns human-readable differences rather than a bool so a mismatch can be
    logged with enough detail to act on.
    """
    diffs: List[str] = []
    a, b = legacy.to_dict(), replay.to_dict()
    for field_name in a:
        if a[field_name] != b[field_name]:
            diffs.append(f"{field_name}: legacy={a[field_name]!r} replay={b[field_name]!r}")
    return diffs


def stub_ai_reply(sentinel: str = "<REPLAY_STUBBED_AI>") -> Callable:
    """Stand-in for reply generation during replay.

    Returns a sentinel instead of calling a provider: no tokens, no cost, no
    quota impact, and nothing to compare that would be non-deterministic anyway.
    """
    def _stub(*args, **kwargs):
        return sentinel
    return _stub
