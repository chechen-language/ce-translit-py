import asyncio
import unicodedata

import pytest

from ce_translit import NasalDecision, Transliterator, transliterate


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("де\u0301", "de"),
        ("е\u0301", "ye"),
        ("ѐ ѝ", "ye i"),
        ("ё й е\u0308 и\u0306", "ö y ö y"),
        ("е\u0301\u0308 и\u0301\u0306", "ö y"),
        ("х\u0301ь г\u0301ӏ к\u0301ъ у\u0301ь", "ẋ ġ q̇ ü"),
        ("к\u0301ъе", "q̇e"),
        ("чекхъ\u0301е\u0301ли", "çeqyeli"),
        ("ö ü ẋ ġ q̇ e\u0301", "ö ü ẋ ġ q̇ é"),
    ],
)
def test_source_annotations_do_not_change_letters_or_target_diacritics(
    source, expected
):
    assert transliterate(source) == unicodedata.normalize("NFC", expected)
    assert asyncio.run(
        Transliterator().atransliterate(source)
    ) == unicodedata.normalize("NFC", expected)


def test_custom_map_applies_after_annotation_removal_and_preserves_its_output():
    converter = Transliterator({"гӏ": "ġ\u0301", "е\u0308": "EXPLICIT", "ё": "OTHER"})
    assert converter.transliterate("г\u0301ӏ е\u0308\u0301") == "ġ\u0301 EXPLICIT"


def test_annotation_removal_keeps_original_resolver_text_words_and_offsets():
    source = "😀 и\u0306\u0301 [са\u0301н\u0301] сан"

    class Resolver:
        def resolve(self, text, targets):
            assert text == source
            assert [t.word for t in targets] == ["са\u0301н\u0301", "сан"]
            assert all(text[t.start : t.end] == t.word for t in targets)
            return tuple(
                NasalDecision(t.id, t.word, t.start, t.end, "nasalization", "Fixture.")
                for t in targets
            )

        async def aresolve(self, text, targets):
            return self.resolve(text, targets)

    converter = Transliterator(nasal_resolver=Resolver())
    result = converter.transliterate_detailed(source)
    assert result.text == "😀 y [saŋ] saŋ"
    assert asyncio.run(converter.atransliterate_detailed(source)) == result


CYRILLIC_CANONICAL_LETTERS = [
    chr(code)
    for code in range(0x400, 0x530)
    if unicodedata.decomposition(chr(code))
    and not unicodedata.decomposition(chr(code)).startswith("<")
]


@pytest.mark.parametrize("letter", CYRILLIC_CANONICAL_LETTERS)
def test_actual_cyrillic_letters_keep_canonical_identity(letter):
    assert transliterate(letter) == transliterate(unicodedata.normalize("NFD", letter))


def test_unsupported_structural_letters_are_not_guessed_as_latin():
    assert transliterate("ӓ ӧ ӱ ӣ ӯ") == "ӓ ӧ ӱ ӣ ӯ"
    assert transliterate("а\u0308 о\u0308 у\u0308 и\u0304 у\u0304") == "ӓ ӧ ӱ ӣ ӯ"
