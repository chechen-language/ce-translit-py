import unicodedata

import pytest

import ce_translit
from ce_translit import Transliterator
from ce_translit._transliterator import _iter_word_tokens


@pytest.mark.parametrize(
    "separator",
    [
        "",
        ",",
        ".",
        "!",
        "?",
        ":",
        ";",
        "…",
        "—",
        "-",
        "'",
        '"',
        "(",
        ")",
        "[",
        "]",
        "_",
        "\u00a0",
        "\t",
        "\r\n",
        "😀",
    ],
)
def test_final_n_at_separator_boundaries(separator):
    assert ce_translit.transliterate(f"{separator}сан{separator}") == (
        f"{separator}san{separator}"
    )


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("Сан", "San"),
        ("САН", "SAN"),
        ("сАн", "sAn"),
        ("саН", "saN"),
        ("хан", "xan"),
        ("ДИН", "DIN"),
        ("гӏан", "ġan"),
        ("ГӀаН", "ĠaN"),
        ("шун", "şun"),
        ("БЕН", "BEN"),
        ("ШуН", "ŞuN"),
    ],
)
def test_punctuation_does_not_hide_case(word, expected):
    assert ce_translit.transliterate(f'("{word}"),') == f'("{expected}"),'


def test_word_initial_e_after_punctuation_and_internal_hard_sign():
    assert ce_translit.transliterate("'елла'-(Елла)[ЕЛЛА]_е, шелъелча; къе") == (
        "'yella'-(Yella)[YELLA]_ye, şelyelça; q̇e"
    )


def test_singleton_a_at_lexical_boundaries():
    assert ce_translit.transliterate("(а), 'А'; а-А_а. ба аб") == (
        "(ə), 'Ə'; ə-Ə_ə. ba ab"
    )


def test_whitespace_and_emoji_are_preserved_exactly():
    text = " \t\u00a0сан,  хан\r\n\tшун\n\nа 👩🏽\u200d💻\ufe0f \r\n"
    expected = " \t\u00a0san,  xan\r\n\tşun\n\nə 👩🏽\u200d💻\ufe0f \r\n"
    assert ce_translit.transliterate(text) == expected


@pytest.mark.parametrize(
    "text", ["", " \t\r\n\n\u00a0 ", "[]-'_,.!", "👩🏽\u200d💻\ufe0f", "\u0301\u0327"]
)
def test_empty_and_non_word_inputs_are_unchanged(text):
    assert ce_translit.transliterate(text) == text


def test_combining_marks_stay_attached_and_only_word_output_is_nfc():
    text = "\u0301 а\u0301 (А\u0301) e\u0301 а,\u0301\u0327"
    assert (
        ce_translit.transliterate(text) == "\u0301 ə\u0301 (Ə\u0301) é ə,\u0301\u0327"
    )
    # Decomposed input is mapped as supplied, not normalized into 'й' first.
    assert ce_translit.transliterate("и\u0306 й") == "ĭ y"


@pytest.mark.parametrize("mark", ["\u0301", "\u0903", "\u20dd"])
def test_all_unicode_mark_categories_stay_inside_word_tokens(mark):
    text = f"(а{mark})"
    tokens = list(_iter_word_tokens(text))
    assert [(token.text, token.start, token.end) for token in tokens] == [
        (f"а{mark}", 1, 3),
    ]
    assert ce_translit.transliterate(text) == unicodedata.normalize("NFC", f"(ə{mark})")


@pytest.mark.parametrize("marks", ["\u0301", "\u0903", "\u20dd", "\u0301\u0327"])
@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("сан", "san"),
        ("САН", "SAN"),
        ("саН", "saN"),
        ("хан", "xan"),
        ("ДИН", "DIN"),
        ("ГӀаН", "ĠaN"),
        ("шун", "şun"),
        ("ШуН", "ŞuN"),
    ],
)
def test_final_n_rules_preserve_attached_marks(word, expected, marks):
    assert ce_translit.transliterate(f"({word}{marks}),") == unicodedata.normalize(
        "NFC", f"({expected}{marks}),"
    )


def test_marks_on_any_letter_are_preserved_without_normalizing_input():
    assert ce_translit.transliterate("ха\u0301н, гӏа\u0301н, шу\u0301н\u0301!") == (
        "xán, ġán, şúń!"
    )


@pytest.mark.parametrize("marks", ["\u0301", "\u0903", "\u20dd", "\u0301\u0327"])
@pytest.mark.parametrize(("letter", "expected"), [("а", "ə"), ("А", "Ə")])
def test_singleton_a_uses_base_letters_and_preserves_marks(letter, expected, marks):
    transliterator = Transliterator(mapping={"а": "o", "А": "O"})
    assert transliterator.transliterate(f"[{letter}{marks}]") == unicodedata.normalize(
        "NFC", f"[{expected}{marks}]"
    )


def test_marks_do_not_hide_additional_base_letters_or_digits():
    assert ce_translit.transliterate("сан\u0301а а\u0301а а\u03011 сан\u03011") == (
        "sańa áa á1 sań1"
    )


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("гӏ", "ġ"),
        ("гӀ", "ġ"),
        ("Ӏ", "J"),
        ("ӏ", "j"),
        ("ггӏ", "ġġ"),
        ("ттӀ", "ṫṫ"),
        ("ккъ", "q̇q̇"),
        ("ххь", "ẋẋ"),
    ],
)
def test_palochka_and_longest_matches_with_punctuation(word, expected):
    assert ce_translit.transliterate(f"[{word}]") == unicodedata.normalize(
        "NFC", f"[{expected}]"
    )


def test_hyphens_delimit_words_initial_e_and_singleton_a():
    assert ce_translit.transliterate("ду-кх сан-хан-шун-елла-а") == (
        "du-q san-xan-şun-yella-ə"
    )


def test_digits_and_mixed_scripts_do_not_create_artificial_word_boundaries():
    assert ce_translit.transliterate(
        "г1ан 1аж 1 а1 1а а2 2е aе aсан Latin еLatin сан1"
    ) == ("g1an 1aƶ 1 a1 1a a2 2e ae asan Latin yeLatin san1")
    assert ce_translit.transliterate("а٢ ٢е") == "a٢ ٢e"


def test_unicode_letters_not_just_ascii_or_cyrillic_are_word_characters():
    assert ce_translit.transliterate("éе 漢е ӏе") == "ée 漢e je"


def test_custom_mapping_applies_to_words_not_separators():
    transliterator = Transliterator(
        mapping={
            "бба": "LONG",
            "бб": "PAIR",
            "б": "v",
            "а": "o",
            "1": "j",
            "a\u0301": "accent",
            "-": "BAD",
            "_": "BAD",
            " ": "BAD",
            "😀": "BAD",
            "б-б": "BAD",
        }
    )
    assert transliterator.transliterate("\tбба-бб_ба 1аж a\u0301 😀\r\nа") == (
        "\tLONG-PAIR_vo joж accent 😀\r\nə"
    )


def test_internal_tokens_keep_original_half_open_code_point_offsets():
    text = "😀\t(Сан)-а\u0301_гӀан\r\n1аж aе\u00a0\u0301!"
    tokens = list(_iter_word_tokens(text))
    assert [(token.text, token.start, token.end) for token in tokens] == [
        ("Сан", 3, 6),
        ("а\u0301", 8, 10),
        ("гӀан", 11, 15),
        ("1аж", 17, 20),
        ("aе", 21, 23),
    ]
    parts = []
    end = 0
    for token in tokens:
        assert text[token.start : token.end] == token.text
        parts.extend([text[end : token.start], token.text])
        end = token.end
    parts.append(text[end:])
    assert "".join(parts) == text


def test_mark_aware_word_rules_keep_original_token_offsets():
    text = "\t😀[сан\u0301],\r\nа\u0301"
    before = list(_iter_word_tokens(text))
    assert [(token.text, token.start, token.end) for token in before] == [
        ("сан\u0301", 3, 7),
        ("а\u0301", 11, 13),
    ]
    assert ce_translit.transliterate(text) == "\t😀[sań],\r\nə\u0301"
    assert list(_iter_word_tokens(text)) == before
    for token in before:
        assert text[token.start : token.end] == token.text
