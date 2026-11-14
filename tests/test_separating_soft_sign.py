import unicodedata

import pytest

from ce_translit import NasalDecision, Transliterator, atransliterate, transliterate


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("шельелла", "şelyella"),
        ("Шельелла", "Şelyella"),
        ("ШЕЛЬЕЛЛА", "ŞELYELLA"),
        ("ШЕЛЬЕ\u0301ЛЛА", "ŞELYÉLLA"),
        ("ШЕЛЬЕ\u0301", "ŞELYÉ"),
        ("ШЕЛЬ\u0301Е", "ŞEĹYE"),
        ("Е\u0301ЛЛА", "YÉLLA"),
        ("ЧЕКХЪЕ\u0301ЛИ", "ÇEQYÉLI"),
        ("шельЕлла", "şelYella"),
        ("льЕ", "lYe"),
        ("ЛЬЕ", "LYE"),
        ("пьеса", "pyesa"),
        ("барьер", "baryer"),
        ("ателье", "atelye"),
        ("шельелла-едда", "şelyella-yedda"),
        ("«шельелла»,\tшельелла!\n", "«şelyella»,\tşelyella!\n"),
        ("шель\u0301елла", "şeĺyella"),
    ],
)
def test_e_after_separating_soft_sign(source, expected):
    assert transliterate(source) == unicodedata.normalize("NFC", expected)


@pytest.mark.parametrize("unit", ["хь", "ххь", "аь", "оь", "уь", "яь", "юь"])
@pytest.mark.parametrize("upper", [False, True])
def test_soft_sign_consumed_by_mapped_unit_is_not_a_separator(unit, upper):
    source = (unit + "е").upper() if upper else unit + "е"
    mapped_unit = Transliterator()._mapping[source[:-1]]
    expected = mapped_unit + ("E" if upper else "e")
    assert transliterate(source) == unicodedata.normalize("NFC", expected)


def test_custom_compound_mapping_controls_unit_boundary():
    converter = Transliterator(mapping={"ль": "L", "е": "E"})
    assert converter.transliterate("лье") == "LE"


def test_combining_mark_does_not_hide_consumed_mapped_unit():
    assert transliterate("хь\u0301е") == unicodedata.normalize("NFC", "ẋ\u0301e")


def test_async_core_uses_same_separator_rule():
    import asyncio

    assert asyncio.run(atransliterate("шельелла")) == "şelyella"


def test_separator_rule_preserves_resolver_source_spans():
    source = "шельелла сан"

    class Resolver:
        def resolve(self, text, targets):
            assert text == source
            assert len(targets) == 1
            target = targets[0]
            assert text[target.start : target.end] == "сан"
            return (
                NasalDecision(
                    target.id,
                    target.word,
                    target.start,
                    target.end,
                    "nasalization",
                    "Rendering fixture.",
                ),
            )

    result = Transliterator(nasal_resolver=Resolver()).transliterate_detailed(source)
    assert result.text == "şelyella saŋ"
    assert result.decisions[0].start == source.index("сан")
