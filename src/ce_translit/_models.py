"""Transport-independent nasal decisions and transliteration results."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

NasalKind = Literal["consonant", "nasalization", "undetermined"]


@dataclass(frozen=True)
class NasalTarget:
    """One occurrence, with half-open code-point offsets in the source text."""

    id: str
    word: str
    start: int
    end: int


@dataclass(frozen=True)
class NasalDecision(NasalTarget):
    kind: NasalKind
    reason: str


@dataclass(frozen=True)
class TransliterationResult:
    text: str
    ai_used: bool
    decisions: tuple[NasalDecision, ...] = ()


class NasalResolver(Protocol):
    """The core depends on this contract, not an AI SDK."""

    def resolve(
        self, text: str, targets: Sequence[NasalTarget]
    ) -> tuple[NasalDecision, ...]: ...

    async def aresolve(
        self, text: str, targets: Sequence[NasalTarget]
    ) -> tuple[NasalDecision, ...]: ...
