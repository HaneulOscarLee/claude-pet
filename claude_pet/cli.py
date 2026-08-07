"""Command line interface."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

from . import config, state
from .errors import PetError

# `sprites` pulls in Pillow and `registry` opens sockets, so both are imported
# inside the commands that need them: the `hook` subcommand runs on every tool
# call and must not pay for either.

HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Notification",
    "Stop",
    "SubagentStop",
    "SessionEnd",
)
#: Substring that identifies a hook entry as ours. Must match what
#: `install-hooks` writes, which is the launcher path ending in `claude-pet`.
HOOK_MARKER = "claude-pet"


def launcher_path() -> Path:
    from . import launch

    return launch.launcher_path()


# --------------------------------------------------------------------- pets


def cmd_list(_args: argparse.Namespace) -> int:
    from . import sprites

    available = config.discover()
    if not available:
        print("No pet packs installed. Browse with `claude-pet search`, install with `claude-pet add <id>`.")
        return 0
    active = config.active_pet_dir()
    for pet_id, directory in available.items():
        marker = "*" if active and directory == active else " "
        try:
            pet = sprites.load_pet(directory)
            counts = pet.frame_counts
            summary = (
                f"v{pet.version} · {pet.cell[0]}x{pet.cell[1]} · "
                f"{sum(counts.values())} frames · {len(pet.looks)} looks"
            )
        except sprites.SpriteError as exc:
            summary = f"broken: {exc}"
        print(f"{marker} {pet_id:<24} {summary}")
        print(f"    {directory}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    from . import registry

    try:
        result = registry.search(
            args.query or "", page_size=args.limit, sort=args.sort, version=args.version or ""
        )
    except registry.RegistryError as exc:
        print(f"claude-pet: {exc}", file=sys.stderr)
        return 1
    pets = result["pets"]
    if not pets:
        print("No results")
        return 0
    print(f"showing {len(pets)} of {result['total']}\n")
    for pet in pets:
        version = pet.get("spriteVersionNumber") or 1
        likes = pet.get("likeCount") or 0
        print(f"  {pet.get('id'):<26} v{version}  ♥{likes:<5} {pet.get('displayName')}")
        description = (pet.get("description") or "").strip()
        if description:
            print(f"    {description[:96]}")
    print("\nInstall with: claude-pet add <id>")
    return 0


def _install_root(args: argparse.Namespace) -> Path:
    if getattr(args, "codex_home", False):
        return config.codex_home() / "pets"
    return config.claude_home() / "pets"


def cmd_add(args: argparse.Namespace) -> int:
    from . import registry, sprites

    root = _install_root(args)
    failures = 0
    for pet_id in args.pet_ids:
        try:
            installed = registry.install(pet_id, root)
        except registry.RegistryError as exc:
            print(f"claude-pet: {exc}", file=sys.stderr)
            failures += 1
            continue
        try:
            pet = sprites.load_pet(installed["directory"])
        except sprites.SpriteError as exc:
            print(f"claude-pet: installed {pet_id}, but its spritesheet will not load: {exc}", file=sys.stderr)
            failures += 1
            continue
        print(
            f"installed  {pet.id}  ({pet.display_name}, v{pet.version}, "
            f"{sum(pet.frame_counts.values())} frames) -> {installed['directory']}"
        )
    if not failures and args.pet_ids:
        settings = config.load()
        if not settings.get("pet"):
            settings["pet"] = args.pet_ids[0]
            config.save(settings)
            print(f"active pet set to {args.pet_ids[0]}")
    return 1 if failures else 0


def cmd_add_collection(args: argparse.Namespace) -> int:
    from . import registry

    root = _install_root(args)
    try:
        installed = registry.install_collection(args.slug, root)
    except registry.RegistryError as exc:
        print(f"claude-pet: {exc}", file=sys.stderr)
        return 1
    for entry in installed:
        print(f"installed  {entry['id']} -> {entry['directory']}")
    print(f"{len(installed)} installed")
    return 0


def cmd_hatch(args: argparse.Namespace) -> int:
    from . import hatch, sprites

    pet_id = args.id or Path(args.image).stem.lower().replace("_", "-").replace(" ", "-")
    pet_id = "".join(char for char in pet_id if char.isalnum() or char == "-").strip("-")
    if not pet_id:
        print("claude-pet: could not make an id from that filename; pass --id", file=sys.stderr)
        return 1

    directory = hatch.hatch(args.image, pet_id, args.name, _install_root(args))
    pet = sprites.load_pet(directory)
    print(f"hatched  {pet.id}  ({pet.display_name}, v{pet.version}) -> {directory}")
    for name, count in pet.frame_counts.items():
        print(f"  {name:<16} {count} frames")
    print(f"\nTry it:  claude-pet demo --pet {pet.id}")
    print(f"Keep it: claude-pet use {pet.id} && claude-pet restart")
    return 0


def cmd_use(args: argparse.Namespace) -> int:
    available = config.discover()
    if args.pet_id not in available:
        print(f"claude-pet: {args.pet_id} is not installed", file=sys.stderr)
        return 1
    settings = config.load()
    settings["pet"] = args.pet_id
    config.save(settings)
    print(f"active pet: {args.pet_id}")
    if _overlay_pid():
        print("restart the overlay to apply: claude-pet restart")
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    from . import sprites

    available = config.discover()
    directory = available.get(args.pet_id) if args.pet_id else config.active_pet_dir()
    if directory is None:
        print("claude-pet: no such pet", file=sys.stderr)
        return 1
    pet = sprites.load_pet(directory)
    output = Path(args.output or f"{pet.id}-preview.png").expanduser()
    sprites.contact_sheet(pet).convert("RGB").save(output)
    print(f"{pet.id} v{pet.version}  cells {pet.cell[0]}x{pet.cell[1]}")
    for name, count in pet.frame_counts.items():
        print(f"  {name:<16} {count} frames")
    print(f"  look-directions  {len(pet.looks)} poses")
    print(f"\nwrote {output}")
    return 0


# ------------------------------------------------------------------ overlay


def _overlay_pid() -> int | None:
    from . import launch

    return launch.overlay_pid()


def cmd_run(args: argparse.Namespace) -> int:
    from . import launch

    if args.detach:
        if _overlay_pid() is not None:
            print("overlay is already running")
            return 0
        pid = launch.spawn_detached(reason="cli")
        if pid is None:
            print("claude-pet: could not start the overlay", file=sys.stderr)
            return 1
        print(f"overlay started detached (pid {pid}); it outlives this terminal")
        return 0

    from . import overlay

    return overlay.run(args.pet)


def cmd_demo(args: argparse.Namespace) -> int:
    from . import overlay

    return overlay.demo(pet_id=args.pet, seconds=args.seconds)


def cmd_snapshot(args: argparse.Namespace) -> int:
    from . import overlay

    return overlay.snapshot(
        args.output, pet_id=args.pet, state_name=args.state, detail=args.detail or ""
    )


def cmd_stop(_args: argparse.Namespace) -> int:
    pid = _overlay_pid()
    if pid is None:
        print("overlay is not running")
        return 0
    os.kill(pid, signal.SIGTERM)
    print(f"sent SIGTERM to pid {pid}")
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    cmd_stop(args)
    import time

    for _ in range(20):
        if _overlay_pid() is None:
            break
        time.sleep(0.1)

    # Detached by default, unlike `run`: restarting is how you apply a setting,
    # and the pet should not end up tied to whichever terminal you typed it in.
    args.detach = not getattr(args, "foreground", False)
    return cmd_run(args)


def cmd_status(_args: argparse.Namespace) -> int:
    snapshot = state.aggregate()
    pid = _overlay_pid()
    print(f"overlay   : {'running (pid %d)' % pid if pid else 'stopped'}")
    print(f"state     : {snapshot['state']}  ({snapshot['sessions']} sessions)")
    if snapshot.get("detail"):
        print(f"detail    : {snapshot['detail']}")
    settings = config.load()
    print(f"active pet: {settings.get('pet') or '(auto)'}")
    print(f"state file: {state.state_path()}")

    if settings.get("exit_when_no_sessions", True):
        grace = settings.get("exit_grace_seconds") or 0
        if snapshot["sessions"]:
            print(f"auto-exit : on, {grace}s after the last session ends")
        else:
            print(f"auto-exit : on, overlay quits within {grace}s")
    else:
        print("auto-exit : off")

    import time as _time

    now = _time.time()
    data = state.read()
    entries = data.get("sessions", {})
    if entries:
        print("sessions  :")
    for session_id, session in entries.items():
        if not isinstance(session, dict):
            continue
        alive = state.is_alive(session, now)
        where = (session.get("locator") or {}).get("claude_pid")
        note = "" if alive else "  DEAD (claude process gone, will be dropped)"
        print(
            f"  {session_id[:8]}  {str(session.get('state')):<8} "
            f"{session.get('detail') or '':<28} pid={where or '?'}{note}"
        )
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    if args.key not in config.DEFAULTS:
        keys = ", ".join(sorted(config.DEFAULTS))
        print(f"claude-pet: unknown key {args.key!r}. Available: {keys}", file=sys.stderr)
        return 1
    settings = config.load()
    raw = args.value
    if raw.lower() in {"true", "false"}:
        value: Any = raw.lower() == "true"
    elif raw.lower() in {"none", "null"}:
        value = None
    else:
        try:
            value = int(raw)
        except ValueError:
            value = raw
    settings[args.key] = value
    if args.key == "anchor":
        # A stored drag position would otherwise override the new anchor.
        settings["position"] = None
    config.save(settings)
    print(f"{args.key} = {value!r}")
    if _overlay_pid():
        print("restart to apply: claude-pet restart")
    return 0


# -------------------------------------------------------------------- hooks


def _settings_file(project: bool) -> Path:
    if project:
        return Path.cwd() / ".claude" / "settings.json"
    return config.claude_home() / "settings.json"


def _read_settings(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _hook_events_installed() -> int:
    """How many hook events already point at this checkout."""
    settings = _read_settings(config.claude_home() / "settings.json")
    return sum(
        1
        for entries in (settings.get("hooks") or {}).values()
        if isinstance(entries, list) and any(_entry_is_ours(entry) for entry in entries)
    )


def _entry_is_ours(entry: Any) -> bool:
    """True when a hooks[] entry was written by `install-hooks`."""
    if not isinstance(entry, dict):
        return False
    return any(
        HOOK_MARKER in str(hook.get("command", ""))
        for hook in entry.get("hooks", [])
        if isinstance(hook, dict)
    )


def cmd_install_hooks(args: argparse.Namespace) -> int:
    path = _settings_file(args.project)
    settings = _read_settings(path)
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        print(f"claude-pet: hooks in {path} is not an object", file=sys.stderr)
        return 1

    command = f"{launcher_path()} hook"
    added = 0
    for event in HOOK_EVENTS:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            print(f"claude-pet: hooks.{event} is not an array, skipping", file=sys.stderr)
            continue
        if any(_entry_is_ours(entry) for entry in entries):
            continue
        entries.append({"hooks": [{"type": "command", "command": command, "timeout": 5}]})
        added += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{path}: added hooks for {added} event(s); existing hooks untouched")
    if added:
        print("Start a new Claude Code session and the pet will follow along.")
    return 0


def cmd_uninstall_hooks(args: argparse.Namespace) -> int:
    path = _settings_file(args.project)
    settings = _read_settings(path)
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        print(f"{path}: nothing to remove")
        return 0

    removed = 0
    for event in list(hooks):
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue
        kept = []
        for entry in entries:
            if _entry_is_ours(entry):
                removed += 1
                continue
            kept.append(entry)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event)

    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{path}: removed {removed} hook(s)")
    return 0


# ------------------------------------------------------------------- doctor


def cmd_update(args: argparse.Namespace) -> int:
    from . import update

    return update.update(check_only=args.check)


def cmd_fix_terminal(args: argparse.Namespace) -> int:
    from . import terminal

    if args.undo:
        if terminal.uninstall():
            print("reverted; close and reopen your terminal")
        else:
            print("nothing to revert")
        return 0

    if not terminal.needed():
        session = os.environ.get("XDG_SESSION_TYPE", "?")
        if session != "wayland":
            print(f"not needed: this is a {session} session, the terminal is already reachable")
        elif not terminal.default_terminal():
            print("not needed: no x-terminal-emulator on PATH")
        else:
            print("not needed: install wmctrl first (`claude-pet setup`)")
        return 0

    print("wrapping your terminal so it runs under XWayland...")
    terminal.install()
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from . import sprites

    # Three outcomes, not two. A fresh clone has no packs and no hooks, and
    # click-to-jump is optional -- calling any of that FAIL made a working
    # checkout look broken.
    problems = 0
    next_steps: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        """A hard requirement: without it the pet cannot run."""
        nonlocal problems
        print(f"  {'OK  ' if ok else 'FAIL'}  {label}{'  — ' + detail if detail else ''}")
        if not ok:
            problems += 1

    def todo(label: str, done: bool, command: str, detail: str = "") -> None:
        """A setup step the user still has to take. Not a fault."""
        print(f"  {'OK  ' if done else 'TODO'}  {label}{'  — ' + detail if detail else ''}")
        if not done:
            next_steps.append(command)

    def optional(label: str, ok: bool, detail: str = "") -> None:
        """A nice-to-have. Absence is never a problem."""
        print(f"  {'OK  ' if ok else '--  '}  {label}{'  — ' + detail if detail else ''}")

    print("environment")
    session = os.environ.get("XDG_SESSION_TYPE", "?")
    display = os.environ.get("DISPLAY", "")
    check("DISPLAY (X11/XWayland)", bool(display), display or "unset: the overlay cannot start")
    print(f"  INFO  session type: {session}" + (" (via XWayland)" if session == "wayland" else ""))

    try:
        from PIL import features

        check("Pillow WebP decoding", bool(features.check("webp")))
    except ImportError:
        check("Pillow", False, "pip install Pillow")

    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # noqa: F401

        check("PyGObject / GTK3", True)
    except (ImportError, ValueError) as exc:
        check("PyGObject / GTK3", False, str(exc))

    from shutil import which

    optional(
        "notify-send",
        which("notify-send") is not None,
        "install libnotify-bin for desktop notifications (off by default anyway)",
    )

    print("\npets")
    available = config.discover()
    todo(
        "installed packs",
        bool(available),
        "claude-pet add clawd",
        f"{len(available)} found" if available else "none yet, pick one from `claude-pet search`",
    )
    for pet_id, directory in available.items():
        try:
            pet = sprites.load_pet(directory)
            print(f"  OK    {pet_id} v{pet.version}")
        except sprites.SpriteError as exc:
            print(f"  FAIL  {pet_id} — {exc}")
            problems += 1

    print("\nintegration")
    settings_path = config.claude_home() / "settings.json"
    settings = _read_settings(settings_path)
    installed_events = [
        event
        for event, entries in (settings.get("hooks") or {}).items()
        if isinstance(entries, list) and any(_entry_is_ours(entry) for entry in entries)
    ]
    todo(
        "hooks installed",
        len(installed_events) >= len(HOOK_EVENTS),
        "claude-pet install-hooks",
        f"{len(installed_events)}/{len(HOOK_EVENTS)} events",
    )
    on_path = launcher_on_path()
    todo(
        "claude-pet on PATH",
        on_path,
        "claude-pet doctor --fix",
        "" if on_path else f"not linked into {_local_bin()}",
    )
    todo(
        "shell completion",
        completion_installed(),
        "claude-pet doctor --fix",
        "" if completion_installed() else "tab completion not installed",
    )
    pid = _overlay_pid()
    print(f"  INFO  overlay: {'pid %d' % pid if pid else 'stopped'}")

    from . import jump

    methods = jump.capabilities()
    usable = [name for name, ok in methods.items() if ok]
    session_type = os.environ.get("XDG_SESSION_TYPE", "")
    if usable:
        hint = ", ".join(usable)
    elif session_type == "wayland":
        hint = "run Claude in tmux; a Wayland terminal cannot be raised by another app"
    else:
        hint = "install wmctrl (or xdotool) to raise the terminal, or run Claude in tmux"
    optional("click-to-jump", bool(usable), hint)

    from . import terminal

    if terminal.needed():
        todo(
            "terminal reachable for clicks",
            terminal.wrapper_installed(),
            "claude-pet fix-terminal",
            "" if terminal.wrapper_installed() else "a Wayland terminal cannot be raised as-is",
        )

    print()
    if problems:
        print(f"{problems} item(s) need attention")
        _print_dependency_hint()
        return 1

    running = _overlay_pid() is not None
    if getattr(args, "fix", False):
        return _finish_setup(install_deps=not getattr(args, "no_deps", False))

    if next_steps or not running:
        print("Nothing broken. Run `claude-pet doctor --fix` to finish setting up, or:")
        for step in next_steps:
            print(f"  {step}")
        if not running:
            print("  claude-pet run --detach")
    else:
        print("all good")
    return 0


#: Installed by `--fix` when no pack is present. Pixel Clawd, so the pet that
#: watches Claude Code looks the part.
DEFAULT_PACK = "clawd"

#: Package names per distro family, for the one thing `--fix` will not do
#: itself: installing system packages needs root.
DEPENDENCY_COMMANDS = (
    ("apt-get", "sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 python3-pil"),
    ("dnf", "sudo dnf install python3-gobject gtk3 python3-pillow"),
    ("pacman", "sudo pacman -S python-gobject gtk3 python-pillow"),
    ("zypper", "sudo zypper install python3-gobject gtk3 python3-Pillow"),
)


def _print_dependency_hint() -> None:
    from shutil import which

    for manager, command in DEPENDENCY_COMMANDS:
        if which(manager):
            print(f"\nMissing system packages are installed with:\n  {command}")
            return


def _local_bin() -> Path:
    return Path.home() / ".local" / "bin"


def launcher_on_path() -> bool:
    """Whether typing `claude-pet` anywhere already runs this checkout."""
    from shutil import which

    found = which("claude-pet")
    if not found:
        return False
    try:
        return Path(found).resolve() == launcher_path().resolve()
    except OSError:
        return False


def _link_launcher() -> None:
    """Symlink the launcher into ~/.local/bin so `claude-pet` just works."""
    link = _local_bin() / "claude-pet"
    target = launcher_path()

    if link.is_symlink() or link.exists():
        try:
            if link.resolve() == target.resolve():
                print(f"  {link} already points here")
            else:
                print(f"claude-pet: {link} exists and points elsewhere; left alone", file=sys.stderr)
        except OSError:
            print(f"claude-pet: {link} is a broken link; left alone", file=sys.stderr)
        return

    try:
        _local_bin().mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)
    except OSError as exc:
        print(f"claude-pet: could not link into {_local_bin()}: {exc}", file=sys.stderr)
        return
    print(f"  linked {link} -> {target}")

    if str(_local_bin()) not in os.environ.get("PATH", "").split(os.pathsep):
        _ensure_local_bin_on_path()


#: Markers so each rc block is added at most once and can be found again.
RC_MARKER_PATH = "# added by claude-pet (PATH)"
RC_MARKER_COMPLETION = "# added by claude-pet (completion)"

#: Shell -> rc file.
RC_FILES = {"zsh": ".zshrc", "bash": ".bashrc", "": ".profile"}


def rc_path() -> Path:
    shell = Path(os.environ.get("SHELL", "")).name
    return Path.home() / RC_FILES.get(shell, RC_FILES[""])


def rc_has(marker: str) -> bool:
    target = rc_path()
    try:
        return marker in target.read_text(encoding="utf-8")
    except OSError:
        return False


def _append_rc_block(marker: str, body: str, description: str) -> bool:
    """Append a marked block to the user's shell rc, at most once."""
    target = rc_path()
    if rc_has(marker):
        print(f"  {target} already has the {description} block")
        return True
    try:
        with target.open("a", encoding="utf-8") as stream:
            stream.write(f"\n{marker}\n{body}")
    except OSError as exc:
        print(f"claude-pet: could not update {target}: {exc}", file=sys.stderr)
        return False
    print(f"  added {description} to {target}")
    return True


def _ensure_local_bin_on_path() -> None:
    """Put ~/.local/bin on PATH via the shell rc.

    Ubuntu's ~/.profile adds ~/.local/bin only if it already existed at login,
    so creating it now is not enough -- without this, `claude-pet` keeps working
    only as `./claude-pet` until the user edits a dotfile themselves.
    """
    _append_rc_block(RC_MARKER_PATH, 'export PATH="$HOME/.local/bin:$PATH"\n', "PATH")


def completion_target() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "bash-completion" / "completions" / "claude-pet"


def completion_installed() -> bool:
    """Whether tab completion will actually be active in a new shell.

    The rc block is what makes that true everywhere: `bash-completion` may not
    be installed, and zsh does not read that directory at all.
    """
    return rc_has(RC_MARKER_COMPLETION)


def _completion_source() -> Path:
    return launcher_path().parent / "completions" / "claude-pet.bash"


def _install_completion() -> None:
    source = _completion_source()
    if not source.is_file():
        print(f"claude-pet: {source} is missing", file=sys.stderr)
        return
    # The standard location, for bash users who have bash-completion.
    target = completion_target()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or target.exists():
            target.unlink()
        target.symlink_to(source)
        print(f"  linked {target}")
    except OSError as exc:
        print(f"claude-pet: could not link completion: {exc}", file=sys.stderr)

    # And an rc block, which is what makes it work regardless of that.
    body = (
        f'if [ -f "{source}" ]; then\n'
        '  if [ -n "${ZSH_VERSION:-}" ]; then autoload -U +X bashcompinit && bashcompinit; fi\n'
        f'  . "{source}"\n'
        "fi\n"
    )
    if _append_rc_block(RC_MARKER_COMPLETION, body, "completion"):
        print("  run `exec $SHELL` (or open a new terminal) to get tab completion")


#: Command that installs the helper click-to-jump needs outside tmux.
JUMP_HELPER_COMMANDS = (
    ("apt-get", ["sudo", "apt-get", "install", "-y", "wmctrl"]),
    ("dnf", ["sudo", "dnf", "install", "-y", "wmctrl"]),
    ("pacman", ["sudo", "pacman", "-S", "--noconfirm", "wmctrl"]),
    ("zypper", ["sudo", "zypper", "--non-interactive", "install", "wmctrl"]),
)


def jump_helper_present() -> bool:
    from . import jump

    return jump.capabilities()["x11"]


def _install_jump_helper() -> None:
    """Install wmctrl, which is what lets a click raise a non-tmux terminal.

    Needs root, so it is the one step that can prompt. Skipped without a
    terminal, since a sudo password prompt would hang a script or a hook.
    """
    import subprocess
    from shutil import which

    from . import jump

    if jump.capabilities()["x11"]:
        return

    command = next((cmd for manager, cmd in JUMP_HELPER_COMMANDS if which(manager)), None)
    if command is None:
        return

    printable = " ".join(command)
    if not sys.stdin.isatty():
        print(f"  for click-to-jump outside tmux, run: {printable}")
        return

    print(f"  running: {printable}")
    print("  (sudo may ask for your password; Ctrl+C to skip)")
    try:
        subprocess.run(command, check=False)  # noqa: S603 - fixed argv, no shell
    except (OSError, KeyboardInterrupt):
        print("  skipped; run it yourself later if you want click-to-jump")
        return
    if which("wmctrl"):
        print("  wmctrl installed: clicking the pet can now raise the terminal")
    else:
        print(f"  wmctrl not installed; run `{printable}` yourself if you want it")


def _finish_setup(install_deps: bool = True) -> int:
    """Do everything a fresh checkout still needs, then start the pet."""
    from . import launch, registry, sprites

    # The bundled pack does not count here: it exists so a clone works offline,
    # but a first setup should still fetch the nicer default when it can.
    bundled = config.bundled_pets()
    has_pack = any(bundled not in directory.parents for directory in config.discover().values())
    has_hooks = _hook_events_installed() >= len(HOOK_EVENTS)
    running = _overlay_pid() is not None
    linked = launcher_on_path()
    completed = completion_installed()

    from . import terminal

    terminal_ready = not terminal.needed() or terminal.wrapper_installed()
    if (
        has_pack and has_hooks and running and linked and completed
        and jump_helper_present() and terminal_ready
    ):
        print("Nothing to do: pack installed, hooks in place, on PATH, pet running.")
        return 0

    if not linked:
        print("putting claude-pet on your PATH...")
        _link_launcher()

    if not completed:
        print("installing shell completion...")
        _install_completion()

    if install_deps and not jump_helper_present():
        print("enabling click-to-jump outside tmux...")
        _install_jump_helper()

    if install_deps and not terminal_ready:
        print("making your terminal reachable so clicking the pet can raise it...")
        terminal.install()

    if not has_pack:
        print(f"installing pack {DEFAULT_PACK}...")
        try:
            installed = registry.install(DEFAULT_PACK, config.claude_home() / "pets")
            sprites.load_pet(installed["directory"])
            config.update(pet=DEFAULT_PACK)
            print(f"  installed {installed['id']} -> {installed['directory']}")
        except (registry.RegistryError, sprites.SpriteError) as exc:
            # Not fatal: the bundled pack means there is always something to show.
            print(f"  could not fetch {DEFAULT_PACK}: {exc}")
            print("  using the bundled pack instead; `claude-pet search` when you are online")

    if not has_hooks:
        print("installing hooks...")
        cmd_install_hooks(argparse.Namespace(project=False))

    if not running:
        print("starting the pet...")
        pid = launch.spawn_detached(reason="doctor --fix")
        if pid is None:
            print("claude-pet: could not start the overlay; see `claude-pet run`", file=sys.stderr)
            return 1
        print(f"  overlay running detached (pid {pid})")

    print("\nDone. The pet now starts with Claude and quits when the last session ends.")
    return 0


# ---------------------------------------------------------------- entrypoint


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-pet",
        description="A desktop pet for Claude Code, rendered from Codex pet sprite packs",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="list installed pet packs").set_defaults(func=cmd_list)

    search = subparsers.add_parser("search", help="browse the codex-pets.net gallery")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--sort", default="popular", choices=["new", "popular", "likes", "random"])
    search.add_argument("--version", choices=["1", "2"])
    search.set_defaults(func=cmd_search)

    add = subparsers.add_parser("add", help="install packs from codex-pets.net")
    add.add_argument("pet_ids", nargs="+", metavar="PET_ID")
    add.add_argument("--codex-home", action="store_true", help="install into ~/.codex/pets instead")
    add.set_defaults(func=cmd_add)

    collection = subparsers.add_parser("add-collection", help="install every pack in a collection")
    collection.add_argument("slug")
    collection.add_argument("--codex-home", action="store_true")
    collection.set_defaults(func=cmd_add_collection)

    hatch_parser = subparsers.add_parser(
        "hatch", help="animate one image you supply into a pack (draws no art)"
    )
    hatch_parser.add_argument("image", help="png, jpg or webp; a flat background is dropped")
    hatch_parser.add_argument("--id", help="pet id (default: the filename)")
    hatch_parser.add_argument("--name", help="display name")
    hatch_parser.add_argument("--codex-home", action="store_true")
    hatch_parser.set_defaults(func=cmd_hatch)

    use = subparsers.add_parser("use", help="choose the active pack")
    use.add_argument("pet_id")
    use.set_defaults(func=cmd_use)

    preview = subparsers.add_parser("preview", help="dump every animation row to a PNG")
    preview.add_argument("pet_id", nargs="?")
    preview.add_argument("-o", "--output")
    preview.set_defaults(func=cmd_preview)

    run = subparsers.add_parser("run", help="start the overlay")
    run.add_argument("--pet", help="pack id to use for this run only")
    run.add_argument(
        "--detach", action="store_true", help="run in the background, surviving this terminal"
    )
    run.set_defaults(func=cmd_run)

    restart = subparsers.add_parser("restart", help="restart the overlay (detached)")
    restart.add_argument("--pet")
    restart.add_argument(
        "--foreground", action="store_true", help="stay attached to this terminal"
    )
    restart.set_defaults(func=cmd_restart)

    demo = subparsers.add_parser("demo", help="cycle the window through every animation row")
    demo.add_argument("--pet")
    demo.add_argument("--seconds", type=float, default=2.0, help="seconds per row")
    demo.set_defaults(func=cmd_demo)

    snapshot = subparsers.add_parser("snapshot", help="capture the overlay window to a PNG (debug)")
    snapshot.add_argument("output")
    snapshot.add_argument("--pet")
    snapshot.add_argument("--state", choices=list(state.PRIORITY))
    snapshot.add_argument("--detail", default="")
    snapshot.set_defaults(func=cmd_snapshot)

    subparsers.add_parser("stop", help="stop the overlay").set_defaults(func=cmd_stop)
    subparsers.add_parser("status", help="show the current state and live sessions").set_defaults(func=cmd_status)
    doctor = subparsers.add_parser("doctor", help="check the environment and integration")
    doctor.add_argument(
        "--fix",
        action="store_true",
        help="install a pack and the hooks, link onto PATH, and start the pet",
    )
    doctor.add_argument(
        "--no-deps", action="store_true", help="skip installing wmctrl (needs sudo)"
    )
    doctor.set_defaults(func=cmd_doctor)

    setup = subparsers.add_parser("setup", help="one-command setup (same as doctor --fix)")
    setup.add_argument("--no-deps", action="store_true", help="skip installing wmctrl")
    setup.set_defaults(func=cmd_doctor, fix=True)

    setter = subparsers.add_parser("set", help="change a setting")
    setter.add_argument("key")
    setter.add_argument("value")
    setter.set_defaults(func=cmd_set)

    install = subparsers.add_parser("install-hooks", help="add hooks to Claude Code settings.json")
    install.add_argument("--project", action="store_true", help="use ./.claude/settings.json instead of the global one")
    install.set_defaults(func=cmd_install_hooks)

    uninstall = subparsers.add_parser("uninstall-hooks", help="remove the hooks again")
    uninstall.add_argument("--project", action="store_true")
    uninstall.set_defaults(func=cmd_uninstall_hooks)

    update_parser = subparsers.add_parser("update", help="update to the latest version")
    update_parser.add_argument(
        "--check", action="store_true", help="only report whether an update is available"
    )
    update_parser.set_defaults(func=cmd_update)

    fix_terminal = subparsers.add_parser(
        "fix-terminal", help="run your terminal under XWayland so clicks can raise it"
    )
    fix_terminal.add_argument("--undo", action="store_true", help="remove the wrappers again")
    fix_terminal.set_defaults(func=cmd_fix_terminal)

    hook = subparsers.add_parser("hook", help="(internal) handle a hook event")
    hook.add_argument("event", nargs="?")
    hook.set_defaults(func=cmd_hook)

    complete = subparsers.add_parser("_complete", help=argparse.SUPPRESS)
    complete.add_argument("cword", type=int)
    complete.add_argument("current")
    complete.add_argument("previous")
    complete.add_argument("sub")
    complete.set_defaults(func=cmd_complete)

    return parser


#: Values worth offering for `set <key>`, beyond booleans and free numbers.
SETTING_CHOICES = {
    "language": ("auto", "en", "ko"),
    "bubble": ("active", "alerts", "never"),
    "anchor": ("bottom-right", "bottom-left", "top-right", "top-left"),
    "position": ("none",),
}


def _subcommands() -> list[str]:
    parser = build_parser()
    for action in parser._actions:  # noqa: SLF001 - argparse exposes no public API
        if isinstance(action, argparse._SubParsersAction):
            return [name for name in action.choices if not name.startswith("_")]
    return []


def _options_for(subcommand: str) -> list[str]:
    parser = build_parser()
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction):
            target = action.choices.get(subcommand)
            if target is None:
                return []
            return [
                option
                for sub_action in target._actions  # noqa: SLF001
                for option in sub_action.option_strings
            ]
    return []


def cmd_complete(args: argparse.Namespace) -> int:
    """Emit completion candidates for the shell. Filtering happens here.

    Kept in Python rather than duplicated in shell script so the candidate
    lists come from the real parser and cannot drift out of date.
    """
    cword, current, previous, subcommand = args.cword, args.current, args.previous, args.sub
    candidates: list[str] = []

    if cword <= 1:
        candidates = _subcommands()
    elif previous == "--pet" or (subcommand in {"use", "preview"} and cword == 2):
        candidates = list(config.discover())
    elif subcommand == "set" and cword == 2:
        candidates = sorted(config.DEFAULTS)
    elif subcommand == "set" and cword == 3:
        key = previous
        if key in SETTING_CHOICES:
            candidates = list(SETTING_CHOICES[key])
        elif isinstance(config.DEFAULTS.get(key), bool):
            candidates = ["true", "false"]
    elif subcommand == "search" and previous == "--sort":
        candidates = ["popular", "new", "likes", "random"]
    elif subcommand == "search" and previous == "--version":
        candidates = ["1", "2"]

    if current.startswith("-"):
        candidates = _options_for(subcommand)

    for candidate in sorted(set(candidates)):
        if candidate.startswith(current):
            print(candidate)
    return 0


def cmd_hook(args: argparse.Namespace) -> int:
    from . import hook

    return hook.main([args.event] if args.event else [])


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except PetError as exc:
        print(f"claude-pet: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
