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
    original = state.any_agent_running
    state.any_agent_running = lambda: answer
    try:
        yield
    finally:
        state.any_agent_running = original


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
    results.append(("real sweep returns a bool", isinstance(state.any_agent_running(), bool)))

    # It asked for a Claude process for as long as Claude was the only agent,
    # and stayed that way once Codex and Gemini arrived -- so on a machine
    # running Codex and no Claude every pid-less session was judged dead the
    # moment it was written, and the pet never noticed Codex at all.
    from claude_pet import agents as agent_registry

    watched = {spec["comm"] for spec in agent_registry.AGENTS.values() if spec.get("comm")}
    results.append((f"the sweep looks for every agent ({', '.join(sorted(watched))})",
                    {"claude", "codex", "node"} <= watched))

    # And the pid check, which has the same shape: an entry carrying a pid but
    # no agent used to be compared against the name "claude" alone.
    live = os.getpid()
    mine = state._comm_of(live)
    for agent in ("codex", "gemini"):
        spec = agent_registry.AGENTS[agent]
        # Stands in for the real thing: whether this interpreter passes for the
        # agent is beside the point, only that the agent is what gets asked.
        entry = {"state": "running", "ts": NOW, "seen": NOW,
                 "locator": {"claude_pid": live, "agent": agent}}
        results.append((f"a {agent} session is judged as {agent}",
                        state.is_alive(entry, NOW)
                        == agent_registry.is_process(agent, live)))
    results.append((f"...and a pid with no agent is not assumed to be claude (this is {mine!r})",
                    state.is_alive({"state": "running", "ts": NOW, "seen": NOW,
                                    "locator": {"claude_pid": live}}, NOW)
                    == (mine in watched or mine == "claude")))
    return results


def idle_session_checks() -> list[tuple[str, bool]]:
    """A session left alone for hours is idle, not gone.

    Age used to decide this before the process was consulted, so a session
    sitting at its prompt overnight was dropped at six hours -- taking the pet
    with it when it was the last one, and leaving it dead until an entirely new
    session was started, since only `SessionStart` brings it back.
    """
    own_pid = os.getpid()
    results = []

    def quiet(hours: float) -> dict:
        return {
            "state": "idle", "ts": NOW - hours * 3600,
            # `comm` is what this test process really is, standing in for a
            # Claude process that is alive but has said nothing.
            "locator": {"claude_pid": own_pid, "comm": _own_comm()},
        }

    for hours in (1, 7, 48):
        results.append(
            (f"quiet for {hours}h with a live process stays",
             state.is_alive(quiet(hours), NOW))
        )
    results.append(
        ("...and is still counted",
         state.aggregate({"sessions": {"a": quiet(48)}})["sessions"] == 1)
    )

    # The process, not the clock, is what settles it.
    gone = {"state": "idle", "ts": NOW, "locator": {"claude_pid": DEAD_PID, "comm": "claude"}}
    results.append(("a dead process is gone however fresh", not state.is_alive(gone, NOW)))

    # Entries that predate pid recording have nothing better than the clock.
    ancient = {"state": "idle", "ts": NOW - 7 * 3600}
    with claude_running(True):
        results.append(("no pid, past the TTL -> gone", not state.is_alive(ancient, NOW)))
        results.append(
            ("no pid, within it -> live", state.is_alive({"state": "idle", "ts": NOW}, NOW))
        )
    return results


def _own_comm() -> str:
    with open(f"/proc/{os.getpid()}/comm", encoding="utf-8") as stream:
        return stream.read().strip()


def cpu_checks() -> list[tuple[str, bool]]:
    """`running` is dropped once the process stops doing anything.

    `Stop` is the clean way out of `running`, but an interrupted turn never
    sends one, and the pet then sat on "working" until the five-minute backstop
    expired with nothing running.

    The verdict is read off `busy_at`, which lives on the session in the state
    file rather than in the overlay's memory -- otherwise `claude-pet status`
    would reach a different answer than the pet it is reporting on.
    """
    results = []

    def running(age: float, idle_for: float) -> dict:
        return {
            "state": "running", "ts": NOW - age,
            "busy_at": NOW - idle_for, "locator": {"claude_pid": 4242},
        }

    results.append(
        ("stale running with an idle process goes idle",
         state.effective_state(running(60, 60), NOW) == "idle")
    )
    results.append(
        ("stale running with a busy process stays",
         state.effective_state(running(60, 1), NOW) == "running")
    )
    # Nothing is second-guessed before the window is up, whatever the process
    # is doing -- a pause between tool calls is not the end of a turn.
    results.append(
        ("fresh running is left alone", state.effective_state(running(5, 60), NOW) == "running")
    )
    # Sessions written before this existed carry no `busy_at`, and must fall
    # back to the backstop rather than be declared idle on no evidence.
    without = {"state": "running", "ts": NOW - 60, "locator": {"claude_pid": 4242}}
    results.append(
        ("no observation means no verdict", state.effective_state(without, NOW) == "running")
    )
    # Only `running` is second-guessed. `waiting` is a claim about the user,
    # and an idle Claude is exactly what being blocked on you looks like.
    blocked = {"state": "waiting", "ts": NOW - 600, "busy_at": NOW - 600,
               "locator": {"claude_pid": 4242}}
    results.append(
        ("idle process still needs you", state.effective_state(blocked, NOW) == "waiting")
    )
    # The backstop still applies on its own.
    results.append(
        ("backstop still fires", state.effective_state(running(400, 1), NOW) == "idle")
    )

    # A hook event is proof of work, so it has to refresh the observation --
    # otherwise a long turn would be judged idle between samples.
    fresh = state.effective_state(
        {"state": "running", "ts": NOW, "busy_at": NOW, "locator": {"claude_pid": 4242}}, NOW
    )
    results.append(("an event counts as work", fresh == "running"))
    return results


def stuck_waiting_checks() -> list[tuple[str, bool]]:
    """A `waiting` that was only the idle nudge heals without another event.

    Existing state files written by the older hook may hold such an entry, and
    nothing would ever clear it -- `waiting` has no dwell and the process it
    belongs to may live for days. Judged at read time so an update alone fixes
    it, on every machine.
    """
    results = []
    live = state.is_alive  # not exercised here; effective_state alone decides
    nudge = "Claude is waiting for your input"
    base = {"state": "waiting", "ts": NOW, "seen": NOW}

    stuck = dict(base, detail=nudge, turn_over=None)
    results.append(("an idle-nudge waiting with no turn is demoted to idle",
                    state.effective_state(stuck, NOW) == "idle"))
    stuck_after = dict(base, detail=nudge, turn_over=True)
    results.append(("...and after a finished turn too",
                    state.effective_state(stuck_after, NOW) == "idle"))
    mid_turn = dict(base, detail=nudge, turn_over=False)
    results.append(("mid-turn the same words still mean needs-you",
                    state.effective_state(mid_turn, NOW) == "waiting"))
    real_ask = dict(base, detail="Claude needs your permission to use Bash", turn_over=None)
    results.append(("a permission ask is never demoted",
                    state.effective_state(real_ask, NOW) == "waiting"))
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

    live_results = liveness_checks() + idle_session_checks() + cpu_checks() + stuck_waiting_checks()
    for name, ok in live_results:
        failures += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    total = len(CASES) + 2 + len(live_results)
    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
