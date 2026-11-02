"""Chechen Cyrillic-to-Latin transliteration with optional context resolution."""

from importlib.metadata import version

from ce_translit._models import (
    NasalDecision,
    NasalKind,
    NasalTarget,
    TransliterationResult,
)
from ce_translit._transliterator import Transliterator

__version__ = version("ce-translit")
_default_transliterator = Transliterator()


def transliterate(text: str) -> str:
    """Transliterate offline. Default final Cyrillic n is always n/N."""
    return _default_transliterator.transliterate(text)


def transliterate_detailed(text: str) -> TransliterationResult:
    return _default_transliterator.transliterate_detailed(text)


async def atransliterate(text: str) -> str:
    return await _default_transliterator.atransliterate(text)


async def atransliterate_detailed(text: str) -> TransliterationResult:
    return await _default_transliterator.atransliterate_detailed(text)


__all__ = [
    "Transliterator",
    "TransliterationResult",
    "NasalDecision",
    "NasalTarget",
    "NasalKind",
    "transliterate",
    "transliterate_detailed",
    "atransliterate",
    "atransliterate_detailed",
]
