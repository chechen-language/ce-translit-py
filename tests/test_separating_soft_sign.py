import unicodedata

import pytest

from ce_translit import NasalDecision, Transliterator, atransliterate, transliterate


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("шельелла", "şelyella"),
        ("шекьелира", "şekyelira"),
        ("Шельелла", "Şelyella"),
        ("ШЕЛЬЕЛЛА", "ŞELYELLA"),
        ("ШЕЛЬЕ\u0301ЛЛА", "ŞELYELLA"),
        ("ШЕЛЬЕ\u0301", "ŞELYE"),
        ("ШЕЛЬ\u0301Е", "ŞELYE"),
        ("Е\u0301ЛЛА", "YELLA"),
        ("ЧЕКХЪЕ\u0301ЛИ", "ÇEQYELI"),
        ("шельЕлла", "şelYella"),
        ("льЕ", "lYe"),
        ("ЛЬЕ", "LYE"),
        ("пьеса", "pyesa"),
        ("барьер", "baryer"),
        ("ателье", "atelye"),
        ("шельелла-едда", "şelyella-yedda"),
        ("«шельелла»,\tшельелла!\n", "«şelyella»,\tşelyella!\n"),
        ("шель\u0301елла", "şelyella"),
    ],
)
def test_e_after_separating_soft_sign(source, expected):
    assert transliterate(source) == unicodedata.normalize("NFC", expected)


@pytest.mark.parametrize("unit", ["хь", "ххь"])
@pytest.mark.parametrize("upper", [False, True])
def test_soft_sign_consumed_by_mapped_unit_is_not_a_separator(unit, upper):
    source = (unit + "е").upper() if upper else unit + "е"
    mapped_unit = Transliterator()._mapping[source[:-1]]
    expected = mapped_unit + Transliterator()._mapping[source[-1]]
    assert transliterate(source) == unicodedata.normalize("NFC", expected)


def test_custom_compound_mapping_controls_unit_boundary():
    converter = Transliterator(mapping={"ль": "L", "е": "E"})
    assert converter.transliterate("лье") == "LE"


def test_combining_mark_does_not_hide_consumed_mapped_unit():
    assert transliterate("хь\u0301е") == "ẋe"


def test_async_core_uses_same_separator_rule():
    import asyncio

    assert asyncio.run(atransliterate("шельелла")) == "şelyella"


def test_separator_rule_preserves_resolver_source_spans():
    source = "пьеса сан"

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
    assert result.text == "pyesa saŋ"
    assert result.decisions[0].start == source.index("сан")


@pytest.mark.parametrize(
    ("source", "expected"),
    [("шекьяьлла", "şekyälla"), ("хӏаллакьхилла", "hallakxilla")],
)
def test_native_separating_soft_sign_examples(source, expected):
    assert transliterate(source) == expected
