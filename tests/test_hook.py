"""Checks for how hook events turn into pet states.

Runs against a throwaway state directory, so it neither reads nor disturbs the
state of a pet that happens to be running.

Plain stdlib, no test runner needed:

    python3 tests/test_hook.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def run(events: list[tuple[str, dict]], session_id: str = "s") -> dict:
    """Feed a sequence of hook events to one session and return its entry.

    Liveness is pinned: these fixtures record no usable Claude pid, so on a
    machine with no Claude running -- CI, notably -- every session would be
    pruned as dead between events and the sequences would never build up.
    """
    from claude_pet import hook, state

    state.any_claude_running = lambda: True

    for name, extra in events:
        payload = {"hook_event_name": name, "session_id": session_id, **extra}
        original = sys.stdin
        sys.stdin = io_stub(json.dumps(payload))
        try:
            hook.main([])
        finally:
            sys.stdin = original
    return state.read().get("sessions", {}).get(session_id) or {}


class io_stub:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


def notification_checks() -> list[tuple[str, bool]]:
    """`Notification` means two unrelated things, and only one is `needs you`.

    Claude Code sends one when it is blocked and cannot go on, and another
    about a minute after a turn ends because nobody has typed since. Treating
    them alike left the pet demanding attention for the sole offence of you
    reading its output -- and `waiting` never times out, so it stayed there.
    """
    idle = {"message": "Claude is waiting for your input"}
    asks = {"message": "Claude needs your permission to use Bash"}
    results = []

    after_turn = run([
        ("UserPromptSubmit", {}),
        ("PostToolUse", {"tool_name": "Bash"}),
        ("Stop", {}),
        ("Notification", idle),
    ], "after-turn")
    results.append(("idle nudge after a turn is ignored", after_turn.get("state") == "review"))
    results.append(("...and does not overwrite the detail", after_turn.get("detail") == ""))

    blocked = run([
        ("UserPromptSubmit", {}),
        ("PreToolUse", {"tool_name": "Bash"}),
        ("Notification", asks),
    ], "blocked")
    results.append(("a permission ask still needs you", blocked.get("state") == "waiting"))

    # Same wording, but mid-turn: Claude asked a question and cannot continue.
    questioned = run([
        ("UserPromptSubmit", {}),
        ("PreToolUse", {"tool_name": "AskUserQuestion"}),
        ("Notification", idle),
    ], "questioned")
    results.append(("mid-turn it still needs you", questioned.get("state") == "waiting"))

    # Events keep arriving after a turn ends, so the flag cannot be inferred
    # from whichever one came last.
    late = run([
        ("UserPromptSubmit", {}),
        ("Stop", {}),
        ("SubagentStop", {}),
        ("Notification", idle),
    ], "late-subagent")
    results.append(("a late subagent does not un-end the turn", late.get("state") == "review"))

    # A new prompt reopens the turn, so the next one is judged afresh.
    again = run([
        ("UserPromptSubmit", {}),
        ("Stop", {}),
        ("UserPromptSubmit", {}),
        ("Notification", idle),
    ], "reprompted")
    results.append(("a new prompt reopens the turn", again.get("state") == "waiting"))
    return results


def lifecycle_checks() -> list[tuple[str, bool]]:
    results = []

    ended = run([("UserPromptSubmit", {}), ("SessionEnd", {})], "ended")
    results.append(("SessionEnd forgets the session", ended == {}))

    failed = run([
        ("UserPromptSubmit", {}),
        ("PostToolUse", {"tool_name": "Bash", "tool_response": {"is_error": True}}),
    ], "failed")
    results.append(("a failed tool shows failed", failed.get("state") == "failed"))

    # Background subagents finish after Stop, and used to re-arm `running` on a
    # turn that was already over.
    kept = run([("UserPromptSubmit", {}), ("Stop", {}), ("SubagentStop", {})], "kept")
    results.append(("SubagentStop leaves the state alone", kept.get("state") == "review"))

    unknown = run([("UserPromptSubmit", {}), ("NotAThing", {})], "unknown")
    results.append(("an unknown event changes nothing", unknown.get("state") == "running"))

    # "Leave the state alone" for a session nobody has heard of has nothing to
    # leave alone, and used to invent a stateless entry that read as idle.
    orphan = run([("SubagentStop", {})], "orphan")
    results.append(("SubagentStop alone creates nothing", orphan == {}))
    return results


def main() -> int:
    # A scratch state directory: these must not read or disturb a running pet.
    workspace = tempfile.mkdtemp(prefix="claude-pet-test-")
    os.environ["XDG_STATE_HOME"] = workspace
    os.environ["CLAUDE_PET_NO_AUTOSTART"] = "1"

    from claude_pet import config

    # Autostart would launch a real overlay from the test run.
    config.load = lambda: {**config.DEFAULTS, "autostart": False}

    failures = 0
    total = 0
    for label, results in (
        ("notifications", notification_checks()),
        ("lifecycle", lifecycle_checks()),
    ):
        print(f"{label}:")
        for name, ok in results:
            total += 1
            failures += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
