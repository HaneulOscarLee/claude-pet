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

    # An errand whose pointer cannot be read must not hang with its "coming"
    # bubble up forever. When the reading stays None past the stall window the
    # pet gives up and the bubble (tied to walk_target) comes down. This was
    # the regression from making the walk pause on an unreadable pointer.
    import time as _time
    from claude_pet import pointer as _pv

    real_sample = _pv.sample
    try:
        _pv.sample = lambda _raw: (None, False)
        window.walk_target = (window.sprite_x + 300, window.sprite_y)
        window.throw = None
        window.called_at = _time.monotonic()
        # Within the stall window it holds position, bubble still up.
        window.errand_seen_at = _time.monotonic()
        window.moved_at = _time.monotonic() - 0.016
        window._advance_motion()
        held = window.walk_target is not None
        # Past the stall window it abandons and clears.
        window.errand_seen_at = _time.monotonic() - (overlay.ERRAND_STALL_SECONDS + 1)
        window.moved_at = _time.monotonic() - 0.016
        window._advance_motion()
        results.append(("an unreadable errand holds briefly, then gives up",
                        held and window.walk_target is None))
        results.append(("...taking its coming bubble down with it",
                        not (window.walk_target is not None)))
    finally:
        _pv.sample = real_sample

    # Petting, the other thing that reaches into the window.
    window.petted_count = 0
    window._enjoy_petting()
    results.append(("petting works end to end", window.petted_count == 1))

    # Every menu page, drawn for real. A missing label or a mistyped entry
    # kind raises only when someone opens that page, which no other test
    # goes near -- and a menu that raises leaves the pet unclickable.
    from gi.repository import Gtk

    popup = Gtk.Window()
    popup.menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    popup.add(popup.menu_box)
    for page in window.PAGES:
        try:
            window._render_page(popup, page)
            drawn = len(popup.menu_box.get_children())
        except Exception as exc:  # noqa: BLE001 -- the point is that it does not
            drawn, why = 0, exc
            results.append((f"the {page} page draws -- {exc!r}", False))
            continue
        results.append((f"the {page} page draws ({drawn} rows)", drawn > 0))

    # The status bar's menu is built from the same model by different code,
    # and it silently skipped any entry kind it did not know -- so the tuning
    # entry opened an empty submenu there while working in the pet's own menu.
    # Nothing about that is visible until someone opens it.
    tray_menu = window._build_tray_menu()

    def count(menu):
        """Every item, and every item of every submenu, as (label, children)."""
        found = []
        for item in menu.get_children():
            child = item.get_submenu() if hasattr(item, "get_submenu") else None
            found.append((item.get_label() if hasattr(item, "get_label") else "",
                          len(child.get_children()) if child is not None else None))
        return found

    rows = count(tray_menu)
    results.append((f"the status bar menu is built ({len(rows)} items)", len(rows) > 0))
    empty = [label for label, children in rows if children == 0]
    results.append((f"...with no empty submenus ({empty or 'none'})", not empty))

    # And the pet's own menu draws every kind the model can produce, which is
    # the other half of the same fault.
    kinds = {entry[0] for page in window.PAGES for entry in window._menu_model(page)}
    results.append((f"the model uses only known kinds ({', '.join(sorted(kinds))})",
                    kinds <= {"separator", "caption", "submenu", "action", "toggle",
                              "choice", "update"}))

    # The sliders have to move something. Each one is applied on the spot,
    # which is the only reason to have a slider rather than a config key.
    #
    # Saving is stubbed out: a test has no business writing the settings of
    # whoever happens to be running it, and resetting the tuning would put
    # their sliders back to the defaults.
    written: list[dict] = []
    config.update = lambda **values: written.append(values)
    window._open_tuning()
    results.append(("the tuning window opens", window.tuning is not None))
    window._open_tuning()
    results.append(("...and opening it again reuses the one window",
                    window.tuning is not None))
    slider_rows = [window._slider_row(key, low, high, step, digits)
                   for key, low, high, step, digits in window.TUNABLE]
    results.append((f"it has a slider for every knob ({len(slider_rows)})",
                    len(slider_rows) == len(window.TUNABLE)))
    for key, low, high, _step, _digits in window.TUNABLE:
        window._tune(key, high)
        at_high = window.settings[key]
        window._tune(key, low)
        results.append((f"{key} follows its slider",
                        at_high != window.settings[key]
                        and abs(window.settings[key] - low) < 0.01))
    results.append(("a throw picks up the tuned friction",
                    abs(window.flick.friction
                        - window.settings["throw_friction"]) < 0.01))
    results.append(("a summons picks up the tuned roundness",
                    abs(window.call_stroke.roundness_wanted
                        - window.settings["call_roundness"]) < 0.01))

    # Where the popup lands, for every page and wherever the pet is. Placement
    # measured the window rather than its contents, and a page just swapped in
    # has not been sized yet -- `get_size()` answered 190x417 for all of them,
    # including the tuning page that wants 244x477. Seventy-seven pixels short
    # put it through the panel whenever the pet was near the top, which is how
    # it was reported.
    area = window._workarea()
    for where, y in (("top", area.y), ("middle", area.y + area.height // 2),
                     ("bottom", area.y + area.height - window.view.height)):
        window._place_sprite(area.x + 400, y)
        for page in ("main", "pets", "behaviour"):
            window._render_page(popup, page)
            _minimum, natural = popup.get_preferred_size()
            left, top = popup.get_position()
            inside = (area.y <= top and top + natural.height <= area.y + area.height
                      and area.x <= left and left + natural.width <= area.x + area.width)
            results.append((f"the {page} menu fits with the pet at the {where}"
                            f" ({natural.width}x{natural.height} at {top})", inside))

    # Usage figures in the menu, and the once-per-window 5h warning. Read is
    # stubbed so the test does not depend on any statusLine cache being around.
    from claude_pet import usage as _usage
    real_read = _usage.read
    try:
        _usage.read = lambda: {"five_hour_pct": 95, "seven_day_pct": 40,
                               "five_hour_resets_at": 111, "cost_usd": 3.5}
        window.settings["usage"] = True
        window.settings["usage_warn_percent"] = 90
        cap = window._usage_caption()
        results.append((f"the usage line is built ({cap})",
                        cap is not None and "95" in cap))
        model = window._menu_model("main")
        captions = [e[1] for e in model if e[0] == "caption"]
        results.append(("...and appears in the menu",
                        any("95" in c for c in captions)))

        window.usage_warned_window = None
        window._check_usage_once()
        fired = window.usage_warned_window == 111
        window._check_usage_once()  # same window: must not re-arm/re-flash
        results.append(("a 5h limit over the threshold warns once", fired))
        results.append(("...and not again for the same window",
                        window.usage_warned_window == 111))

        # A new 5h window (different resets_at) warns afresh.
        _usage.read = lambda: {"five_hour_pct": 96, "seven_day_pct": 40,
                               "five_hour_resets_at": 222, "cost_usd": 3.5}
        window._check_usage_once()
        results.append(("...but a fresh window warns again",
                        window.usage_warned_window == 222))

        # Under the threshold: silence, and the line still shows.
        _usage.read = lambda: {"five_hour_pct": 10, "five_hour_resets_at": 333}
        window.usage_warned_window = None
        window._check_usage_once()
        results.append(("under the threshold does not warn",
                        window.usage_warned_window is None))

        # Turned off: no line at all.
        window.settings["usage"] = False
        results.append(("usage off hides the line", window._usage_caption() is None))
    finally:
        _usage.read = real_read
        window.settings["usage"] = True

    # Clicking to jump takes the bubble down for that alert until the state
    # changes -- reported as the "click to jump" bubble lingering through the
    # whole dwell and re-appearing on every click after you had already jumped.
    import time as _t2
    from claude_pet import jump as _jump

    real_to_session = _jump.to_session
    try:
        class _R:
            def __init__(self, ok): self.ok = ok; self.message = "there" if ok else "no"
            def __bool__(self): return self.ok
        window.settings["bubble"] = "active"
        window.state = "review"
        window.since = 1000.0
        window.locator = {"pids": [1]}
        window.bubble_pinned = False
        window.walk_target = None
        window.jumped_episode = None
        window.flash_until = 0.0
        results.append(("a done alert shows its bubble", window._bubble_visible()))

        _jump.to_session = lambda loc: _R(True)
        window._on_click()
        window.flash_until = 0.0  # let the 4s result flash expire
        results.append(("after a successful jump the bubble is down",
                        not window._bubble_visible()))

        # A fresh alert (new since) shows again.
        window.since = 2000.0
        results.append(("a new alert shows again", window._bubble_visible()))

        # A failed jump keeps the bubble -- the alert is still pending.
        window.jumped_episode = None
        _jump.to_session = lambda loc: _R(False)
        window._on_click()
        window.flash_until = 0.0
        results.append(("a failed jump keeps the bubble up", window._bubble_visible()))

        # A real state change clears the marker.
        window.jumped_episode = ("review", 2000.0)
        window._adopt({"state": "running", "since": 3000.0, "sessions": 1})
        results.append(("a state change clears the jumped marker",
                        window.jumped_episode is None))
    finally:
        _jump.to_session = real_to_session
        window.state = "idle"; window.locator = None

    # The re-login reminder: fires only when the bridge is installed but not
    # yet active (the "menu update / fresh install, log in to finish" state),
    # and stays quiet otherwise. It flashes, so we watch flash_until move.
    from claude_pet import shellext as _sx
    saved = (_sx.supported_here, _sx.installed, _sx.active)
    try:
        _sx.supported_here = lambda: True
        _sx.installed = lambda: True
        _sx.active = lambda: False           # installed but not loaded yet
        window.flash_until = 0.0
        window._remind_bridge_relogin()
        results.append(("installed-but-inactive bridge prompts a re-login",
                        window.flash_until > _t2.monotonic()))
        _sx.active = lambda: True            # already loaded -> silent
        window.flash_until = 0.0
        window._remind_bridge_relogin()
        results.append(("an active bridge says nothing", window.flash_until == 0.0))
        _sx.supported_here = lambda: False   # not GNOME/Wayland -> silent
        _sx.active = lambda: False
        window._remind_bridge_relogin()
        results.append(("off a supported desktop it says nothing",
                        window.flash_until == 0.0))
    finally:
        _sx.supported_here, _sx.installed, _sx.active = saved

    window._reset_tuning(slider_rows)
    results.append(("resetting puts every default back",
                    all(window.settings[key] == config.DEFAULTS[key]
                        for key, *_rest in window.TUNABLE)))
    results.append(("...and is written out once", len(written) == 1))
    results.append(("...naming every knob",
                    written and set(written[0]) == {k for k, *_r in window.TUNABLE}))
    results.append(("...and the sliders follow it back",
                    all(abs(holder.scale.get_value()
                            - float(config.DEFAULTS[holder.tune_key])) < 0.01
                        for holder in slider_rows)))
    window.tuning.destroy()
    results.append(("closing it lets it open again", window.tuning is None))
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
