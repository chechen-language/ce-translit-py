"""Sentence contexts and independently bounded request batches."""

import re
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ce_translit._models import NasalTarget
from ce_translit._tokenizer import _final_n_index, _iter_word_tokens
from ce_translit.errors import NasalInputError

ContextMode = Literal["sentence", "adjacent"]
_LINE_BREAK = r"(?:\r\n|\r(?!\n)|(?<!\r)\n|[\u0085\u2028])"
_PARAGRAPH = re.compile(rf"(?:{_LINE_BREAK}[^\S\r\n\u0085\u2028\u2029]*){{2,}}|\u2029")
_SOFT_BREAKS = str.maketrans({"\r": " ", "\n": " ", "\u0085": " ", "\u2028": " "})
_LAST_WORD = re.compile(r"([^\W\d_]+)\.$", re.UNICODE)
_ABBREVIATIONS = re.compile(
    r"(?:\b(?:стр|рис|им|ул|г|др)|\bт\.[ \t]*(?:е|д|п))\.$", re.I
)
_ADDRESS = re.compile(
    r"(?:https?://|www\.)[^\s<>]+|(?<!\S)[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+"
)


@dataclass(frozen=True)
class _Context:
    text: str
    start: int
    targets: tuple[NasalTarget, ...]


@dataclass(frozen=True)
class _Batch:
    contexts: tuple[_Context, ...]

    @property
    def targets(self) -> tuple[NasalTarget, ...]:
        return tuple(target for context in self.contexts for target in context.targets)


def _sentence_spans(text: str) -> tuple[tuple[int, int], ...]:
    from uniseg.sentencebreak import sentence_boundaries  # type: ignore[import-untyped]

    spans = []
    paragraph_start = 0
    # Segmentation uses a same-length shadow only; all slices use the original.
    for paragraph_end, next_start in [
        *((match.start(), match.end()) for match in _PARAGRAPH.finditer(text)),
        (len(text), len(text)),
    ]:
        shadow = text[paragraph_start:paragraph_end].translate(_SOFT_BREAKS)
        addresses = list(_ADDRESS.finditer(shadow))
        address_index = 0
        begin = 0
        for boundary in sentence_boundaries(shadow):
            if boundary == 0:
                continue
            if boundary < len(shadow):
                while (
                    address_index < len(addresses)
                    and addresses[address_index].end() <= boundary
                ):
                    address_index += 1
                inside_address = (
                    address_index < len(addresses)
                    and addresses[address_index].start()
                    < boundary
                    < addresses[address_index].end()
                )
                tail = shadow[max(0, boundary - 32) : boundary].rstrip()
                last = _LAST_WORD.search(tail)
                initial = last is not None and len(last[1]) == 1 and last[1].isupper()
                if inside_address or initial or _ABBREVIATIONS.search(tail):
                    continue
            start, end = begin, boundary
            while start < end and text[paragraph_start + start].isspace():
                start += 1
            while end > start and text[paragraph_start + end - 1].isspace():
                end -= 1
            if start < end:
                spans.append((paragraph_start + start, paragraph_start + end))
            begin = boundary
        paragraph_start = next_start
    return tuple(spans)


def _prepare_batches(
    text: str,
    targets: Sequence[NasalTarget],
    *,
    context: ContextMode = "sentence",
    max_targets_per_request: int = 64,
    max_context_chars: int = 12_000,
) -> tuple[_Batch, ...]:
    if context not in ("sentence", "adjacent"):
        raise ValueError("context must be 'sentence' or 'adjacent'.")
    for limit in (max_targets_per_request, max_context_chars):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("Request limits must be positive integers.")
    if not targets:
        return ()
    tokens = {(token.start, token.end): token.text for token in _iter_word_tokens(text)}
    seen: set[str] = set()
    previous_end = 0
    for target in targets:
        if (
            not isinstance(target, NasalTarget)
            or not isinstance(target.id, str)
            or not target.id
            or target.id in seen
            or type(target.start) is not int
            or type(target.end) is not int
            or target.start < previous_end
            or tokens.get((target.start, target.end)) != target.word
            or _final_n_index(target.word) is None
        ):
            raise NasalInputError(
                "Targets must be unique source-ordered word occurrences."
            )
        seen.add(target.id)
        previous_end = target.end
        if target.end - target.start > max_context_chars:
            raise NasalInputError("A word occurrence exceeds max_context_chars.")

    spans = _sentence_spans(text)
    starts = [start for start, _ in spans]
    groups: dict[int, list[NasalTarget]] = {}
    for target in targets:
        index = bisect_right(starts, target.start) - 1
        if index < 0 or target.end > spans[index][1]:
            raise NasalInputError("An occurrence crosses a sentence boundary.")
        groups.setdefault(index, []).append(target)

    contexts = []
    for index, owned in groups.items():
        left = max(0, index - 1) if context == "adjacent" else index
        right = min(len(spans) - 1, index + 1) if context == "adjacent" else index
        start, end = spans[left][0], spans[right][1]
        if end - start > max_context_chars:
            raise NasalInputError(
                "A complete context exceeds max_context_chars; increase the limit."
            )
        contexts.append(_Context(text[start:end], start, tuple(owned)))

    batches: list[_Batch] = []
    pending: list[_Context] = []
    chars = count = 0
    for item in contexts:
        offset = 0
        while offset < len(item.targets):
            if pending and (
                count == max_targets_per_request
                or chars + len(item.text) > max_context_chars
            ):
                batches.append(_Batch(tuple(pending)))
                pending, chars, count = [], 0, 0
            take = min(max_targets_per_request - count, len(item.targets) - offset)
            pending.append(
                _Context(item.text, item.start, item.targets[offset : offset + take])
            )
            chars += len(item.text)
            count += take
            offset += take
    if pending:
        batches.append(_Batch(tuple(pending)))
    return tuple(batches)
