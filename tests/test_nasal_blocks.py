from dataclasses import replace

import pytest

from ce_translit import Transliterator
from ce_translit._tokenizer import _iter_word_tokens
from ce_translit.ai._blocks import _iter_blocks
from ce_translit.errors import NasalInputError


def targets(text):
    return Transliterator()._targets(text)


def test_all_occurrences_owned_once_and_context_offsets_stay_valid():
    text = "начало. " + " ".join(["сан"] * 180) + " конец."
    expected = targets(text)
    blocks = list(_iter_blocks(text, expected))
    assert [len(b.targets) for b in blocks] == [64, 64, 52]
    assert [t.id for b in blocks for t in b.targets] == [t.id for t in expected]
    for block in blocks:
        assert text[block.start : block.start + len(block.text)] == block.text
        assert len(block.text) <= 16_000
        for target in block.targets:
            assert (
                block.text[target.start - block.start : target.end - block.start]
                == target.word
            )


@pytest.mark.parametrize("separator", [". ", "!\r\n", "\n\n", "\r\n\r\n"])
def test_prefers_natural_boundaries(separator):
    text = "сан" + separator + "сан сан сан"
    blocks = list(_iter_blocks(text, targets(text), max_targets=3))
    assert len(blocks[0].targets) == 1
    assert sum(len(b.targets) for b in blocks) == 4


def test_long_spans_and_context_windows_never_split_words():
    text = (
        "предисловие "
        + ("слово " * 9)
        + "сан "
        + ("слово " * 8)
        + "сан "
        + ("слово " * 9)
        + "окончание"
    )
    blocks = list(_iter_blocks(text, targets(text), max_chars=20, context_chars=17))
    token_boundaries = {0, len(text)}
    for token in _iter_word_tokens(text):
        token_boundaries.update((token.start, token.end))
    for block in blocks:
        end = block.start + len(block.text)
        assert not any(
            t.start < block.start < t.end or t.start < end < t.end
            for t in _iter_word_tokens(text)
        )
        assert len(block.text) <= 54
    assert len(blocks) == 2


def test_all_targets_prevalidated_before_first_block():
    text = "сан " + "а" * 12_001 + "н"
    with pytest.raises(NasalInputError):
        next(_iter_blocks(text, targets(text)))


@pytest.mark.parametrize(
    "change", ["duplicate", "out_of_order", "inside_word", "non_final_n", "word"]
)
def test_rejects_invalid_targets(change):
    text = "сан сан санна"
    rows = list(targets(text))
    if change == "duplicate":
        rows[1] = replace(rows[1], id=rows[0].id)
    elif change == "out_of_order":
        rows.reverse()
    elif change == "inside_word":
        rows[0] = replace(rows[0], start=1, word="ан")
    elif change == "non_final_n":
        rows[1] = replace(rows[1], start=8, end=13, word="санна")
    else:
        rows[0] = replace(rows[0], word="бен")
    with pytest.raises(NasalInputError):
        list(_iter_blocks(text, rows))


def test_no_targets_no_blocks():
    assert list(_iter_blocks("слово", ())) == []
