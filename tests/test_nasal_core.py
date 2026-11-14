import asyncio
import subprocess
import sys
import unicodedata
from dataclasses import replace

import pytest

import ce_translit
from ce_translit import NasalDecision, Transliterator
from ce_translit.errors import NasalAPIError, NasalResponseError


class Resolver:
    def __init__(self, kinds=("nasalization",)):
        self.kinds = kinds
        self.calls = []

    def resolve(self, text, targets):
        self.calls.append((text, targets))
        return tuple(
            NasalDecision(
                t.id,
                t.word,
                t.start,
                t.end,
                self.kinds[i % len(self.kinds)],
                "Context.",
            )
            for i, t in enumerate(targets)
        )

    async def aresolve(self, text, targets):
        await asyncio.sleep(0)
        return self.resolve(text, targets)


def test_offline_result_and_public_async_api():
    result = ce_translit.transliterate_detailed("сан, ШУН; бен!")
    assert result.text == "san, ŞUN; ben!"
    assert result.decisions == ()
    assert not result.ai_used
    assert asyncio.run(ce_translit.atransliterate("сан")) == "san"
    assert asyncio.run(
        ce_translit.atransliterate_detailed("сан")
    ) == ce_translit.transliterate_detailed("сан")


def test_repeated_homographs_have_distinct_decisions_and_source_offsets():
    resolver = Resolver(("nasalization", "consonant", "undetermined"))
    text = "😀 [шун], шун\r\nШУН!"
    result = Transliterator(nasal_resolver=resolver).transliterate_detailed(text)
    assert result.text == "😀 [şuŋ], şun\r\nŞUN!"
    assert result.ai_used
    assert [d.id for d in result.decisions] == ["N000001", "N000002", "N000003"]
    for decision in result.decisions:
        assert text[decision.start : decision.end] == decision.word
    assert len(resolver.calls) == 1


@pytest.mark.parametrize(
    "kind,letter", [("consonant", "n"), ("nasalization", "ŋ"), ("undetermined", "n")]
)
def test_case_marks_and_separators(kind, letter):
    text = "\u0301\tсаН\u0301, сан\u0301а; шун\u0301-сан\u0903\u00a0сан1"
    result = Transliterator(nasal_resolver=Resolver((kind,))).transliterate_detailed(
        text
    )
    assert result.text == unicodedata.normalize(
        "NFC",
        f"\u0301\tsa{letter.upper()}, sana; şu{letter}-sa{letter}\u00a0san1",
    )
    assert len(result.decisions) == 3


def test_non_targets_and_ai_disabled_do_not_call_resolver():
    resolver = Resolver()
    result = Transliterator(nasal_resolver=resolver).transliterate_detailed(
        "а! сан1 san; санна"
    )
    assert not result.ai_used
    assert not result.decisions
    assert not resolver.calls


def test_async_core_uses_async_resolver_only():
    class AsyncOnly(Resolver):
        def resolve(self, text, targets):
            raise AssertionError("Sync I/O was used.")

        async def aresolve(self, text, targets):
            await asyncio.sleep(0)
            return tuple(
                NasalDecision(t.id, t.word, t.start, t.end, "nasalization", "Context.")
                for t in targets
            )

    transliterator = Transliterator(nasal_resolver=AsyncOnly())
    assert asyncio.run(transliterator.atransliterate("сан сан")) == "saŋ saŋ"


@pytest.mark.parametrize(
    "kind,expected",
    [("consonant", "san"), ("nasalization", "saŋ"), ("undetermined", "san")],
)
def test_ai_final_n_overrides_single_and_multicharacter_custom_maps(kind, expected):
    mapping = {
        **Transliterator()._mapping,
        "н": "OTHER",
        "ан": "COMBINED",
        "сан": "WHOLE",
    }
    assert Transliterator(mapping=mapping).transliterate("сан") == "WHOLE"
    assert (
        Transliterator(mapping=mapping, nasal_resolver=Resolver((kind,))).transliterate(
            "сан"
        )
        == expected
    )


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "extra", "kind", "offset", "reason"]
)
def test_core_rejects_invalid_resolver_decisions(change):
    class Invalid(Resolver):
        def resolve(self, text, targets):
            rows = list(super().resolve(text, targets))
            if change == "missing":
                rows.pop()
            elif change == "duplicate":
                rows[1] = rows[0]
            elif change == "extra":
                rows.append(replace(rows[0], id="unexpected"))
            elif change == "kind":
                rows[0] = replace(rows[0], kind="wrong")
            elif change == "offset":
                rows[0] = replace(rows[0], start=100)
            else:
                rows[0] = replace(rows[0], reason=" ")
            return tuple(reversed(rows))

    with pytest.raises(NasalResponseError):
        Transliterator(nasal_resolver=Invalid()).transliterate("сан сан")


def test_failures_are_not_silently_converted_to_offline_text():
    class Broken(Resolver):
        def resolve(self, text, targets):
            raise NasalAPIError("Unavailable.")

    with pytest.raises(NasalAPIError):
        Transliterator(nasal_resolver=Broken()).transliterate("сан")


def test_core_does_not_import_or_activate_sdk_even_with_environment_keys():
    script = """
import os
import sys
os.environ['GEMINI_API_KEY'] = 'must-not-activate'
os.environ['GOOGLE_GENAI_USE_VERTEXAI'] = 'true'
import ce_translit
assert ce_translit.transliterate('сан') == 'san'
assert not any(name == 'httpx' or name.startswith('google.genai') for name in sys.modules)
"""
    subprocess.run([sys.executable, "-c", script], check=True)


def test_removed_word_lists_are_not_accepted():
    with pytest.raises(TypeError):
        Transliterator(blacklist=["сан"])
    with pytest.raises(TypeError):
        Transliterator(unsurelist=["сан"])


def test_custom_mapping_is_a_defensive_snapshot():
    mapping = {"с": "s", "а": "a", "н": "n"}
    transliterator = Transliterator(mapping)
    mapping["н"] = "changed"
    assert transliterator.transliterate("сан") == "san"


def test_custom_resolver_can_honestly_omit_reasons_in_sync_and_async():
    class Compact(Resolver):
        def resolve(self, text, targets):
            return tuple(
                NasalDecision(t.id, t.word, t.start, t.end, "nasalization")
                for t in targets
            )

    converter = Transliterator(nasal_resolver=Compact())
    result = converter.transliterate_detailed("са\u0301н")
    assert result.text == "saŋ"
    assert result.decisions[0].reason is None
    assert asyncio.run(converter.atransliterate_detailed("са\u0301н")) == result


@pytest.mark.parametrize("reason", ["", " ", 0, False, [], {}])
def test_core_rejects_invalid_present_reasons(reason):
    class Invalid(Resolver):
        def resolve(self, text, targets):
            return tuple(
                replace(d, reason=reason) for d in super().resolve(text, targets)
            )

    with pytest.raises(NasalResponseError):
        Transliterator(nasal_resolver=Invalid()).transliterate("сан")
