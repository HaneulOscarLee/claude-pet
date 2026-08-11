"""Drives the real overlay through the paths a fresh install takes.

Written because a deleted constant shipped in three releases. `EDGE_MARGIN`
went missing in a refactor, and nothing caught it: it compiles, it imports, and
the only code that touches it is placing a pet that has no remembered position
and walking one that wanders. The machine it was developed on had both a saved
position and wandering switched off, so every check passed while a fresh
install crashed on startup.

So this constructs the window for real and puts it through those paths. It
needs a display; CI supplies one with xvfb, and it is skipped without one.

    xvfb-run -a python3 tests/test_overlay_smoke.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def checks() -> list[tuple[str, bool]]:
    import gi

    gi.require_version("Gtk", "3.0")

    from claude_pet import config, overlay, sprites

    results = []
    settings = dict(config.DEFAULTS)
    settings["position"] = None  # a fresh install, which is the case that broke
    settings["walk"] = True      # and the other one

    directory = config.active_pet_dir(settings)
    pet = sprites.load_pet(str(directory))
    window = overlay.Overlay(overlay.PetView(pet, 132), settings, poll=False)
    results.append(("a pet with no saved position places itself", True))
    results.append(("...somewhere on a screen", window._on_screen(window.sprite_x, window.sprite_y)))

    # Anchoring is what `reset_position` and a first run both go through.
    for anchor in ("bottom-right", "bottom-left", "top-right", "top-left"):
        window.settings["anchor"] = anchor
        x, y = window._anchored_sprite()
        results.append((f"anchors {anchor}", window._on_screen(x, y)))

    # Wandering, which is on by default and never ran on the machine this was
    # written on.
    window.walking = 1
    window.walk_until = 1e18
    window.visual_state = "running-right"
    before = window.sprite_x
    height_before = window.sprite_y
    for step in range(30):
        window._update_walk(step * 0.1)
    results.append(("it wanders without falling over", window.sprite_x != before))
    # Wandering is sideways only. Up and down is for being called, which is
    # a thing you asked for rather than something it does on its own.
    results.append(("...along the ground, never up or down", window.sprite_y == height_before))
    results.append(("...and stays on screen", window._on_screen(window.sprite_x, window.sprite_y)))

    # Being thrown, and being called: both move the sprite every frame.
    from claude_pet import motion

    window.throw = motion.Throw(2500, -1200)
    window.thrown_at = 0.0
    for step in range(40):
        if window.throw is None:
            break
        window._advance_throw(step * 0.05)
    results.append(("a throw runs to a stop", window.throw is None))
    results.append(("...on screen", window._on_screen(window.sprite_x, window.sprite_y)))

    window.walk_target = (window.sprite_x - 400, window.sprite_y - 120)
    for _ in range(200):
        if window.walk_target is None:
            break
        window._advance_errand()
    results.append(("being called arrives", window.walk_target is None))
    results.append(("...on screen", window._on_screen(window.sprite_x, window.sprite_y)))

    # Petting, the other thing that reaches into the window.
    window.petted_count = 0
    window._enjoy_petting()
    results.append(("petting works end to end", window.petted_count == 1))
    return results


def main() -> int:
    if not os.environ.get("DISPLAY"):
        print("no DISPLAY; skipping (CI runs this under xvfb)")
        return 0

    # Never touch the real configuration: this writes positions and counters.
    workspace = tempfile.mkdtemp(prefix="claude-pet-smoke-")
    os.environ["XDG_CONFIG_HOME"] = workspace
    os.environ["XDG_STATE_HOME"] = workspace

    results = checks()
    failures = sum(1 for _, ok in results if not ok)
    print("overlay:")
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"\n{len(results) - failures}/{len(results)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
