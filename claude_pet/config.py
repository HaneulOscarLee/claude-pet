"""Pet discovery and user configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "pet": None,          # active pet id; None -> first one found
    "height": 132,        # on-screen sprite height in pixels
    "anchor": "bottom-right",
    "fps": 10,
    "walk": True,         # wander along the screen edge while idle
    # Off by default: the speech bubble is the intended channel, and a
    # desktop notification on top of it is just the same news twice.
    "notifications": False,
    "language": "auto",   # bubble label language: auto (locale) | en | ko
    "look_at_mouse": True,  # v2 packs only: face the pointer while idle
    "autostart": True,    # let the SessionStart hook launch the overlay
    "position": None,     # [x, y] once the user drags the pet somewhere
}


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "claude-pet"


def config_path() -> Path:
    return config_dir() / "config.json"


def load() -> dict[str, Any]:
    settings = dict(DEFAULTS)
    try:
        stored = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return settings
    if isinstance(stored, dict):
        settings.update({key: value for key, value in stored.items() if key in DEFAULTS})
    return settings


def save(settings: dict[str, Any]) -> None:
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    payload = {key: value for key, value in settings.items() if key in DEFAULTS}
    config_path().write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex"))


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"))


def pet_search_paths() -> list[Path]:
    """Directories scanned for pet packs.

    `~/.codex/pets` is included so packs already installed with
    `npx codex-pets add` are picked up without being copied.
    """
    return [claude_home() / "pets", codex_home() / "pets"]


def discover() -> dict[str, Path]:
    """Map pet id -> pack directory. Earlier search paths win."""
    found: dict[str, Path] = {}
    for root in pet_search_paths():
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if (entry / "pet.json").is_file() and entry.name not in found:
                found[entry.name] = entry
    return found


def active_pet_dir(settings: dict[str, Any] | None = None) -> Path | None:
    settings = load() if settings is None else settings
    available = discover()
    if not available:
        return None
    wanted = settings.get("pet")
    if wanted and wanted in available:
        return available[wanted]
    return next(iter(available.values()))
