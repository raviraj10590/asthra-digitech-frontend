"""Suite-wide test configuration — imported by pytest before any test module.

THE BUG THIS CLOSES
--------------------
bic.policy.BOOTSTRAP_OWNERS (and bic.identity's copy of it, bound in via
`from .policy import BOOTSTRAP_OWNERS`) is computed ONCE, at first import,
from os.environ.get("OWNER_PHONE", ...). Individual test files used to each
call os.environ.setdefault("OWNER_PHONE", ...) at their own top of file —
harmless in isolation, but 39 files disagreed on the value (14 used
"918884448141,918861369951", 25 used "910000000001,910000000002"), and
setdefault() is a no-op once any earlier-imported file has already set it.
So whichever file's bic.policy import happened to run first in a given
pytest process decided the bootstrap-owner numbers for every test that
followed — a full `pytest tests/` run got lucky by always collecting a
matching file first; any differently-ordered subset invocation could not.

tests/test_routing_integration.py::TestOwnerRoutingEquivalence hit exactly
this and was given its own scoped mock.patch fix. This closes the same hole
at the root for every other file, so no test needs to know or care which
file ran before it.

WHY HERE, NOT A NEW bic/ RESET HOOK
------------------------------------
pytest imports every conftest.py in scope BEFORE it imports any test module
in that scope (that ordering is pytest's own collection contract, not
something this file arranges). Setting the environment variable here — once
— means bic.policy is never imported anywhere before this line has already
run, so there is nothing left to race. No production module needed a new
test-only function for this.

os.environ.setdefault, not a plain assignment: an operator or CI job that
has deliberately exported OWNER_PHONE before invoking pytest is expressing
an intentional override, and this file must not silently discard it.
"""

import os

os.environ.setdefault("OWNER_PHONE", "910000000001,910000000002")
os.environ.setdefault("SUPABASE_KEY", "test-anon-key")


# THE CALL-HOURS CLOCK (2026-10-03). The live pipeline promises "call now"
# only between 9 am and 9 pm IST and reads the hour through
# webhook._ist_hour(). Fixed at midday for every test, so a suite run at
# night cannot turn every "ಈಗಲೇ" assertion red. Tests of the rule itself
# (tests/test_call_hours.py) set their own hour.
import pytest


@pytest.fixture(autouse=True)
def _midday_in_india(monkeypatch):
    import sys as _sys
    mod = _sys.modules.get("webhook")
    if mod is not None and hasattr(mod, "_ist_hour"):
        monkeypatch.setattr(mod, "_ist_hour", lambda: 12)
    yield


# CALL REMINDERS OFF BY DEFAULT IN TESTS (2026-10-03). The authenticated
# sweep runs them; in production they read Brain and the CRM. Any test that
# drives the endpoint without stubbing them must not reach a network, so the
# suite defaults to off and tests/test_call_reminders.py turns them on.
@pytest.fixture(autouse=True)
def _call_reminders_off(monkeypatch):
    monkeypatch.setenv("CALL_REMINDERS", "off")
    yield
