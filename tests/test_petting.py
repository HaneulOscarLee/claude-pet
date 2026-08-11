"""Checks for recognising a pet being stroked.

The whole feature is one judgement call: nothing separates "stroking the pet"
from "moving the pointer across it" except that a stroke turns around. A rule
about that is worth only as much as the cases it has been tried against, so
both halves are pinned here -- what must set it off, and what must not.

Plain stdlib, no test runner needed:

    python3 tests/test_petting.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_pet import petting  # noqa: E402

FAR = petting.STROKE_PIXELS + 4


def rub(stroke: petting.Stroke, sweeps: int, start: float = 100.0, step: float = 0.1) -> int:
    """Sweep back and forth over the pet; returns how often it reacted."""
    reacted = 0
    x, now = 500, start
    for index in range(sweeps):
        x += FAR * (1 if index % 2 == 0 else -1)
        now += step
        reacted += bool(stroke.feed(x, now))
    return reacted


def triggers() -> list[tuple[str, bool]]:
    results = []

    stroke = petting.Stroke()
    results.append(("a proper rub is noticed", rub(stroke, 6) >= 1))

    # It must react once per rub, not once per wobble -- otherwise a long
    # stroking session is a pet having a seizure.
    stroke = petting.Stroke()
    reacted = rub(stroke, 30, step=0.05)
    results.append((f"a long rub reacts sparingly ({reacted}x in 1.5s)", reacted == 1))

    # ...but keeps responding if you carry on past the cooldown.
    stroke = petting.Stroke()
    first = rub(stroke, 8, start=0.0)
    second = rub(stroke, 8, start=petting.COOLDOWN_SECONDS + 1.0)
    results.append(("stroking again later is noticed again", first >= 1 and second >= 1))
    return results


def directions() -> list[tuple[str, bool]]:
    """The gesture counts however it is oriented.

    Reported as not working at all, and this was why: only horizontal movement
    was measured, so waving up and down at the pet did nothing whatever --
    which nobody would guess was deliberate, and plenty of people wave that
    way.
    """
    import math

    def wave(axis: str, seconds: float = 1.2, hz: float = 1.5, amplitude: int = 130) -> bool:
        stroke = petting.Stroke()
        moment = 0.0
        while moment < seconds:
            offset = amplitude * math.sin(2 * math.pi * hz * moment)
            if axis == "x":
                x, y = 600 + offset, 500
            elif axis == "y":
                x, y = 600, 500 + offset
            else:
                x, y = 600 + offset * 0.7, 500 + offset * 0.7
            if stroke.feed(int(x), moment, int(y)):
                return True
            moment += 0.05
        return False

    results = [(f"waving along {axis} is noticed", wave(axis)) for axis in ("x", "y", "diagonal")]

    # y is optional, so a caller with only one axis to give still works.
    stroke = petting.Stroke()
    fired = any(stroke.feed(600 + FAR * (1 if i % 2 == 0 else -1), i * 0.1) for i in range(8))
    results.append(("x alone still works", fired))
    return results


def summons() -> list[tuple[str, bool]]:
    """A summons asks for less turning than a rub, and has to.

    A rub happens on a sprite a hundred pixels wide and gives half a turn per
    sweep, so it can ask for plenty. A summons is often a circle drawn at arm's
    length, and a big circle at an ordinary hand speed takes seconds per
    revolution -- asking for more than one meant a normal-sized circle never
    finished in time and looked like the gesture did nothing.
    """
    import math

    def circle(radius: int, speed: float, seconds: float = 3.0) -> bool:
        stroke = petting.Stroke(petting.CALL_TURN_RADIANS)
        moment = 0.0
        turns_per_second = speed / (2 * math.pi * radius)
        while moment < seconds:
            angle = 2 * math.pi * turns_per_second * moment
            if stroke.feed(int(700 + radius * math.cos(angle)), moment,
                           int(500 + radius * math.sin(angle))):
                return True
            moment += 0.05
        return False

    results = [("a summons asks less than a rub",
                petting.CALL_TURN_RADIANS < petting.TURN_RADIANS)]
    # Small, medium and large, each at a speed someone would actually draw it.
    for radius, speed in ((25, 400), (100, 600), (250, 1200), (400, 2000)):
        results.append((f"a circle of radius {radius} is a summons", circle(radius, speed)))
    # A rub is still a rub: the stricter threshold is the default.
    results.append(("the default is still the stricter one",
                    petting.Stroke().turn_radians == petting.TURN_RADIANS))
    return results


def rejects() -> list[tuple[str, bool]]:
    """The half that matters more: things that must never read as affection."""
    results = []

    # Crossing the sprite on the way somewhere else. No reversal, so no pet.
    stroke = petting.Stroke()
    reacted = 0
    for step in range(12):
        reacted += bool(stroke.feed(500 + step * FAR, step * 0.05))
    results.append(("a pointer passing straight across is ignored", reacted == 0))

    # A hand resting on the mouse: plenty of jitter, none of it deliberate.
    stroke = petting.Stroke()
    reacted = 0
    for step in range(60):
        reacted += bool(stroke.feed(500 + (step % 2) * 2, step * 0.05))
    results.append(("jitter on a resting hand is ignored", reacted == 0))

    # Two turns far apart are two hesitations, not one gesture.
    stroke = petting.Stroke()
    reacted = 0
    for index in range(6):
        reacted += bool(stroke.feed(500 + FAR * (1 if index % 2 == 0 else -1),
                                    index * (petting.WINDOW_SECONDS + 0.5)))
    results.append(("reversals far apart do not add up", reacted == 0))

    # Just under the amount of turning required. One rub back and forth is
    # a single half-turn; the threshold is above a full circle.
    stroke = petting.Stroke()
    reacted = rub(stroke, 3)
    results.append(("just under the threshold does not fire", reacted == 0))

    # A circle is what a wave and a rub have in common -- turning -- so the
    # threshold is stated in those terms and checked here.
    import math

    stroke = petting.Stroke()
    turned = 0
    for step in range(40):
        angle = 2 * math.pi * step / 20  # two full circles
        turned += bool(stroke.feed(int(600 + 60 * math.cos(angle)), step * 0.05,
                                   int(500 + 60 * math.sin(angle))))
    results.append(("a circle counts as a gesture", turned >= 1))

    # A drag is not a stroke, and the overlay resets on one.
    stroke = petting.Stroke()
    rub(stroke, 3)
    stroke.reset()
    results.append(("reset forgets a gesture in progress", stroke.turned == 0.0))
    return results


def main() -> int:
    failures = 0
    total = 0
    for label, results in (("triggers", triggers()), ("directions", directions()),
                            ("summons", summons()), ("rejects", rejects())):
        print(f"{label}:")
        for name, ok in results:
            total += 1
            failures += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
