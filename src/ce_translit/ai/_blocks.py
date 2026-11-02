"""Bounded source-context windows, with disjoint occurrence ownership."""

import re
from bisect import bisect_left, bisect_right
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from ce_translit._models import NasalTarget
from ce_translit._tokenizer import _final_n_index, _iter_word_tokens
from ce_translit.errors import NasalInputError

_PARAGRAPH = re.compile(r"\r?\n[ \t]*\r?\n")
_SENTENCE = re.compile(r"[.!?\u2026]+[\u00bb\"')\]]*(?:\s+|$)")


@dataclass(frozen=True)
class _NasalBlock:
    text: str
    start: int
    targets: tuple[NasalTarget, ...]


def _iter_blocks(
    text: str,
    targets: Sequence[NasalTarget],
    *,
    max_targets: int = 64,
    max_chars: int = 12_000,
    context_chars: int = 2_000,
) -> Iterator[_NasalBlock]:
    if max_targets < 1 or max_chars < 1 or context_chars < 0:
        raise ValueError("Invalid context limits.")
    tokens = tuple(_iter_word_tokens(text))
    starts = [token.start for token in tokens]
    ends = [token.end for token in tokens]
    seen = set()
    previous_end = 0
    for target in targets:
        token_index = bisect_left(starts, target.start)
        if (
            not isinstance(target.id, str)
            or not target.id
            or target.id in seen
            or target.start < previous_end
            or token_index >= len(tokens)
            or (
                tokens[token_index].text,
                tokens[token_index].start,
                tokens[token_index].end,
            )
            != (target.word, target.start, target.end)
            or _final_n_index(target.word) is None
        ):
            raise NasalInputError(
                "Targets must be unique source-ordered final-n word occurrences."
            )
        if target.end - target.start > max_chars:
            raise NasalInputError(
                "A target word exceeds the context block character limit."
            )
        seen.add(target.id)
        previous_end = target.end

    index = 0
    while index < len(targets):
        main_start = targets[index].start
        stop = index + 1
        while (
            stop < len(targets)
            and stop - index < max_targets
            and targets[stop].end - main_start <= max_chars
        ):
            stop += 1
        main_end = targets[stop - 1].end

        # Prefer a natural boundary within the bounded group, without losing IDs.
        if stop < len(targets):
            segment = text[main_start:main_end]
            paragraphs = list(_PARAGRAPH.finditer(segment))
            boundaries = paragraphs or list(_SENTENCE.finditer(segment))
            if boundaries:
                boundary = main_start + boundaries[-1].end()
                while stop > index + 1 and targets[stop - 1].end > boundary:
                    stop -= 1
                main_end = targets[stop - 1].end

        left = max(0, main_start - context_chars)
        right = min(len(text), main_end + context_chars)
        left_word = bisect_right(starts, left) - 1
        if left_word >= 0 and starts[left_word] < left < ends[left_word]:
            left = ends[left_word]
        right_word = bisect_right(starts, right) - 1
        if right_word >= 0 and starts[right_word] < right < ends[right_word]:
            right = starts[right_word]
        yield _NasalBlock(text[left:right], left, tuple(targets[index:stop]))
        index = stop
