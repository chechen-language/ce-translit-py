import asyncio

import pytest

from ce_translit import NasalDecision, Transliterator, transliterate


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("дӏаелира", "djayelira"),
        ("Дӏаелира", "Djayelira"),
        ("ДӀАЕЛИРА", "DJAYELIRA"),
        ("дӏаЕлира", "djaYelira"),
        ("йолаелира", "yolayelira"),
        ("гучуелира", "guçuyelira"),
        ("хьеелира", "ẋeyelira"),
        ("тӏееана", "ṫeyeana"),
        ("дӏа\u0301е\u0301лира", "djayelira"),
        ("«дӏаелира»,\tгучуелира!\n", "«djayelira»,\tguçuyelira!\n"),
    ],
)
def test_owner_confirmed_e_after_vowel_readings(source, expected):
    assert transliterate(source) == expected
    assert asyncio.run(Transliterator().atransliterate(source)) == expected


@pytest.mark.parametrize(
    "unit",
    ["а", "е", "ё", "и", "о", "у", "ы", "э", "ю", "я", "аь", "оь", "уь", "яь", "юь"],
)
@pytest.mark.parametrize("upper", [False, True])
def test_cyrillic_vowel_units_are_followed_by_a_glide(unit, upper):
    converter = Transliterator()
    vowel = unit.upper() if upper else unit
    source = "б" + vowel + ("ЕЛ" if upper else "ел")
    assert converter.transliterate(source) == "b" + converter._mapping[vowel] + (
        "YEL" if upper else "yel"
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("хье", "ẋe"),
        ("ххье", "ẋẋe"),
        ("къе", "q̇e"),
        ("тӏе", "ṫe"),
        ("йе", "ye"),
        ("aе", "ae"),
        ("1е", "1e"),
    ],
)
def test_consonants_and_other_scripts_do_not_trigger_the_vowel_rule(source, expected):
    assert transliterate(source) == expected


def test_decomposed_source_vowels_keep_their_identity_before_e():
    assert transliterate("бе\u0308ел") == "böyel"
    assert transliterate("би\u0306ел") == "byel"


def test_vowel_detection_uses_source_units_rather_than_custom_latin_output():
    mapping = {**Transliterator()._mapping, "б": "a", "а": "X"}
    converter = Transliterator(mapping)
    assert converter.transliterate("бе") == "ae"
    assert converter.transliterate("ае") == "Xye"
    assert (
        Transliterator({**mapping, "ба": "CUSTOM"}).transliterate("бае") == "CUSTOMye"
    )
    assert (
        Transliterator({**mapping, "бае": "EXPLICIT"}).transliterate("бае")
        == "EXPLICIT"
    )


def test_vowel_glide_preserves_original_resolver_context_and_offsets():
    source = "😀 дӏа\u0301елира [са\u0301н] хьеелира"

    class Resolver:
        def resolve(self, text, targets):
            assert text == source
            assert len(targets) == 1
            target = targets[0]
            assert text[target.start : target.end] == "са\u0301н"
            return (
                NasalDecision(
                    target.id, target.word, target.start, target.end, "nasalization"
                ),
            )

        async def aresolve(self, text, targets):
            return self.resolve(text, targets)

    converter = Transliterator(nasal_resolver=Resolver())
    result = converter.transliterate_detailed(source)
    assert result.text == "😀 djayelira [saŋ] ẋeyelira"
    assert asyncio.run(converter.atransliterate_detailed(source)) == result
