"""Claude Code hook bridge.

Invoked once per hook event with the event JSON on stdin. It runs inside every
Claude turn, so it stays stdlib-only, does no network or image work, and always
exits 0 -- a broken pet must never break a session.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import config, state

#: Hook event -> pet state. `None` means "forget this session".
EVENT_STATES: dict[str, str | None] = {
    "SessionStart": "waving",
    "UserPromptSubmit": "running",
    "PreToolUse": "running",
    "PostToolUse": "running",
    "Notification": "waiting",
    "Stop": "review",
    "SubagentStop": "running",
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
        return "서브에이전트 완료"
    if event in {"PreCompact", "PostCompact"}:
        return "컨텍스트 압축"
    return ""


def _tool_failed(payload: dict[str, Any]) -> bool:
    """Best-effort detection of a failed tool call in a PostToolUse payload."""
    response = payload.get("tool_response")
    if isinstance(response, dict):
        if response.get("is_error") is True or response.get("success") is False:
            return True
    return False


def _overlay_alive() -> bool:
    try:
        pid = int(state.pid_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return Path(f"/proc/{pid}").exists()


def _spawn_overlay() -> None:
    """Start the overlay detached, so the pet appears without a manual step."""
    if _overlay_alive():
        return
    try:
        log = state.state_dir()
        log.mkdir(parents=True, exist_ok=True)
        handle = open(log / "overlay.log", "ab", buffering=0)  # noqa: SIM115 - handed to child
    except OSError:
        return
    root = Path(__file__).resolve().parent.parent
    environment = {**os.environ, "CLAUDE_PET_AUTOSTARTED": "1"}
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = f"{root}:{existing}" if existing else str(root)
    try:
        subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-m", "claude_pet", "run"],
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=handle,
            start_new_session=True,
            cwd=str(root),
            env=environment,
        )
    except OSError:
        pass
    finally:
        handle.close()


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
    try:
        state.update(
            session_id,
            state=pet_state,
            detail=_detail(event, payload) if pet_state else None,
            cwd=str(payload.get("cwd") or "") or None,
        )
    except OSError:
        return 0

    if event == "SessionStart" and config.load().get("autostart", True):
        _spawn_overlay()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
