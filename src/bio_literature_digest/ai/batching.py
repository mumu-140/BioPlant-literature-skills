from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TypeVar

T = TypeVar("T")


def chunk_by_limits(
    items: Iterable[T],
    *,
    max_items: int,
    max_chars: int,
    size_fn: Callable[[T], int],
) -> list[list[T]]:
    """Split items into stable batches bounded by item count and estimated size."""

    batches: list[list[T]] = []
    current: list[T] = []
    current_chars = 0
    max_items = max(1, int(max_items))
    max_chars = max(1, int(max_chars))

    for item in items:
        item_chars = max(1, int(size_fn(item)))
        if current and (len(current) >= max_items or current_chars + item_chars > max_chars):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += item_chars

    if current:
        batches.append(current)
    return batches

