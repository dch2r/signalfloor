"""Answer scoring used by SQuAD and HotpotQA.

Both scores compare a predicted answer with the gold answer after normalising them:
lowercase, drop punctuation and the articles a, an and the, and collapse whitespace.

exact_match is 1 when the normalised answers are identical and 0 otherwise.
f1 gives partial credit by counting the words the two answers share.
"""

from __future__ import annotations

import re
import string
from collections import Counter

_ARTICLES = re.compile(r"\b(a|an|the)\b")
_PUNCTUATION = str.maketrans("", "", string.punctuation)

# HotpotQA scores these special answers as all or nothing, never by word overlap.
_ALL_OR_NOTHING = {"yes", "no", "noanswer"}


def normalize_answer(text: str) -> str:
    text = text.lower().translate(_PUNCTUATION)
    text = _ARTICLES.sub(" ", text)
    return " ".join(text.split())


def exact_match(prediction: str, gold: str) -> float:
    return float(normalize_answer(prediction) == normalize_answer(gold))


def f1(prediction: str, gold: str) -> float:
    pred, ref = normalize_answer(prediction), normalize_answer(gold)
    if (pred in _ALL_OR_NOTHING or ref in _ALL_OR_NOTHING) and pred != ref:
        return 0.0

    pred_words, ref_words = pred.split(), ref.split()
    common = Counter(pred_words) & Counter(ref_words)
    overlap = sum(common.values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred_words)
    recall = overlap / len(ref_words)
    return 2 * precision * recall / (precision + recall)
