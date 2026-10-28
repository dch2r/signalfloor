"""BM25 keyword search.

For a query, each passage gets a score summed over the query words it contains:

    idf(word) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / average_length))

tf is how often the word appears in the passage. idf is high for rare words and low for
common ones, so "Derrickson" counts for much more than "film". k1 caps how much repeating a
word helps, and b discounts long passages that match just because they contain more words.
The idf formula is the one Lucene uses, which never goes negative.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Sequence

_WORD = re.compile(r"\w+")

# Very common English words. Dropping them keeps scores focused on words that carry meaning.
STOPWORDS = frozenset(
    """a an and are as at be by for from has have he her his in is it its of on or she that the
    their they this to was were what when where which who whom why will with""".split()  # noqa: SIM905
)


def tokenize(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in STOPWORDS]


class BM25:
    def __init__(self, documents: Sequence[str], *, k1: float = 1.5, b: float = 0.75) -> None:
        if not documents:
            raise ValueError("BM25 needs at least one document")
        self.k1 = k1
        self.b = b

        tokenized = [tokenize(d) for d in documents]
        self._lengths = [len(t) for t in tokenized]
        self._average_length = sum(self._lengths) / len(tokenized) or 1.0

        # word -> list of (document index, count in that document)
        self._postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for i, tokens in enumerate(tokenized):
            for word, count in Counter(tokens).items():
                self._postings[word].append((i, count))

        n = len(tokenized)
        self._idf = {
            word: math.log(1 + (n - len(docs) + 0.5) / (len(docs) + 0.5))
            for word, docs in self._postings.items()
        }

    def search(self, query: str, k: int = 10) -> list[tuple[int, float]]:
        """Return up to k (document index, score) pairs, best first. Ties go to the lower index."""
        scores: dict[int, float] = defaultdict(float)
        for word in set(tokenize(query)):
            idf = self._idf.get(word)
            if idf is None:
                continue
            for doc, tf in self._postings[word]:
                norm = 1 - self.b + self.b * self._lengths[doc] / self._average_length
                scores[doc] += idf * tf * (self.k1 + 1) / (tf + self.k1 * norm)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return ranked[:k]
