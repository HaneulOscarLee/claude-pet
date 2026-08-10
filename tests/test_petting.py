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

    # One reversal short of the threshold.
    stroke = petting.Stroke()
    reacted = 0
    x, now = 500, 0.0
    for index in range(petting.REVERSALS):  # N moves == N-1 reversals
        x += FAR * (1 if index % 2 == 0 else -1)
        now += 0.1
        reacted += bool(stroke.feed(x, now))
    results.append(("just under the threshold does not fire", reacted == 0))

    # A drag is not a stroke, and the overlay resets on one.
    stroke = petting.Stroke()
    rub(stroke, 2)
    stroke.reset()
    results.append(("reset forgets a gesture in progress", stroke.reversals == 0))
    return results


def main() -> int:
    failures = 0
    total = 0
    for label, results in (("triggers", triggers()), ("rejects", rejects())):
        print(f"{label}:")
        for name, ok in results:
            total += 1
            failures += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
