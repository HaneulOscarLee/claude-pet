"""Checks for multi-session aggregation and per-session dwells.

Plain stdlib, no test runner needed:

    python3 tests/test_aggregate.py
"""

import contextlib
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_pet import state  # noqa: E402

NOW = time.time()


@contextlib.contextmanager
def claude_running(answer: bool):
    """Pin the "is any Claude running" answer.

    Fixtures below carry no recorded pid, so without this they would depend on
    whether a Claude process happens to exist -- which passes on a developer's
    machine and fails in CI.
    """
    original = state.any_claude_running
    state.any_claude_running = lambda: answer
    try:
        yield
    finally:
        state.any_claude_running = original


def session(name: str, age_seconds: float) -> dict:
    return {"state": name, "detail": f"{name}-detail", "ts": NOW - age_seconds}


#: (label, sessions, expected aggregate state)
CASES = [
    # A finished session should announce itself even while others work...
    ("2 running + fresh review", {"a": session("running", 1), "b": session("running", 1),
                                  "c": session("review", 2)}, "review"),
    # ...but must hand the pet back once its dwell is up, rather than dragging
    # everything to idle while real work is still going on.
    ("2 running + review 25s old", {"a": session("running", 1), "b": session("running", 1),
                                    "c": session("review", 25)}, "running"),
    ("only review, fresh", {"c": session("review", 2)}, "review"),
    ("only review, 25s old", {"c": session("review", 25)}, "idle"),
    ("failed fresh + running", {"a": session("failed", 2), "b": session("running", 1)}, "failed"),
    ("failed 25s old + running", {"a": session("failed", 25), "b": session("running", 1)}, "running"),
    ("waving 1s old", {"c": session("waving", 1)}, "waving"),
    ("waving 10s old", {"c": session("waving", 10)}, "idle"),
    # waiting has no dwell at all: a pet that stops asking defeats the point.
    ("waiting 3h old", {"c": session("waiting", 10800)}, "waiting"),
    # running has a generous one, as a backstop against an event arriving after
    # a turn ended and re-arming it forever.
    ("running 100s old", {"c": session("running", 100)}, "running"),
    ("running 400s old", {"c": session("running", 400)}, "idle"),
    ("stale running loses to fresh review",
     {"a": session("running", 400), "b": session("review", 2)}, "review"),
    ("every session expired", {"a": session("review", 25), "b": session("failed", 25)}, "idle"),
    ("no sessions", {}, "idle"),
    ("unknown state name", {"a": {"state": "nonsense", "ts": NOW}}, "idle"),
]


#: A pid that certainly is not a Claude process. pid 1 is init, and it is alive,
#: so it also proves the check looks at `comm` and not merely at existence.
DEAD_PID = 2**22 - 1


def liveness_checks() -> list[tuple[str, bool]]:
    """A session outlives its Claude process only until someone looks."""
    own_pid = os.getpid()
    results = []

    gone = {"state": "running", "ts": NOW, "locator": {"claude_pid": DEAD_PID}}
    results.append(("dead claude pid is not live", not state.is_alive(gone, NOW)))
    results.append(
        ("dead session leaves no state", state.aggregate({"sessions": {"a": gone}})["state"] == "idle")
    )
    results.append(
        ("dead session is not counted", state.aggregate({"sessions": {"a": gone}})["sessions"] == 0)
    )

    # This test process is alive but is not named "claude", so a pid that exists
    # is still rejected unless it really is a Claude session.
    impostor = {"state": "running", "ts": NOW, "locator": {"claude_pid": own_pid}}
    results.append(("live pid with wrong comm is not live", not state.is_alive(impostor, NOW)))

    # Entries with no recorded pid predate pid recording. They fall back to
    # "is any Claude running at all", because trusting them outright kept the
    # pet alive for the whole TTL after everything had closed.
    no_locator = {"state": "running", "ts": NOW}
    empty_locator = {"state": "running", "ts": NOW, "locator": {}}
    with claude_running(True):
        results.append(("no pid + Claude running -> live", state.is_alive(no_locator, NOW)))
        results.append(
            ("empty locator + Claude running -> live", state.is_alive(empty_locator, NOW))
        )
        mixed = {"sessions": {"dead": gone, "live": session("waiting", 1)}}
        aggregated = state.aggregate(mixed)
        results.append(("live session survives a dead one", aggregated["state"] == "waiting"))
        results.append(("only live sessions counted", aggregated["sessions"] == 1))

    with claude_running(False):
        results.append(("no pid + no Claude -> dead", not state.is_alive(no_locator, NOW)))
        results.append(
            (
                "no pid + no Claude aggregates to idle",
                state.aggregate({"sessions": {"a": no_locator}})["state"] == "idle",
            )
        )

    # The real sweep must answer without raising. Whether it finds anything
    # depends on the machine, so that is deliberately not asserted.
    results.append(("real sweep returns a bool", isinstance(state.any_claude_running(), bool)))
    return results


def main() -> int:
    failures = 0
    # These cases are about dwells and priority, not liveness, so the liveness
    # answer is pinned rather than left to whatever the machine is running.
    with claude_running(True):
        for label, sessions, expected in CASES:
            result = state.aggregate({"sessions": sessions})
            ok = result["state"] == expected
            failures += not ok
            print(
                f"  {'PASS' if ok else 'FAIL'}  {label:<28} -> "
                f"{result['state']} (expected {expected})"
            )

        # A session past its dwell has nothing left to say.
        stale = state.aggregate({"sessions": {"a": session("review", 25)}})
        ok = stale["detail"] == ""
        failures += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  expired session drops detail  -> {stale['detail']!r}")

        # Live-session count is independent of dwells.
        counted = state.aggregate(
            {"sessions": {"a": session("review", 25), "b": session("running", 1)}}
        )
        ok = counted["sessions"] == 2
        failures += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  count ignores dwells          -> {counted['sessions']}")

    live_results = liveness_checks()
    for name, ok in live_results:
        failures += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    total = len(CASES) + 2 + len(live_results)
    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
