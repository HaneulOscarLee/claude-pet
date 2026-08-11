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

import math

#: How far the pointer must travel before a movement counts as a stroke at all,
#: rather than the hand shaking on a stationary mouse.
STROKE_PIXELS = 8

#: How far the pointer's direction must turn, in total, to count as a
#: gesture. Radians.
#:
#: Counting reversals -- turns of more than a right angle -- worked for
#: rubbing back and forth and could never work for a circle, which turns
#: gradually and reverses never. Accumulated turning covers both: half a
#: turn per reversal of a rub, a full turn per loop of a circle. Set a
#: little above one circle, so a small deliberate loop is enough and the
#: ordinary curve of a pointer on its way somewhere is not.
TURN_RADIANS = 2.2 * math.pi

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
        self.y = 0
        self.at = 0.0
        self.direction_x = 0.0
        self.direction_y = 0.0
        self.turned = 0.0
        self.ready_at = 0.0

    def reset(self) -> None:
        """Forget the gesture in progress, when the pointer leaves or drags."""
        self.x = None
        self.direction_x = 0.0
        self.direction_y = 0.0
        self.turned = 0.0

    def feed(self, x: int, now: float, y: int = 0) -> bool:
        """Feed a pointer position. `y` is optional; without it, x alone decides.

        Direction is a vector, not a sign, so a gesture counts however it is
        oriented. Watching only x meant waving up and down at the pet did
        nothing at all -- which is not a thing anyone would guess was
        deliberate, and several people wave that way.
        """
        if self.x is None:
            self.x, self.y, self.at = x, y, now
            return False

        travelled_x = x - self.x
        travelled_y = y - self.y
        if math.hypot(travelled_x, travelled_y) < STROKE_PIXELS:
            # Too small to mean anything. Deliberately does not update the
            # anchor: a slow drag across the sprite would otherwise never
            # accumulate enough travel to register at all.
            return False

        if now - self.at > WINDOW_SECONDS:
            self.turned = 0.0  # whatever came before was a different gesture
        if self.direction_x or self.direction_y:
            # The angle between one movement and the next, added up. A rub
            # turns half a circle every time it goes back; a circle turns a
            # whole one each loop; a pointer crossing the sprite on its way
            # somewhere turns almost nothing.
            self.turned += abs(
                math.atan2(
                    self.direction_x * travelled_y - self.direction_y * travelled_x,
                    self.direction_x * travelled_x + self.direction_y * travelled_y,
                )
            )
        self.direction_x, self.direction_y = float(travelled_x), float(travelled_y)
        self.x, self.y, self.at = x, y, now

        if self.turned < TURN_RADIANS or now < self.ready_at:
            return False
        self.turned = 0.0
        self.ready_at = now + COOLDOWN_SECONDS
        return True
