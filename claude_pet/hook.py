"""Claude Code hook bridge.

Invoked once per hook event with the event JSON on stdin. It runs inside every
Claude turn, so it stays stdlib-only, does no network or image work, and always
exits 0 -- a broken pet must never break a session.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from . import config, launch, locate, state

#: Events on which the session's location is (re)recorded. Cheap -- a handful
#: of /proc reads -- but pointless on every tool call, and doing it on prompt
#: submit as well means sessions that predate `install-hooks` still get one.
LOCATE_ON = {"SessionStart", "UserPromptSubmit"}

#: Sentinel: report the detail but leave the state as it was.
KEEP = "__keep__"

#: Hook event -> pet state. `None` means "forget this session", `KEEP` means
#: "this says nothing about whether Claude is working".
EVENT_STATES: dict[str, str | None] = {
    "SessionStart": "waving",
    "UserPromptSubmit": "running",
    "PreToolUse": "running",
    "PostToolUse": "running",
    "Notification": "waiting",
    "Stop": "review",
    # A subagent finishing does not mean the main agent is working -- and
    # background subagents finish *after* Stop, which used to re-arm `running`
    # on a turn that was already over and leave the pet stuck there.
    "SubagentStop": KEEP,
    "PreCompact": "running",
    "PostCompact": "running",
    "SessionEnd": None,
}


def _detail(event: str, payload: dict[str, Any]) -> str:
    """Extra line for the speech bubble.

    The bubble already shows the state label, so this stays empty whenever the
    label alone says everything -- otherwise the bubble reads like a stutter.
    """
    if event in {"PreToolUse", "PostToolUse"}:
        return str(payload.get("tool_name") or "")
    if event == "Notification":
        # The only place Claude gives us real prose worth surfacing.
        return str(payload.get("message") or "")
    if event == "SubagentStop":
        return "subagent finished"
    if event in {"PreCompact", "PostCompact"}:
        return "compacting context"
    return ""


def _tool_failed(payload: dict[str, Any]) -> bool:
    """Best-effort detection of a failed tool call in a PostToolUse payload."""
    response = payload.get("tool_response")
    if isinstance(response, dict):
        if response.get("is_error") is True or response.get("success") is False:
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    forced_event = argv[0] if argv else None

    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        raw = ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    event = forced_event or str(payload.get("hook_event_name") or "")
    if event not in EVENT_STATES:
        return 0

    pet_state = EVENT_STATES[event]
    if event == "PostToolUse" and _tool_failed(payload):
        pet_state = "failed"

    session_id = str(payload.get("session_id") or "default")
    fields: dict[str, Any] = {
        "detail": _detail(event, payload) if pet_state else None,
        "cwd": str(payload.get("cwd") or "") or None,
        "locator": locate.locator() if event in LOCATE_ON else None,
    }
    # Omitting `state` entirely leaves the stored one alone; passing None
    # deletes the session.
    if pet_state != KEEP:
        fields["state"] = pet_state

    try:
        state.update(session_id, **fields)
    except OSError:
        return 0

    if event == "SessionStart" and config.load().get("autostart", True):
        launch.spawn_detached(reason="SessionStart")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
