"""Bootstrap resampling in memory bounded chunks."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import numpy.typing as npt

# Upper bound on how many resampled indices we hold in memory at once. Keeps memory flat
# for large suites: 10,000 resamples of 5,000 cases would otherwise be 400 MB.
MAX_CHUNK_ELEMENTS = 2_000_000


def resample_chunks(
    n_cases: int, n_resamples: int, rng: np.random.Generator
) -> Iterator[tuple[slice, npt.NDArray[np.int64]]]:
    """Yield (where, indices) pairs that together cover all resamples.

    indices has shape (rows, n_cases) and each row is one resample of case positions drawn
    with replacement. where is the slice of the output array those rows belong to.
    """
    rows_per_chunk = max(1, MAX_CHUNK_ELEMENTS // n_cases)
    for start in range(0, n_resamples, rows_per_chunk):
        rows = min(rows_per_chunk, n_resamples - start)
        yield slice(start, start + rows), rng.integers(0, n_cases, size=(rows, n_cases))
