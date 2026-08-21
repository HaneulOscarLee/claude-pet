"""Installing the GNOME Shell extension that answers where the pointer is.

Kept opt-in and kept small. An extension runs inside the compositor's own
process, so the bar for asking someone to install one is high; this one has a
single method, watches nothing, and owns no bus name of its own -- it answers
`global.get_pointer()` on the shell's existing name.

The reason it has to exist is in `pointer.py`: the overlay runs under
XWayland, XWayland is told where the pointer is only while the pointer is
over one of its own windows, and there is no portal on GNOME 46 that will
say otherwise. The compositor knows. This is a window to ask through.

The shell reads the extensions directory once, at startup. Enabling an
unknown one through gsettings does nothing at all -- measured: no reaction,
no log line. So installing takes effect at the next login, and saying so is
part of installing it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

UUID = "claude-pet-pointer@claude-pet.local"

#: Where the shell looks for extensions belonging to this user.
def extensions_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "gnome-shell" / "extensions"


def install_path() -> Path:
    return extensions_dir() / UUID


def source_path() -> Path | None:
    """The copy shipped with claude-pet, wherever it was installed from."""
    for root in (Path(__file__).resolve().parent.parent, Path("/usr/lib/claude-pet")):
        candidate = root / "assets" / "gnome-extension" / UUID
        if (candidate / "metadata.json").is_file():
            return candidate
    return None


def on_gnome() -> bool:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    return "GNOME" in desktop.upper()


def installed() -> bool:
    return (install_path() / "metadata.json").is_file()


def enabled() -> bool:
    """Whether the shell has been told to run it, which is not whether it is running."""
    try:
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.shell", "enabled-extensions"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return UUID in out


def supported_here() -> bool:
    """Whether installing it would help: GNOME, on Wayland."""
    return on_gnome() and os.environ.get("XDG_SESSION_TYPE", "") == "wayland"


def _enabled_list() -> list[str]:
    try:
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.shell", "enabled-extensions"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return []
    # gsettings prints a GVariant array of strings; near enough to JSON once
    # the quoting is normalised, and a parse failure must not lose the list.
    try:
        return list(json.loads(out.replace("'", '"'))) if out.startswith("[") else []
    except json.JSONDecodeError:
        return []


def _set_enabled(names: list[str]) -> bool:
    value = "[" + ", ".join(f"'{name}'" for name in names) + "]"
    try:
        return subprocess.run(
            ["gsettings", "set", "org.gnome.shell", "enabled-extensions", value],
            capture_output=True, timeout=5,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def install() -> bool:
    """Copy it into place and switch it on. Takes effect at the next login."""
    source = source_path()
    if source is None:
        return False
    target = install_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)

    names = _enabled_list()
    if UUID not in names:
        names.append(UUID)
        return _set_enabled(names)
    return True


def ensure() -> str:
    """Put the extension on disk where it helps, idempotently.

    For setup and update, which both want "and calling works from anywhere"
    to hold without a separate step. Does not and cannot activate it -- GNOME
    loads extensions only at login -- so a caller that installs it should tell
    the user to log out and back in. The overlay also reminds them on its next
    start, which covers the update-from-the-menu path where there is no
    terminal to print to.

    Returns "installed" (just now), "already" (was there), "unsupported"
    (not GNOME, or not Wayland), or "failed".
    """
    if not supported_here():
        return "unsupported"
    if installed():
        return "already"
    return "installed" if install() else "failed"


def active() -> bool:
    """Whether the extension is not just installed but answering.

    Installed-but-not-active is the "needs a re-login" state, and telling the
    two apart is the whole point of the reminder.
    """
    if not (supported_here() and installed()):
        return False
    from . import pointer

    return pointer.bridge_present()


def uninstall() -> bool:
    removed = False
    target = install_path()
    if target.exists():
        shutil.rmtree(target)
        removed = True
    names = _enabled_list()
    if UUID in names:
        _set_enabled([name for name in names if name != UUID])
        removed = True
    return removed
