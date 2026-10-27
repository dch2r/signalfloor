"""Match up two sets of per-case results by case ID."""

from __future__ import annotations

from collections.abc import Iterable, Mapping


class PairingError(ValueError):
    """The two sets of results do not contain the same test cases."""


def shared_case_ids(
    first: Mapping[str, object],
    second: Mapping[str, object],
    *,
    names: tuple[str, str],
) -> list[str]:
    """Return the case IDs in a fixed order, or raise if the two sides differ."""
    only_first = first.keys() - second.keys()
    only_second = second.keys() - first.keys()
    if only_first or only_second:
        raise PairingError(
            f"{names[0]} and {names[1]} must contain the same cases: "
            f"{len(only_first)} only in {names[0]} (e.g. {examples(only_first)}), "
            f"{len(only_second)} only in {names[1]} (e.g. {examples(only_second)})"
        )
    if len(first) < 2:
        raise ValueError(f"need at least 2 cases, got {len(first)}")
    return sorted(first)


def examples(ids: Iterable[str], limit: int = 3) -> str:
    ordered = sorted(ids)
    if not ordered:
        return "none"
    shown = ordered[:limit]
    more = len(ordered) - len(shown)
    return ", ".join(shown) + (f" and {more} more" if more else "")
