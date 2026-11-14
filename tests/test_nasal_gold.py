import json
import unicodedata
from pathlib import Path

from ce_translit import NasalDecision, Transliterator

GOLD = json.loads(
    (Path(__file__).parent / "fixtures/nasal_gold.json").read_text(encoding="utf-8")
)


def test_native_speaker_corrected_p07_khyan_is_nasalized():
    passage = next(p for p in GOLD["texts"] if p["id"] == "P07")
    target = next(t for t in passage["targets"] if t["id"] == "P07-T005")
    sentence = "Хьоьга хьан белхор бу шен беза бала?"
    assert target["start"] == passage["text"].index(sentence) + len("Хьоьга ")
    assert passage["text"][target["start"] : target["end"]] == "хьан"
    assert target["kind"] == "nasalization"


def test_all_63_human_reviewed_occurrences_are_detected_and_applied():
    count = 0
    for passage in GOLD["texts"]:
        gold = passage["targets"]

        class GoldResolver:
            def resolve(self, text, targets, gold=gold):
                assert len(targets) == len(gold)
                assert [(t.word, t.start, t.end) for t in targets] == [
                    (t["word"], t["start"], t["end"]) for t in gold
                ]
                return tuple(
                    NasalDecision(
                        t.id, t.word, t.start, t.end, g["kind"], "Native-speaker gold."
                    )
                    for t, g in zip(targets, gold, strict=True)
                )

        result = Transliterator(nasal_resolver=GoldResolver()).transliterate_detailed(
            passage["text"]
        )
        expected = passage["text"]
        for target in reversed(gold):
            word = target["word"]
            # These corpus fixtures have no trailing combining marks.
            final = "ŋ" if target["kind"] == "nasalization" else "n"
            if word[-1].isupper():
                final = final.upper()
            expected_word = unicodedata.normalize(
                "NFC", Transliterator().transliterate(word[:-1]) + final
            )
            expected = (
                expected[: target["start"]] + expected_word + expected[target["end"] :]
            )
        assert result.text == Transliterator().transliterate(expected)
        count += len(result.decisions)
    assert count == 63
