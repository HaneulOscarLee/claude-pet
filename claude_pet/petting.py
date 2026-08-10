"""Recognising a pet being stroked.

Kept apart from the overlay, and stdlib-only, so the gesture can be tested
without a display -- which matters here more than most places, because the
whole difficulty is a judgement call about intent. Nothing distinguishes
"stroking the pet" from "moving the pointer across it" except that a stroke
turns around, and a rule about that is only as good as the cases it is tried
against.

Direction is what counts, not distance. Movements too small to be deliberate
are discarded, so a hand resting on a mouse never accumulates into affection,
and reversals expire, so two turns a minute apart are not one gesture.
"""

from __future__ import annotations

#: How far the pointer must travel before a movement counts as a stroke at all,
#: rather than the hand shaking on a stationary mouse.
STROKE_PIXELS = 8

#: Direction changes that add up to being stroked. Two would fire while merely
#: hesitating over the sprite; three needs deliberate back-and-forth.
REVERSALS = 3

#: Reversals only belong to the same gesture within this long of each other.
WINDOW_SECONDS = 1.6

#: A pet reacting to every stroke of a long rub is a pet having a seizure.
COOLDOWN_SECONDS = 2.5


class Stroke:
    """Tracks a hovering pointer and says when it has been stroking.

    `feed` is given the pointer's x and the time, and returns True on the
    moment the gesture completes -- once per rub, not once per wobble.
    """

    def __init__(self) -> None:
        self.x: int | None = None
        self.at = 0.0
        self.direction = 0
        self.reversals = 0
        self.ready_at = 0.0

    def reset(self) -> None:
        """Forget the gesture in progress, when the pointer leaves or drags."""
        self.x = None
        self.direction = 0
        self.reversals = 0

    def feed(self, x: int, now: float) -> bool:
        if self.x is None:
            self.x, self.at = x, now
            return False

        travelled = x - self.x
        if abs(travelled) < STROKE_PIXELS:
            # Too small to mean anything. Deliberately does not update the
            # anchor: a slow drag across the sprite would otherwise never
            # accumulate enough travel to register at all.
            return False

        direction = 1 if travelled > 0 else -1
        if now - self.at > WINDOW_SECONDS:
            self.reversals = 0  # whatever came before was a different gesture
        if self.direction and direction != self.direction:
            self.reversals += 1
        self.direction = direction
        self.x, self.at = x, now

        if self.reversals < REVERSALS or now < self.ready_at:
            return False
        self.reversals = 0
        self.ready_at = now + COOLDOWN_SECONDS
        return True
