"""Checks for multi-session aggregation and per-session dwells.

Plain stdlib, no test runner needed:

    python3 tests/test_aggregate.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_pet import state  # noqa: E402

NOW = time.time()


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
    # These two have no dwell: waiting must keep asking, and only Claude ends a run.
    ("waiting 300s old", {"c": session("waiting", 300)}, "waiting"),
    ("running 300s old", {"c": session("running", 300)}, "running"),
    ("every session expired", {"a": session("review", 25), "b": session("failed", 25)}, "idle"),
    ("no sessions", {}, "idle"),
    ("unknown state name", {"a": {"state": "nonsense", "ts": NOW}}, "idle"),
]


def main() -> int:
    failures = 0
    for label, sessions, expected in CASES:
        result = state.aggregate({"sessions": sessions})
        ok = result["state"] == expected
        failures += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {label:<28} -> {result['state']} (expected {expected})")

    # A session past its dwell has nothing left to say.
    stale = state.aggregate({"sessions": {"a": session("review", 25)}})
    ok = stale["detail"] == ""
    failures += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  expired session drops detail  -> {stale['detail']!r}")

    # Live-session count is independent of dwells.
    counted = state.aggregate({"sessions": {"a": session("review", 25), "b": session("running", 1)}})
    ok = counted["sessions"] == 2
    failures += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  count ignores dwells          -> {counted['sessions']}")

    total = len(CASES) + 2
    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
