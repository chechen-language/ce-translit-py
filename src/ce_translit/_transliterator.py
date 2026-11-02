"""Core transliteration logic for the ce_translit package."""

import json
import unicodedata
from collections.abc import Mapping
from importlib import resources
from typing import Final

from ce_translit._models import (
    NasalDecision,
    NasalResolver,
    NasalTarget,
    TransliterationResult,
)
from ce_translit._tokenizer import _final_n_index, _iter_word_tokens, _without_marks
from ce_translit.errors import NasalResponseError

# Constants for data file
_DATA_FILE: Final[str] = "cyrl_latn_map.json"

# Load default mapping at import time
with (
    resources.files("ce_translit.data")
    .joinpath(_DATA_FILE)
    .open(encoding="utf-8") as fh
):
    _DEFAULT_DATA: Final[dict] = json.load(fh)

DEFAULT_MAPPING: Final[Mapping[str, str]] = _DEFAULT_DATA["mapping"]


class Transliterator:
    """Transliterate Chechen text from Cyrillic to Latin script using the Chechen Latin alphabet.

    An optional resolver classifies each final Cyrillic n in its source context.
    Without a resolver, only the character mapping is used.
    """

    def __init__(
        self,
        mapping: Mapping[str, str] | None = None,
        *,
        nasal_resolver: NasalResolver | None = None,
    ) -> None:
        """Initialize the transliterator with custom or default configuration.

        Args:
            mapping: Custom cyrillic-to-latin mapping. If None, uses default.
            nasal_resolver: Optional context resolver. No implicit AI activation.
        """
        self._mapping = mapping if mapping is not None else DEFAULT_MAPPING
        self._nasal_resolver = nasal_resolver

    def _transliterate_word(
        self, word: str, decision: NasalDecision | None = None
    ) -> str:
        """Convert a single word from Cyrillic to Latin script.

        Args:
            word: A single word in Cyrillic script.

        Returns:
            The word transliterated to Latin script.
        """
        base_word = _without_marks(word)
        if base_word in ("а", "А"):
            replacement = "ə" if base_word == "а" else "Ə"
            return unicodedata.normalize("NFC", replacement + word[1:])

        final_letter = _final_n_index(word) if decision is not None else None
        result = ""
        i = 0

        while i < len(word):
            match = None

            if decision is not None and final_letter is not None and i == final_letter:
                letter = "ŋ" if decision.kind == "nasalization" else "n"
                if word[i].isupper():
                    letter = letter.upper()
                result += letter + word[i + 1 :]
                break

            has_next_letter = i + 1 < len(word)
            next_letter = word[i + 1] if has_next_letter else ""
            has_pre_letter = i > 0
            pre_letter = word[i - 1] if has_pre_letter else ""

            # Check all case variations (3 chars, 2 chars, 1 char)
            for key in [
                word[i : i + 3],
                word[i : i + 2],
                word[i : i + 1],
            ]:
                match_length = len(key)
                # A custom multi-character map cannot consume the AI-controlled n.
                if final_letter is not None and i + match_length > final_letter:
                    continue
                # Handle 'ъ' and 'Ъ' before 'е', 'ё', 'ю', 'я' and their uppercase versions
                # The lower() method is used to ensure the comparison is case-insensitive.
                if (
                    key.lower() == "ъ"
                    and has_next_letter
                    and next_letter.lower() in "еёюя"
                ):
                    if has_pre_letter and pre_letter.lower() == "к":  # and after 'к'
                        match = "q̇" if key.islower() else "Q̇"  # match to 'къ'
                    else:
                        match = ""  # else skip 'ъ'
                elif key.lower() == "е":
                    # 'е' can be 'ye' or 'e' depending on context
                    if i == 0:  # if 'е' is at the start of the word
                        # match to 'ye' if the next letter is uppercase or if there is no next letter but previous letter is uppercase
                        match = (
                            "ye"
                            if key.islower()
                            else (
                                "YE"
                                if has_next_letter
                                and next_letter.isupper()
                                or not has_next_letter
                                and has_pre_letter
                                and pre_letter.isupper()
                                else "Ye"
                            )
                        )
                    elif (
                        has_pre_letter
                        and pre_letter.lower() == "ъ"
                        and (i < 2 or word[i - 2 : i].lower() != "къ")
                    ):
                        # after 'ъ' but not after 'къ'
                        # match to 'ye' if the next letter is uppercase or if there is no next letter but previous letter is uppercase
                        match = (
                            "ye"
                            if key.islower()
                            else (
                                "YE"
                                if has_next_letter
                                and next_letter.isupper()
                                or not has_next_letter
                                and has_pre_letter
                                and pre_letter.isupper()
                                else "Ye"
                            )
                        )
                    else:
                        match = self._mapping.get(
                            key
                        )  # regular transliteration for 'е'
                else:
                    match = self._mapping.get(
                        key
                    )  # regular transliteration for other characters

                if match is not None:
                    result += match
                    i += match_length
                    break

            if match is None:
                result += word[i]
                i += 1

        # Normalize to NFC form for proper character composition
        return unicodedata.normalize("NFC", result)

    def transliterate(self, text: str) -> str:
        """Convert full text from Cyrillic to Latin script.

        Handles special cases like standalone 'а' → 'ə' and applies
        word-by-word transliteration, preserving separators exactly.

        Args:
            text: Text in Cyrillic script to transliterate.

        Returns:
            Text transliterated to Latin script.
        """
        return self.transliterate_detailed(text).text

    def _targets(self, text: str) -> tuple[NasalTarget, ...]:
        return tuple(
            NasalTarget(f"N{index:06d}", token.text, token.start, token.end)
            for index, token in enumerate(
                (
                    token
                    for token in _iter_word_tokens(text)
                    if _final_n_index(token.text) is not None
                ),
                start=1,
            )
        )

    def _render(
        self,
        text: str,
        targets: tuple[NasalTarget, ...],
        decisions: tuple[NasalDecision, ...],
    ) -> TransliterationResult:
        by_id = {}
        expected = {target.id: target for target in targets}
        for decision in decisions:
            if not isinstance(decision, NasalDecision):
                raise NasalResponseError(
                    "Resolver returned invalid occurrence decisions."
                )
            target = expected.get(decision.id)
            if (
                target is None
                or decision.id in by_id
                or (decision.word, decision.start, decision.end)
                != (target.word, target.start, target.end)
                or decision.kind not in ("consonant", "nasalization", "undetermined")
                or not isinstance(decision.reason, str)
                or not decision.reason.strip()
            ):
                raise NasalResponseError(
                    "Resolver returned invalid occurrence decisions."
                )
            by_id[decision.id] = decision
        if by_id.keys() != expected.keys():
            raise NasalResponseError(
                "Resolver did not resolve every requested occurrence."
            )
        ordered = tuple(by_id[target.id] for target in targets)
        by_start = {decision.start: decision for decision in ordered}
        parts = []
        end = 0
        for token in _iter_word_tokens(text):
            parts.append(text[end : token.start])
            parts.append(
                self._transliterate_word(token.text, by_start.get(token.start))
            )
            end = token.end
        parts.append(text[end:])
        return TransliterationResult("".join(parts), bool(targets), ordered)

    def transliterate_detailed(self, text: str) -> TransliterationResult:
        """Return source-indexed decisions; unresolved occurrences retain n/N."""
        if self._nasal_resolver is None:
            return self._render(text, (), ())
        targets = self._targets(text)
        decisions = self._nasal_resolver.resolve(text, targets) if targets else ()
        return self._render(text, targets, decisions)

    async def atransliterate(self, text: str) -> str:
        """Asynchronously resolve nasal occurrences, without blocking network I/O."""
        return (await self.atransliterate_detailed(text)).text

    async def atransliterate_detailed(self, text: str) -> TransliterationResult:
        if self._nasal_resolver is None:
            return self._render(text, (), ())
        targets = self._targets(text)
        decisions = (
            await self._nasal_resolver.aresolve(text, targets) if targets else ()
        )
        return self._render(text, targets, decisions)
