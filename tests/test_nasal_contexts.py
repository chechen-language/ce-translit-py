import json
from dataclasses import replace
from pathlib import Path

import pytest

from ce_translit import Transliterator
from ce_translit.ai._contexts import _prepare_batches, _sentence_spans
from ce_translit.errors import NasalInputError

pytest.importorskip("uniseg")


def contexts(text, **kwargs):
    return [
        item
        for batch in _prepare_batches(text, Transliterator()._targets(text), **kwargs)
        for item in batch.contexts
    ]


def sentences(text):
    return [text[start:end] for start, end in _sentence_spans(text)]


def test_only_target_sentences_are_sent_by_default():
    text = "Начало. Сан дош ду. Далее. Шун дош ду! Конец."
    items = contexts(text)
    assert [item.text for item in items] == ["Сан дош ду.", "Шун дош ду!"]
    assert len(_prepare_batches(text, Transliterator()._targets(text))) == 1


def test_adjacent_context_is_explicit_and_does_not_own_neighbor_targets():
    text = "Сан дош ду. Бен. Шун дош ду."
    items = contexts(text, context="adjacent")
    assert [item.text for item in items] == [
        "Сан дош ду. Бен.",
        text,
        "Бен. Шун дош ду.",
    ]
    assert [len(item.targets) for item in items] == [1, 1, 1]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Сан дош\nду. Шун дош ду.", ["Сан дош\nду.", "Шун дош ду."]),
        ("Сан дош\r\nду.\r\nШун дош ду.", ["Сан дош\r\nду.", "Шун дош ду."]),
        ("Сан дош\n\nШун дош", ["Сан дош", "Шун дош"]),
        ("Сан дош\r\n \r\nШун дош", ["Сан дош", "Шун дош"]),
        ("А. Б. Сан дош ду. Шун дош ду.", ["А. Б. Сан дош ду.", "Шун дош ду."]),
        ("См. стр. 2. Сан дош ду.", ["См. стр. 2.", "Сан дош ду."]),
        ("3.14. Сан дош ду.", ["3.14.", "Сан дош ду."]),
        ("«Сан дош ду?» Шун дош ду!", ["«Сан дош ду?»", "Шун дош ду!"]),
        ("Сан дош... Шун дош!", ["Сан дош...", "Шун дош!"]),
        ("Сан дош ду", ["Сан дош ду"]),
        (
            "Сан https://a.B.example/x ду. Шун ду.",
            ["Сан https://a.B.example/x ду.", "Шун ду."],
        ),
    ],
)
def test_sentence_tailoring(text, expected):
    assert sentences(text) == expected


def test_full_sentence_repeated_when_target_limit_splits_it():
    text = " ".join(["сан"] * 180) + "."
    batches = _prepare_batches(text, Transliterator()._targets(text))
    assert [len(batch.targets) for batch in batches] == [64, 64, 52]
    assert all(item.text == text for batch in batches for item in batch.contexts)
    assert [t.id for b in batches for t in b.targets] == [
        t.id for t in Transliterator()._targets(text)
    ]


def test_character_limit_bounds_request_sum_not_sentence_truncation():
    text = "Сан ду. Шун ду. Бен ду."
    batches = _prepare_batches(
        text, Transliterator()._targets(text), max_context_chars=14
    )
    assert [len(batch.contexts) for batch in batches] == [2, 1]
    assert all(
        sum(len(item.text) for item in batch.contexts) <= 14 for batch in batches
    )


def test_too_long_later_sentence_fails_during_preflight():
    text = "Сан ду. " + "слово " * 10 + "сан."
    with pytest.raises(NasalInputError, match="complete context"):
        _prepare_batches(text, Transliterator()._targets(text), max_context_chars=20)


@pytest.mark.parametrize(
    "change", ["duplicate", "order", "inside", "nonfinal", "word", "bool"]
)
def test_invalid_targets(change):
    text = "сан сан санна"
    rows = list(Transliterator()._targets(text))
    if change == "duplicate":
        rows[1] = replace(rows[1], id=rows[0].id)
    elif change == "order":
        rows.reverse()
    elif change == "inside":
        rows[0] = replace(rows[0], start=1, word="ан")
    elif change == "nonfinal":
        rows[1] = replace(rows[1], start=8, end=13, word="санна")
    elif change == "bool":
        rows[0] = replace(rows[0], start=False)
    else:
        rows[0] = replace(rows[0], word="бен")
    with pytest.raises(NasalInputError):
        _prepare_batches(text, rows)


def test_all_reviewed_gold_targets_have_exact_source_and_context_offsets():
    gold = json.loads((Path(__file__).parent / "fixtures/nasal_gold.json").read_text())
    total = 0
    for passage in gold["texts"]:
        text = passage["text"]
        expected = Transliterator()._targets(text)
        for mode in ("sentence", "adjacent"):
            batches = _prepare_batches(text, expected, context=mode)
            assert [t for b in batches for t in b.targets] == list(expected)
            for batch in batches:
                for item in batch.contexts:
                    assert text[item.start : item.start + len(item.text)] == item.text
                    for target in item.targets:
                        assert (
                            item.text[
                                target.start - item.start : target.end - item.start
                            ]
                            == target.word
                        )
        total += len(expected)
    assert total == 63


def test_empty_targets_do_not_segment():
    assert _prepare_batches("слово", ()) == ()


@pytest.mark.parametrize(
    "separator", ["\n\u00a0\n", "\r\r", "\u2028\u2028", "\u0085\u0085", "\u2029"]
)
def test_unicode_blank_lines_and_paragraph_separators(separator):
    assert sentences(f"Сан ду{separator}Шун ду") == ["Сан ду", "Шун ду"]


@pytest.mark.parametrize("separator", ["\r\n", "\n", "\r", "\u2028", "\u0085"])
def test_single_line_break_does_not_become_a_paragraph(separator):
    assert sentences(f"Сан дош{separator}ду.") == [f"Сан дош{separator}ду."]


def test_initial_30_reviewed_positions_remain_in_full_target_coverage():
    reviewed = json.loads(
        (Path(__file__).parent / "fixtures/nasal_reviewed_positions.json").read_text()
    )
    for position in reviewed["positions"]:
        text = position["text"]
        gold = position["target"]
        expected = Transliterator()._targets(text)
        for mode in ("sentence", "adjacent"):
            batches = _prepare_batches(text, expected, context=mode)
            received = [target for batch in batches for target in batch.targets]
            assert received == list(expected)
            assert any(
                (target.start, target.end, target.word)
                == (gold["start"], gold["end"], gold["word"])
                for target in received
            )
    assert len(reviewed["positions"]) == 30
