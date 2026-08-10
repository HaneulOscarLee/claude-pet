"""Checks for following more than one coding agent.

Claude Code, Codex and Gemini CLI share a hook vocabulary but not a spelling of
it, and not a way of being recognised on the process table. Both of those are
easy to get subtly wrong in ways that only show up as a pet that sits on the
wrong state, so they are pinned here.

Plain stdlib, no test runner needed:

    python3 tests/test_agents.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_pet import agents  # noqa: E402

#: What each agent's settings file may legally contain, from its own schema.
#: Writing anything else is how the pet ends up configured against an event
#: that does not exist.
GEMINI_EVENTS = {
    "BeforeTool", "AfterTool", "BeforeAgent", "AfterAgent", "Notification",
    "SessionStart", "SessionEnd", "PreCompress", "BeforeModel", "AfterModel",
    "BeforeToolSelection",
}
CLAUDE_EVENTS = set(agents.CANONICAL_EVENTS)


def naming_checks() -> list[tuple[str, bool]]:
    results = []

    # The renames that make Gemini work at all.
    for ours, theirs in (
        ("UserPromptSubmit", "BeforeAgent"),
        ("Stop", "AfterAgent"),
        ("PreToolUse", "BeforeTool"),
        ("PostToolUse", "AfterTool"),
    ):
        results.append(
            (f"gemini calls {ours} {theirs}",
             agents.to_agent_event("gemini", ours) == theirs)
        )
    # And the ones nobody renamed, which is why one bridge works at all.
    results.append(
        ("everyone agrees on SessionStart",
         {agents.to_agent_event(a, "SessionStart") for a in agents.known()} == {"SessionStart"})
    )

    # An event an agent does not have must come back as None, not as itself.
    # Returning the canonical name for anything unrecognised wrote
    # `SubagentStop` into Gemini's settings, which has no such event.
    results.append(
        ("gemini has no SubagentStop",
         agents.to_agent_event("gemini", "SubagentStop") is None)
    )
    results.append(
        ("codex has no SubagentStop either",
         agents.to_agent_event("codex", "SubagentStop") is None)
    )
    results.append(
        ("claude has all of them",
         all(agents.to_agent_event("claude", e) == e for e in agents.CANONICAL_EVENTS))
    )

    # Nothing may be offered to an agent that its own schema would reject.
    written = {agents.to_agent_event("gemini", e) for e in agents.CANONICAL_EVENTS}
    written.discard(None)
    results.append(("every name written for gemini is one it knows", written <= GEMINI_EVENTS))
    written = {agents.to_agent_event("claude", e) for e in agents.CANONICAL_EVENTS}
    written.discard(None)
    results.append(("...and for claude", written <= CLAUDE_EVENTS))

    # Incoming events arrive in the caller's vocabulary and must land on ours.
    for theirs, ours in (
        ("BeforeAgent", "UserPromptSubmit"),
        ("AfterAgent", "Stop"),
        ("BeforeTool", "PreToolUse"),
        ("AfterTool", "PostToolUse"),
        ("PreCompress", "PreCompact"),
        ("SessionStart", "SessionStart"),
    ):
        results.append((f"{theirs} arrives as {ours}", agents.to_canonical(theirs) == ours))
    results.append(
        ("an unknown event is left alone", agents.to_canonical("Whatever") == "Whatever")
    )

    # Every translation must round-trip, or an agent's own event would be
    # recorded under a name the pet does not act on.
    broken = [
        (a, e)
        for a in agents.known()
        for e in agents.CANONICAL_EVENTS
        if (name := agents.to_agent_event(a, e)) and agents.to_canonical(name) != e
    ]
    results.append((f"every name round-trips ({len(broken)} broken)", not broken))
    return results


def process_checks() -> list[tuple[str, bool]]:
    """Recognising a running turn, which a session's liveness rests on."""
    results = []
    table: dict[int, tuple[str, str]] = {}
    original_comm, original_cmdline = agents._comm_of, agents._cmdline_of
    agents._comm_of = lambda pid: table.get(int(pid), ("", ""))[0]
    agents._cmdline_of = lambda pid: table.get(int(pid), ("", ""))[1]
    try:
        table[1] = ("claude", "claude")
        table[2] = ("codex", "/opt/codex/bin/codex")
        table[3] = ("node", "node /home/me/.npm-global/bin/gemini")
        # The one that matters: Node runs plenty of things that are not Gemini,
        # and comm alone would have every one of them pass.
        table[4] = ("node", "node /home/me/some-server.js")
        table[5] = ("bash", "/bin/bash")

        results.append(("a claude process is claude", agents.identify(1) == "claude"))
        results.append(("a codex process is codex", agents.identify(2) == "codex"))
        results.append(("a gemini process is gemini", agents.identify(3) == "gemini"))
        results.append(("an unrelated node is nothing", agents.identify(4) is None))
        results.append(("a shell is nothing", agents.identify(5) is None))
        results.append(
            ("...and specifically does not pass for gemini", not agents.is_process("gemini", 4))
        )
        results.append(("a dead pid is nothing", agents.identify(999) is None))
        results.append(
            ("an unknown agent id matches nothing", not agents.is_process("nope", 1))
        )
    finally:
        agents._comm_of, agents._cmdline_of = original_comm, original_cmdline
    return results


def registry_checks() -> list[tuple[str, bool]]:
    results = [
        ("claude is still the default", agents.DEFAULT_AGENT in agents.known()),
        ("every agent has a label", all(agents.label(a) for a in agents.known())),
        (
            "every agent names a settings file",
            all(str(agents.settings_path(a)).startswith(os.path.expanduser("~"))
                for a in agents.known()),
        ),
        (
            "every agent supports at least a turn's start and end",
            all(agents.to_agent_event(a, "SessionStart")
                and agents.to_agent_event(a, "Stop") for a in agents.known()),
        ),
    ]
    return results


def main() -> int:
    failures = 0
    total = 0
    for label, results in (
        ("names", naming_checks()),
        ("processes", process_checks()),
        ("registry", registry_checks()),
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
