"""Unicode word boundaries without altering the source or its offsets."""

import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass


def _without_marks(text: str) -> str:
    return "".join(
        char for char in text if not unicodedata.category(char).startswith("M")
    )


@dataclass(frozen=True)
class _WordToken:
    text: str
    start: int
    end: int


def _iter_word_tokens(text: str) -> Iterator[_WordToken]:
    """Group Unicode letters/digits and attached marks, regardless of script."""
    start = None
    for i, char in enumerate(text):
        category = unicodedata.category(char)
        if category.startswith("L") or category == "Nd":
            if start is None:
                start = i
        elif category.startswith("M") and start is not None:
            continue
        elif start is not None:
            yield _WordToken(text[start:i], start, i)
            start = None
    if start is not None:
        yield _WordToken(text[start:], start, len(text))


def _final_n_index(word: str) -> int | None:
    index = len(word) - 1
    while index >= 0 and unicodedata.category(word[index]).startswith("M"):
        index -= 1
    return index if index >= 0 and word[index] in ("н", "Н") else None
