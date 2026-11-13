"""SM-2 spaced-repetition scheduler (SuperMemo-2).

Pure functions only: no database, no clock. That makes it trivial to test.
Quality scale (what the student/assistant reports after each answer):
  5 perfect, 4 correct after hesitation, 3 correct with difficulty,
  2 wrong but felt familiar, 1 wrong, 0 blackout.
"""
from dataclasses import dataclass
from datetime import date, timedelta

MIN_EASE = 1.3


@dataclass(frozen=True)
class CardState:
    repetitions: int = 0      # consecutive successful reviews
    interval_days: int = 0    # days until the next review
    ease: float = 2.5         # how quickly the interval grows


def review(state: CardState, quality: int, today: date) -> tuple[CardState, date]:
    """Return the card's new state and its next due date."""
    if not 0 <= quality <= 5:
        raise ValueError("quality must be between 0 and 5")

    if quality < 3:
        # Failed: start the learning steps over, review again tomorrow.
        repetitions, interval = 0, 1
    else:
        if state.repetitions == 0:
            interval = 1
        elif state.repetitions == 1:
            interval = 6
        else:
            interval = round(state.interval_days * state.ease)
        repetitions = state.repetitions + 1

    # Ease moves with how hard the answer felt, never below the floor.
    ease = state.ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease = max(MIN_EASE, round(ease, 4))

    new_state = CardState(repetitions, interval, ease)
    return new_state, today + timedelta(days=interval)
