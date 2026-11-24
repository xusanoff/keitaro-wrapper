"""Pure weight (share) algorithm. No I/O, no ORM: easy to test.

Rules
-----
* Removed offers always get 0 % and their pin flag is ignored.
* Pinned active offers keep their share.
* ``100 - sum(pinned)`` is split evenly between non-pinned active offers.
  The integer remainder goes +1 to the first non-pinned offers by position
  (deterministic, so the UI and Keitaro always show the same numbers).
* If every active offer is pinned, shares are kept as they are; whether they
  add up to 100 is checked by :func:`push_problem` (Push is blocked otherwise).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


class WeightError(ValueError):
    pass


@dataclass(frozen=True)
class WeightItem:
    status: str  # "active" | "removed"
    pinned: bool
    share: int

    @property
    def active(self) -> bool:
        return self.status == "active"


def distribute(items: Sequence[WeightItem]) -> list[int]:
    """Return new shares for ``items`` (same order = position order)."""
    pinned_total = 0
    free_idx: list[int] = []
    for i, it in enumerate(items):
        if not it.active:
            continue
        if it.pinned:
            if not 0 <= it.share <= 100:
                raise WeightError(f"Pinned weight must be between 0 and 100, got {it.share}%")
            pinned_total += it.share
        else:
            free_idx.append(i)

    if pinned_total > 100:
        raise WeightError(f"Pinned weights add up to {pinned_total}%, which is more than 100%")

    result = [it.share if (it.active and it.pinned) else 0 for it in items]
    if free_idx:
        rest = 100 - pinned_total
        base, remainder = divmod(rest, len(free_idx))
        for n, i in enumerate(free_idx):
            result[i] = base + (1 if n < remainder else 0)
    return result


def push_problem(items: Sequence[WeightItem]) -> str | None:
    """Why this offer list cannot be pushed to Keitaro, or ``None`` if it can."""
    active = [it for it in items if it.active]
    if not active:
        return "The stream has no active offers. Add or bring back at least one offer before pushing."
    total = sum(it.share for it in active)
    if any(not 0 <= it.share <= 100 for it in active):
        return "Every weight must be between 0 and 100%."
    if total != 100:
        if all(it.pinned for it in active):
            return f"All offers are pinned and add up to {total}%. Change a pinned weight or unpin an offer so the total is 100%."
        return f"Weights add up to {total}%, not 100%."
    zero = sum(1 for it in active if it.share == 0)
    if zero:
        return (
            f"{zero} active offer(s) would get 0% of traffic. "
            "Lower the pinned weights or remove those offers before pushing."
        )
    return None
