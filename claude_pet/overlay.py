"""The floating desktop pet window.

GTK3 on X11. Under a GNOME Wayland session this runs through XWayland, because
`_NET_WM_STATE_ABOVE` is the only always-on-top mechanism mutter honours for a
regular client -- `gtk-layer-shell` is wlroots-only.
"""

from __future__ import annotations

import math
import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import gi

for _namespace, _version in (
    ("Gtk", "3.0"),
    ("Gdk", "3.0"),
    ("GdkPixbuf", "2.0"),
    ("Pango", "1.0"),
    ("PangoCairo", "1.0"),
):
    gi.require_version(_namespace, _version)

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from . import config, jump, sprites, state  # noqa: E402

BUBBLE_WIDTH = 260
BUBBLE_GAP = 8
POLL_INTERVAL_MS = 250
EDGE_MARGIN = 12

#: Look frames ordered left-to-right. A v2 sheet stores 16 yaw poses across
#: rows 9-10; row 10 holds the left half of the sweep and row 9 the right half.
LOOK_ORDER: tuple[int, ...] = (8, 9, 10, 11, 12, 13, 14, 15, 0, 1, 2, 3, 4, 5, 6, 7)

#: Animation row played once when a state is entered, before settling into the
#: state's own row. Finishing a turn earns a hop.
INTRO = {"review": "jumping"}

#: How long each state stays interesting lives in `state.DWELL_SECONDS`, since
#: it has to be applied per session while aggregating, not to the result.

#: Frames per second per state -- working should read as busier than idle.
STATE_FPS = {
    "idle": 6,
    "waiting": 8,
    "review": 8,
    "running": 12,
    "failed": 8,
    "waving": 10,
    "jumping": 12,
    # A stroll, not a sprint: at 12fps with a 6px step the pet tore along the
    # bottom of the screen, which reads as agitated rather than idle.
    "running-right": 8,
    "running-left": 8,
}

#: Seconds between wanders, and how long each lasts.
WALK_PAUSE_RANGE = (12.0, 30.0)
WALK_DURATION_RANGE = (2.0, 5.0)

#: Bubble state labels. `language: auto` picks by locale and falls back to en.
LABELS: dict[str, dict[str, str]] = {
    "en": {
        "idle": "idle",
        "running": "working",
        "waiting": "needs you",
        "review": "done",
        "failed": "failed",
        "waving": "session started",
        "menu.walk": "Wander around",
        "menu.notify": "Desktop notifications",
        "menu.autostart": "Start with Claude",
        "menu.exit_idle": "Quit when no sessions",
        "menu.quit": "Quit",
        "jump.hint": "click to jump",
    },
    "ko": {
        "idle": "대기 중",
        "running": "작업 중",
        "waiting": "입력 대기",
        "review": "응답 완료",
        "failed": "실패",
        "waving": "세션 시작",
        "menu.walk": "돌아다니기",
        "menu.notify": "데스크톱 알림",
        "menu.autostart": "클로드와 함께 시작",
        "menu.exit_idle": "세션 없으면 종료",
        "menu.quit": "종료",
        "jump.hint": "클릭하면 이동",
    },
}


#: Things the pet can say per state, one picked when the state is entered.
#: `{tool}` is filled with the tool Claude is using, when there is one.
PHRASES: dict[str, dict[str, tuple[str, ...]]] = {
    "en": {
        "idle": ("nothing running", "all quiet", "waiting for you"),
        "running": ("working", "on it", "{tool}…", "busy with {tool}"),
        "waiting": ("needs you",),
        "review": ("done", "all yours", "have a look"),
        "failed": ("that failed", "something broke"),
        "waving": ("hello", "session started"),
    },
    "ko": {
        "idle": ("할 일 없음", "조용함", "기다리는 중"),
        "running": ("작업 중", "하는 중", "{tool} 중", "{tool} 돌리는 중"),
        "waiting": ("입력 대기",),
        "review": ("응답 완료", "다 됐어요", "확인해 주세요"),
        "failed": ("실패했어요", "뭔가 깨졌어요"),
        "waving": ("안녕", "세션 시작"),
    },
}

#: Below this, saying how long something has been going is just noise.
ELAPSED_FLOOR_SECONDS = 45


def resolve_phrases(language: str) -> dict[str, tuple[str, ...]]:
    if language in PHRASES:
        return PHRASES[language]
    if language == "auto":
        for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
            value = os.environ.get(variable, "")
            if value:
                return PHRASES.get(value.split("_")[0].lower(), PHRASES["en"])
    return PHRASES["en"]


def resolve_labels(language: str) -> dict[str, str]:
    if language in LABELS:
        return LABELS[language]
    if language == "auto":
        for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
            value = os.environ.get(variable, "")
            if value:
                return LABELS.get(value.split("_")[0].lower(), LABELS["en"])
    return LABELS["en"]

NOTIFY_ON = {"waiting", "review", "failed"}

#: States whose bubble advertises the jump. Clicking tries it whenever a
#: location is known, but only these are worth cluttering the bubble for.
JUMPABLE = {"waiting", "review", "failed"}

#: Pointer travel, in pixels, that turns a click into a drag.
DRAG_THRESHOLD = 5

#: Focus changes within this long of opening the menu are setup noise, not a
#: click on something else.
MENU_FOCUS_GUARD_SECONDS = 0.3


def _to_pixbuf(image) -> GdkPixbuf.Pixbuf:
    data = GLib.Bytes.new(image.tobytes())
    return GdkPixbuf.Pixbuf.new_from_bytes(
        data, GdkPixbuf.Colorspace.RGB, True, 8, image.width, image.height, image.width * 4
    )


class PetView:
    """Scaled, pixbuf-ready frames for one pet pack."""

    def __init__(self, pet: sprites.Pet, height: int) -> None:
        self.pet = pet
        self.animations: dict[str, list[GdkPixbuf.Pixbuf]] = {}
        for name, frames in pet.animations.items():
            scaled = sprites.scale_frames(frames, height)
            self.animations[name] = [_to_pixbuf(frame) for frame in scaled]

        self.looks: list[GdkPixbuf.Pixbuf] = []
        if len(pet.looks) >= max(LOOK_ORDER) + 1:
            ordered = [pet.looks[index] for index in LOOK_ORDER]
            self.looks = [_to_pixbuf(frame) for frame in sprites.scale_frames(ordered, height)]

        reference = next((frames for frames in self.animations.values() if frames), None)
        if reference is None:
            raise sprites.SpriteError(f"{pet.id}: spritesheet has no visible frames")
        self.width = reference[0].get_width()
        self.height = reference[0].get_height()

    def frames(self, name: str) -> list[GdkPixbuf.Pixbuf]:
        for candidate in (name, "idle", "running", "waiting"):
            frames = self.animations.get(candidate)
            if frames:
                return frames
        return next(frames for frames in self.animations.values() if frames)


class Overlay(Gtk.Window):
    def __init__(self, view: PetView, settings: dict[str, Any], poll: bool = True) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.view = view
        self.settings = settings
        language = str(settings.get("language") or "auto")
        self.labels = resolve_labels(language)
        self.phrases = resolve_phrases(language)
        self.phrase = ""
        self.project = ""
        self.since = time.time()

        self.state = "idle"
        self.detail = ""
        self.sessions = 0
        self.visual_state = "idle"
        self.frame_index = 0
        self.visual_until: float | None = None
        self.visual_return: str | None = None
        self.bubble_pinned = False
        self.empty_since: float | None = None
        self.locator: dict[str, Any] | None = None
        # A short-lived bubble override, for telling the user how a click went.
        self.flash_text = ""
        self.flash_until = 0.0
        self.press_origin: tuple[int, int] | None = None
        self.menu_opened_at = 0.0

        self.dragging = False
        # The overlay owns its position. Reading it back from GTK on every walk
        # step accumulates frame-vs-client offset error and the pet drifts off
        # the floor and past its bounds.
        self.pos_x = 0
        self.pos_y = 0
        self.walking = 0          # -1 left, 0 still, +1 right
        self.walk_until = 0.0
        self.next_walk_at = time.monotonic() + random.uniform(*WALK_PAUSE_RANGE)
        self.look_index: int | None = None

        self.window_width = max(view.width, BUBBLE_WIDTH)
        self.window_height = view.height + BUBBLE_GAP + 78
        self.sprite_left = (self.window_width - view.width) // 2
        self.sprite_top = self.window_height - view.height

        self._configure_window()
        self._place_initial()

        self.connect("draw", self._on_draw)
        self.connect("button-press-event", self._on_button_press)
        self.connect("button-release-event", self._on_button_release)
        self.connect("motion-notify-event", self._on_motion)
        self.connect("configure-event", self._on_configure)
        self.connect("destroy", lambda *_: self.quit())
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.ENTER_NOTIFY_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
        )

        self.show_all()
        self._place_initial()  # a move() before realize is not always honoured
        self._apply_input_shape()
        if poll:
            GLib.timeout_add(POLL_INTERVAL_MS, self._poll_state)
        self._schedule_frame()

    # ---------------------------------------------------------------- window

    def _configure_window(self) -> None:
        self.set_title("claude-pet")
        self.set_wmclass("claude-pet", "claude-pet")
        self.set_default_size(self.window_width, self.window_height)
        self.set_size_request(self.window_width, self.window_height)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_accept_focus(False)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_app_paintable(True)
        self.stick()

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)

    def _workarea(self) -> Gdk.Rectangle:
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        return monitor.get_workarea()

    def _place_initial(self) -> None:
        area = self._workarea()
        stored = self.settings.get("position")
        if isinstance(stored, (list, tuple)) and len(stored) == 2:
            x, y = int(stored[0]), int(stored[1])
        else:
            anchor = str(self.settings.get("anchor") or "bottom-right")
            y = area.y + area.height - self.window_height - EDGE_MARGIN
            if anchor.endswith("left"):
                x = area.x + EDGE_MARGIN
            else:
                x = area.x + area.width - self.window_width - EDGE_MARGIN
            if anchor.startswith("top"):
                y = area.y + EDGE_MARGIN

        self.pos_x, self.pos_y = x, y
        self.move(x, y)

    def _apply_input_shape(self) -> None:
        """Only the sprite (and a visible bubble) should swallow clicks."""
        window = self.get_window()
        if window is None:
            return
        import cairo

        # Only the sprite takes clicks. The bubble is on screen most of the time
        # now, and a talkative pet must not become a 260px dead zone over
        # whatever is underneath it.
        region = cairo.Region(
            cairo.RectangleInt(self.sprite_left, self.sprite_top, self.view.width, self.view.height)
        )
        window.input_shape_combine_region(region, 0, 0)

    def _on_configure(self, _widget, event) -> bool:
        # Only a deliberate drag should move the pet's home. Walk steps and the
        # initial anchored placement must not become sticky state.
        if self.dragging and not self.walking:
            self.pos_x, self.pos_y = int(event.x), int(event.y)
            self.settings["position"] = [self.pos_x, self.pos_y]
        return False

    # ----------------------------------------------------------------- state

    def _poll_state(self) -> bool:
        # Re-aggregated every time, not only when the file changes: dwells
        # expire on the clock, so the same file yields a different state later.
        snapshot = state.aggregate()
        self._adopt(snapshot)
        self._maybe_exit(snapshot)
        return True

    def _maybe_exit(self, snapshot: dict[str, Any]) -> None:
        """Shut down once every Claude session is gone.

        Waits out a grace period first, so closing one terminal and opening
        another does not kill the pet in between.
        """
        if not self.settings.get("exit_when_no_sessions", True):
            self.empty_since = None
            return
        if snapshot.get("sessions"):
            self.empty_since = None
            return

        now = time.monotonic()
        if self.empty_since is None:
            self.empty_since = now
            return

        grace = float(self.settings.get("exit_grace_seconds") or 0)
        if now - self.empty_since >= grace:
            print("claude-pet: no Claude sessions left, exiting", flush=True)
            self.quit()

    def _adopt(self, snapshot: dict[str, Any]) -> None:
        new_state = snapshot.get("state") or "idle"
        self.detail = snapshot.get("detail") or ""
        self.sessions = int(snapshot.get("sessions") or 0)
        self.locator = snapshot.get("locator")
        self.project = Path(str(snapshot.get("cwd") or "")).name
        self.since = float(snapshot.get("since") or time.time())

        if new_state == self.state:
            return
        previous = self.state
        self.state = new_state
        self.frame_index = 0
        self.walking = 0

        options = self.phrases.get(new_state) or (self.labels.get(new_state, new_state),)
        self.phrase = random.choice(options)

        intro = INTRO.get(new_state)
        if intro and self.view.animations.get(intro):
            self.visual_state = intro
            self.visual_return = new_state
            self.visual_until = time.monotonic() + self._row_duration(intro)
        else:
            self.visual_state = new_state
            self.visual_return = None
            self.visual_until = None

        if new_state in NOTIFY_ON and self.settings.get("notifications", False):
            if previous != new_state:
                self._notify(new_state)
        self._apply_input_shape()

    def _row_duration(self, name: str) -> float:
        frames = self.view.frames(name)
        return len(frames) / max(1, STATE_FPS.get(name, 10))

    def _notify(self, name: str) -> None:
        summary = f"Claude Code · {self.labels.get(name, name)}"
        body = self.detail or ""
        urgency = "critical" if name == "waiting" else "normal"
        try:
            subprocess.Popen(  # noqa: S603,S607 - fixed argv
                [
                    "notify-send",
                    "--app-name=claude-pet",
                    f"--urgency={urgency}",
                    "--hint=string:x-canonical-private-synchronous:claude-pet",
                    summary,
                    body,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, FileNotFoundError):
            pass

    # ------------------------------------------------------------- animation

    def _schedule_frame(self) -> None:
        fps = STATE_FPS.get(self.visual_state, 10)
        GLib.timeout_add(max(20, int(1000 / fps)), self._tick)

    def _tick(self) -> bool:
        now = time.monotonic()

        if self.visual_until is not None and now >= self.visual_until:
            self.visual_state = self.visual_return or "idle"
            self.visual_until = None
            self.visual_return = None
            self.frame_index = 0

        if self.state == "idle" and self.visual_until is None:
            self._update_walk(now)
        elif self.walking:
            self.walking = 0

        frames = self.view.frames(self.visual_state)
        self.frame_index = (self.frame_index + 1) % max(1, len(frames))
        self._update_look()

        self.queue_draw()
        self._schedule_frame()
        return False

    def _update_walk(self, now: float) -> None:
        if not self.settings.get("walk", True):
            return
        # Stop the moment it is grabbed, not merely hovered: move() during a
        # drag fights the window manager. Hovering leaves it walking, so it can
        # be picked up mid-stride.
        if self.dragging or self.press_origin is not None:
            return

        if self.walking and now >= self.walk_until:
            self.walking = 0
            self.visual_state = "idle"
            self.frame_index = 0
            self.next_walk_at = now + random.uniform(*WALK_PAUSE_RANGE)
            return

        if not self.walking and now >= self.next_walk_at:
            self.walking = random.choice((-1, 1))
            self.walk_until = now + random.uniform(*WALK_DURATION_RANGE)
            self.visual_state = "running-right" if self.walking > 0 else "running-left"
            self.frame_index = 0
            return

        if not self.walking:
            return

        # Bounds keep the *sprite* inside the workarea; the window is wider
        # than the sprite because of the bubble, and that padding is invisible.
        area = self._workarea()
        left_bound = area.x + EDGE_MARGIN - self.sprite_left
        right_bound = area.x + area.width - EDGE_MARGIN - self.sprite_left - self.view.width
        step = max(1, int(self.settings.get("walk_speed") or 3))
        new_x = self.pos_x + step * self.walking
        if new_x <= left_bound or new_x >= right_bound:
            self.walking *= -1
            self.visual_state = "running-right" if self.walking > 0 else "running-left"
        self.pos_x = min(max(new_x, left_bound), right_bound)
        self.move(self.pos_x, self.pos_y)

    def _update_look(self) -> None:
        """Face the pointer while idle, using the v2 look sweep."""
        self.look_index = None
        if not (self.view.looks and self.settings.get("look_at_mouse", True)):
            return
        if self.visual_state != "idle" or self.walking:
            return

        display = Gdk.Display.get_default()
        seat = display.get_default_seat() if display else None
        pointer = seat.get_pointer() if seat else None
        if pointer is None:
            return
        _screen, pointer_x, pointer_y = pointer.get_position()

        center_x = self.pos_x + self.sprite_left + self.view.width / 2
        center_y = self.pos_y + self.sprite_top + self.view.height / 2
        dx, dy = pointer_x - center_x, pointer_y - center_y
        if math.hypot(dx, dy) < self.view.width * 0.6:
            return  # pointer is on top of the pet; keep the neutral pose

        span = self.view.width * 6
        fraction = min(1.0, max(-1.0, dx / span))
        count = len(self.view.looks)
        self.look_index = min(count - 1, max(0, int(round((fraction + 1) / 2 * (count - 1)))))

    # --------------------------------------------------------------- drawing

    def _bubble_visible(self) -> bool:
        # Tied to the state rather than a timer: the state's own dwell already
        # decides how long it lasts, so the bubble cannot outlive its news.
        # Anything but idle is worth saying out loud -- while Claude works, the
        # tool name in the bubble is the most useful thing on screen.
        if self.bubble_pinned or time.monotonic() < self.flash_until:
            return True
        mode = str(self.settings.get("bubble") or "active")
        if mode == "never":
            return False
        if mode == "alerts":
            return self.state in NOTIFY_ON
        return self.state != "idle"

    def _bubble_text(self) -> str:
        if time.monotonic() < self.flash_until:
            return self.flash_text

        fallback = self.labels.get(self.state, self.state)
        phrase = self.phrase or fallback

        if "{tool}" in phrase:
            # The phrase is built around a tool name, so it needs one.
            text = phrase.format(tool=self.detail) if self.detail else fallback
        elif self.detail:
            text = f"{phrase} · {self.detail}"
        else:
            text = phrase

        # `waiting` carries Claude's own prose, which is long and already the
        # most useful thing on screen; leave it room.
        if self.state != "waiting":
            if self.project:
                text = f"{text} · {self.project}"
            elapsed = time.time() - self.since
            if self.state == "running" and elapsed >= ELAPSED_FLOOR_SECONDS:
                text = f"{text} · {int(elapsed // 60)}m"

        if self.sessions > 1:
            text = f"{text}  ({self.sessions} sessions)"
        if self.state in JUMPABLE and self.locator:
            text = f"{text}  ↩ {self.labels['jump.hint']}"
        return text

    def _on_draw(self, _widget, cr) -> bool:
        cr.set_operator(1)  # cairo.OPERATOR_SOURCE
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(2)  # cairo.OPERATOR_OVER

        if self._bubble_visible():
            self._draw_bubble(cr)

        if self.look_index is not None and self.view.looks:
            pixbuf = self.view.looks[self.look_index]
        else:
            frames = self.view.frames(self.visual_state)
            pixbuf = frames[self.frame_index % len(frames)]

        Gdk.cairo_set_source_pixbuf(cr, pixbuf, self.sprite_left, self.sprite_top)
        cr.paint()
        return False

    def _draw_bubble(self, cr) -> None:
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(Pango.FontDescription("Sans 10"))
        layout.set_width((BUBBLE_WIDTH - 24) * Pango.SCALE)
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        layout.set_ellipsize(Pango.EllipsizeMode.END)
        layout.set_height(-3)
        layout.set_text(self._bubble_text(), -1)
        _ink, logical = layout.get_pixel_extents()

        box_width = min(BUBBLE_WIDTH, logical.width + 24)
        box_height = logical.height + 16
        box_x = (self.window_width - box_width) / 2
        box_y = max(0, self.sprite_top - BUBBLE_GAP - box_height)

        radius = 10
        cr.new_sub_path()
        cr.arc(box_x + box_width - radius, box_y + radius, radius, -math.pi / 2, 0)
        cr.arc(box_x + box_width - radius, box_y + box_height - radius, radius, 0, math.pi / 2)
        cr.arc(box_x + radius, box_y + box_height - radius, radius, math.pi / 2, math.pi)
        cr.arc(box_x + radius, box_y + radius, radius, math.pi, 3 * math.pi / 2)
        cr.close_path()

        accent = {
            "waiting": (0.98, 0.72, 0.18),
            "failed": (0.93, 0.35, 0.35),
            "review": (0.42, 0.78, 0.52),
        }.get(self.state, (0.66, 0.68, 0.76))
        cr.set_source_rgba(0.09, 0.09, 0.12, 0.92)
        cr.fill_preserve()
        cr.set_source_rgba(*accent, 0.9)
        cr.set_line_width(1.5)
        cr.stroke()

        cr.set_source_rgba(0.94, 0.95, 0.97, 1.0)
        cr.move_to(box_x + 12, box_y + 8)
        PangoCairo.show_layout(cr, layout)

    # ----------------------------------------------------------------- input

    def _on_button_press(self, _widget, event) -> bool:
        if event.button == 3:
            self._show_menu(event)
            return True
        if event.button == 1 and event.type == Gdk.EventType.BUTTON_PRESS:
            # Held, not committed: the drag only starts once the pointer has
            # actually travelled, so a plain click stays available for jumping.
            self._halt_walk()
            self.press_origin = (int(event.x_root), int(event.y_root))
            return True
        return False

    def _halt_walk(self, pause: float = 0.0) -> None:
        """Stop mid-stride and stay put for at least `pause` seconds.

        Needed before any interaction: while walking, every animation tick calls
        move(), which fights the window manager's drag and yanks the pet back.
        Worse, the pet walks out from under the pointer, so the drag threshold
        is never crossed and it cannot be picked up at all.
        """
        if self.walking:
            self.walking = 0
            self.visual_state = "idle"
            self.frame_index = 0
        self.next_walk_at = max(
            self.next_walk_at, time.monotonic() + max(pause, WALK_PAUSE_RANGE[0])
        )

    def _on_motion(self, _widget, event) -> bool:
        if self.press_origin is None:
            return False
        start_x, start_y = self.press_origin
        if math.hypot(event.x_root - start_x, event.y_root - start_y) < DRAG_THRESHOLD:
            return False
        self.press_origin = None
        self.dragging = True
        self.begin_move_drag(1, start_x, start_y, event.time)
        return True

    def _on_button_release(self, _widget, event) -> bool:
        if event.button != 1:
            return False
        if self.press_origin is not None:
            self.press_origin = None
            self._on_click()
        elif self.dragging:
            self.dragging = False
            self._halt_walk()  # settle where it was dropped before wandering on
            config.update(position=self.settings.get("position"))
        return False

    def _on_click(self) -> None:
        """Take me to the session, or toggle the bubble if there is none.

        Any state, not just the alerting ones: "show me that terminal" is what
        people reach for the pet to do, whether or not Claude is asking.
        """
        if not self.locator:
            self.bubble_pinned = not self.bubble_pinned
            self._apply_input_shape()
            self.queue_draw()
            return

        result = jump.to_session(self.locator)
        self._flash(result.message)

    def _flash(self, message: str, seconds: float = 4.0) -> None:
        self.flash_text = message
        self.flash_until = time.monotonic() + seconds
        self._apply_input_shape()
        self.queue_draw()

    def _show_menu(self, event) -> None:
        menu = Gtk.Menu()

        header = Gtk.MenuItem(label=f"{self.view.pet.display_name} · v{self.view.pet.version}")
        header.set_sensitive(False)
        menu.append(header)
        menu.append(Gtk.SeparatorMenuItem())

        available = config.discover()
        for pet_id in available:
            item = Gtk.CheckMenuItem(label=pet_id)
            item.set_active(pet_id == self.view.pet.id)
            item.connect("activate", self._on_pick_pet, pet_id)
            menu.append(item)

        menu.append(Gtk.SeparatorMenuItem())
        walk = Gtk.CheckMenuItem(label=self.labels["menu.walk"])
        walk.set_active(bool(self.settings.get("walk", True)))
        walk.connect("toggled", self._on_toggle, "walk")
        menu.append(walk)

        notify = Gtk.CheckMenuItem(label=self.labels["menu.notify"])
        notify.set_active(bool(self.settings.get("notifications", False)))
        notify.connect("toggled", self._on_toggle, "notifications")
        menu.append(notify)

        autostart = Gtk.CheckMenuItem(label=self.labels["menu.autostart"])
        autostart.set_active(bool(self.settings.get("autostart", True)))
        autostart.connect("toggled", self._on_toggle, "autostart")
        menu.append(autostart)

        exit_idle = Gtk.CheckMenuItem(label=self.labels["menu.exit_idle"])
        exit_idle.set_active(bool(self.settings.get("exit_when_no_sessions", True)))
        exit_idle.connect("toggled", self._on_toggle, "exit_when_no_sessions")
        menu.append(exit_idle)

        menu.append(Gtk.SeparatorMenuItem())
        quit_item = Gtk.MenuItem(label=self.labels["menu.quit"])
        quit_item.connect("activate", lambda *_: self.quit())
        menu.append(quit_item)

        menu.show_all()
        menu.popup_at_pointer(event)

        # Closing on an outside click, not on the pointer merely wandering off.
        # The menu takes keyboard focus -- measured -- so clicking any other
        # window, Wayland-native included, shows up here as focus-out. Watching
        # the grab instead would miss it: an XWayland grab never sees a click
        # that lands on a Wayland surface.
        self.menu_opened_at = time.monotonic()
        toplevel = menu.get_toplevel()
        if isinstance(toplevel, Gtk.Window):
            toplevel.connect("notify::has-toplevel-focus", self._on_menu_focus_change, menu)
        menu.connect("grab-broken-event", self._on_menu_grab_broken, menu)

    def _on_menu_focus_change(self, toplevel, _param, menu) -> None:
        if toplevel.has_toplevel_focus():
            return
        # Focus can flicker while the menu is still being mapped; that is not a
        # click on anything.
        if time.monotonic() - self.menu_opened_at < MENU_FOCUS_GUARD_SECONDS:
            return
        menu.popdown()

    def _on_menu_grab_broken(self, _menu, _event, menu) -> bool:
        menu.popdown()
        return False

    def _on_pick_pet(self, item, pet_id: str) -> None:
        if not item.get_active():
            return
        self.settings["pet"] = pet_id
        config.update(pet=pet_id)
        self.quit(restart=True)

    def _on_toggle(self, item, key: str) -> None:
        self.settings[key] = item.get_active()
        config.update(**{key: self.settings[key]})

    # ---------------------------------------------------------------- teardown

    def quit(self, restart: bool = False) -> None:
        try:
            state.pid_path().unlink()
        except OSError:
            pass
        if restart:
            try:
                os.execv(sys.executable, [sys.executable, "-m", "claude_pet", "run"])
            except OSError:
                pass
        Gtk.main_quit()


def demo(pet_id: str | None = None, seconds: float = 2.0) -> int:
    """Cycle the live window through every animation row the pack provides.

    The desktop equivalent of the state buttons on a pack's gallery page: it is
    how you check that a pack drew all nine rows before trusting it.
    """
    if not os.environ.get("DISPLAY"):
        print("claude-pet: no DISPLAY", file=sys.stderr)
        return 2

    settings = dict(config.load())
    settings.update({"walk": False, "notifications": False, "look_at_mouse": False})
    if pet_id:
        settings["pet"] = pet_id

    directory = config.active_pet_dir(settings)
    if directory is None:
        print("claude-pet: no pet packs found", file=sys.stderr)
        return 2

    pet = sprites.load_pet(directory)
    view = PetView(pet, int(settings.get("height") or 132))
    window = Overlay(view, settings, poll=False)
    window.bubble_pinned = True

    rows = [name for name in sprites.ROW_STATES if view.animations.get(name)]
    print(
        f"claude-pet: {pet.id} v{pet.version} cycling {len(rows)} rows, Ctrl+C to stop",
        flush=True,
    )
    counter = {"index": 0}

    def advance() -> bool:
        name = rows[counter["index"] % len(rows)]
        counter["index"] += 1
        window.state = name
        window.visual_state = name
        window.detail = f"{len(view.animations[name])} frames"
        window.frame_index = 0
        window.visual_until = None
        window.visual_return = None
        window._apply_input_shape()
        print(f"  {name:<15} {len(view.animations[name])} frames", flush=True)
        return True

    advance()
    GLib.timeout_add(max(200, int(seconds * 1000)), advance)
    for number in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, number, lambda: (Gtk.main_quit(), True)[1])
    Gtk.main()
    return 0


def snapshot(
    output: str,
    pet_id: str | None = None,
    state_name: str | None = None,
    detail: str = "",
    delay_ms: int = 700,
) -> int:
    """Render the overlay offscreen-ish and dump its own window to a PNG.

    Used to verify drawing without a compositor screenshot API, which GNOME
    restricts to authorised callers.
    """
    if not os.environ.get("DISPLAY"):
        print("claude-pet: no DISPLAY", file=sys.stderr)
        return 2

    settings = dict(config.load())
    settings["walk"] = False
    settings["notifications"] = False
    if pet_id:
        settings["pet"] = pet_id

    directory = config.active_pet_dir(settings)
    if directory is None:
        print("claude-pet: no pet packs found", file=sys.stderr)
        return 2

    pet = sprites.load_pet(directory)
    view = PetView(pet, int(settings.get("height") or 132))
    # With no state forced, poll like the real overlay does, so a snapshot
    # shows whatever the live sessions are actually doing.
    window = Overlay(view, settings, poll=state_name is None)

    if state_name:
        window.state = window.visual_state = state_name
        window.detail = detail
        window.sessions = 1
        window.bubble_pinned = state_name in NOTIFY_ON
        window._apply_input_shape()

    destination = Path(output).expanduser()

    def grab() -> bool:
        surface = window.get_window()
        pixbuf = Gdk.pixbuf_get_from_window(
            surface, 0, 0, window.window_width, window.window_height
        )
        if pixbuf is None:
            print("claude-pet: window grab returned nothing", file=sys.stderr)
        else:
            pixbuf.savev(str(destination), "png", [], [])
            print(f"claude-pet: {pet.id} [{window.visual_state}] -> {destination}")
        Gtk.main_quit()
        return False

    GLib.timeout_add(delay_ms, grab)
    Gtk.main()
    return 0


def _claim_pidfile() -> bool:
    path = state.pid_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = int(path.read_text(encoding="utf-8").strip())
        if Path(f"/proc/{existing}").exists() and existing != os.getpid():
            return False
    except (OSError, ValueError):
        pass
    path.write_text(str(os.getpid()), encoding="utf-8")
    return True


def run(pet_id: str | None = None) -> int:
    """Launch the overlay. Returns a process exit code.

    `GDK_BACKEND=x11` is exported by the `claude-pet` launcher, because GTK
    resolves its backend before this module gets a say.
    """
    if not os.environ.get("DISPLAY"):
        print(
            "claude-pet: no DISPLAY. The overlay needs X11 or XWayland for always-on-top.",
            file=sys.stderr,
        )
        return 2

    settings = config.load()
    if pet_id:
        settings["pet"] = pet_id

    directory = config.active_pet_dir(settings)
    if directory is None:
        searched = ", ".join(str(path) for path in config.pet_search_paths())
        print(f"claude-pet: no pet packs found in {searched}", file=sys.stderr)
        print("claude-pet: install one with `claude-pet add <pet-id>`", file=sys.stderr)
        return 2

    pet = sprites.load_pet(directory)
    view = PetView(pet, int(settings.get("height") or 132))

    if not _claim_pidfile():
        print("claude-pet: overlay is already running", file=sys.stderr)
        return 0

    overlay = Overlay(view, settings)
    print(
        f"claude-pet: {pet.display_name} (v{pet.version}) on "
        f"{type(Gdk.Display.get_default()).__name__} at ({overlay.pos_x},{overlay.pos_y}) "
        f"sprite {view.width}x{view.height}",
        flush=True,
    )
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal_number, lambda: (overlay.quit(), True)[1])

    overlay._adopt(state.aggregate())
    Gtk.main()
    return 0
