# Chechen Transliterator

[![PyPI](https://img.shields.io/pypi/v/ce-translit.svg)](https://pypi.org/project/ce-translit/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

`ce-translit` converts Chechen text from Cyrillic to the Chechen Latin alphabet. It combines a deterministic transliteration engine with optional AI-powered **nasalization disambiguation**: the appropriate Latin spelling is selected from each word's meaning and grammatical role in context.

- Chechen-specific character combinations and positional spelling rules.
- Contextual nasalization analysis with Gemini.
- Preserved case, punctuation, whitespace and Unicode combining marks.
- Synchronous and asynchronous APIs with per-occurrence linguistic decisions.

Requires Python 3.10 or later.

## Installation

```bash
pip install ce-translit
```

For AI-powered nasalization:

```bash
pip install 'ce-translit[ai]'
```

## Quick Start

```python
import ce_translit

text = ce_translit.transliterate("Нохчийн мотт")
print(text)  # Noxçiyn mott
```

Basic transliteration runs locally with the standard character mapping, including `н → n`. The core has no third-party runtime dependencies.

## Contextual Nasalization

Chechen homographs can share a Cyrillic spelling while differing in meaning and pronunciation:

| Cyrillic | Meaning | Latin |
| --- | --- | --- |
| шун | your | şuŋ |
| шун | table / tray | şun |
| бен | only / except | beŋ |
| бен | nest / den | ben |

The nasalization resolver uses the surrounding text to distinguish these readings. Each occurrence is analysed separately, including repeated words. In the adopted Latin orthography, `ŋ` denotes vowel nasalization; `n` represents the pronounced consonant.

### Configuration

The examples read these environment variables:

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | API key for the configured service. |
| `GEMINI_MODEL` | Model name available on that service. |
| `GEMINI_BASE_URL` | Optional service root for a Gemini-compatible endpoint. |

With `GEMINI_BASE_URL` unset, the resolver connects to Google's Gemini API. Set it to your service root to use a Gemini-compatible gateway such as CLIProxyAPI. The endpoint must support Gemini's `generateContent` protocol under `/v1beta`.

### Usage

```python
import os

from ce_translit import Transliterator
from ce_translit.ai import GeminiNasalResolver

with GeminiNasalResolver(
    api_key=os.environ["GEMINI_API_KEY"],
    model=os.environ["GEMINI_MODEL"],
    base_url=os.environ.get("GEMINI_BASE_URL"),
) as resolver:
    transliterator = Transliterator(nasal_resolver=resolver)
    result = transliterator.transliterate_detailed("цхьа стаг бен вацар арахь")
    print(result.text)  # cẋa stag beŋ vacar araẋ
```

The resolver uses the [Google GenAI SDK](https://github.com/googleapis/python-genai). Reuse it across conversions within the `with` block; the context manager closes its network resources on exit.

### Async Usage

```python
import os

from ce_translit import Transliterator
from ce_translit.ai import GeminiNasalResolver

async def transliterate_texts(texts: list[str]) -> list[str]:
    async with GeminiNasalResolver(
        api_key=os.environ["GEMINI_API_KEY"],
        model=os.environ["GEMINI_MODEL"],
        base_url=os.environ.get("GEMINI_BASE_URL"),
    ) as resolver:
        transliterator = Transliterator(nasal_resolver=resolver)
        return [await transliterator.atransliterate(text) for text in texts]
```

For a long-running application, keep one resolver open for its lifecycle and close it during shutdown. Asynchronous use requires `async with` or `await resolver.aclose()`.

## API And Results

| `Transliterator` method | Returns |
| --- | --- |
| `transliterate(text)` | Latin text as `str`. |
| `transliterate_detailed(text)` | `TransliterationResult` with text and decisions. |
| `await atransliterate(text)` | Latin text as `str`. |
| `await atransliterate_detailed(text)` | `TransliterationResult` with text and decisions. |

The module-level functions with these names provide basic transliteration. Use a `Transliterator` instance with a resolver for contextual nasalization. For a custom alphabet, pass a character mapping to `Transliterator(mapping=...)`; it replaces the default mapping.

### Detailed Results

`TransliterationResult` contains `text`, `ai_used` and an ordered tuple of `decisions`. The `ai_used` flag indicates whether AI was used for the conversion. Using the result from the example above:

```python
for decision in result.decisions:
    print(decision.word, decision.kind, decision.reason)
```

Each `NasalDecision` contains `id`, `word`, `start`, `end`, `kind` and `reason`. Source spans are half-open Python code-point offsets: `source[decision.start:decision.end] == decision.word`. Repeated words have separate IDs, local to the conversion.

| Decision kind | Rendering |
| --- | --- |
| `consonant` | `n/N` |
| `nasalization` | `ŋ/Ŋ` |
| `undetermined` | `n/N`, with the unresolved reading recorded in the decision. |

Use detailed results when your application needs to inspect uncertainty. AI predictions remain subject to linguistic error.

### Requests And Errors

Long texts are sent to Gemini in sequential batches. Each batch contains at most 64 word occurrences to resolve, drawn from a source span of up to 12,000 characters. Up to 2,000 characters of surrounding text are added on each side to help interpret those words. Context can overlap between batches, but each occurrence is resolved in exactly one batch.

The default timeout is 60 seconds per request attempt, configurable through `GeminiNasalResolver(timeout=...)`. Temporary network and API failures receive up to two retries.

Failures raise exceptions from `ce_translit.errors`:

| Exception | Meaning |
| --- | --- |
| `NasalAPIError` | A network or provider request failed; `status_code` is available for API errors. |
| `NasalResponseError` | The response was blocked, truncated or failed decision validation. |
| `NasalInputError` | An input occurrence exceeds the context limits. |

These inherit from `NasalResolutionError`. A failed conversion raises an exception rather than returning partially processed text.

AI processing sends source context to the configured provider and consumes its API quota. Review the provider's pricing and data-handling terms before processing sensitive texts.

## Text Handling

Words consist of Unicode letters, decimal digits and attached combining marks. Hyphens, quotes, brackets and underscores delimit words; contiguous mixed-script text forms one word. Whitespace, punctuation and emoji retain their original positions among the transformed words.

Input is mapped as supplied. Word outputs are normalized to NFC, and separators are preserved exactly. Digits remain literal unless explicitly mapped.

## Development

```bash
hatch run test
hatch run ai:test
hatch build
```

The test suite covers transliteration rules, Unicode boundaries, occurrence tracking, context windows and mocked Gemini requests. Live evaluations compare predictions against native-speaker-reviewed fixtures and produce a per-occurrence report.

With the Gemini environment variables configured, run a live evaluation:

```bash
CE_TRANSLIT_API_KEY="$GEMINI_API_KEY" \
CE_TRANSLIT_MODEL="$GEMINI_MODEL" \
CE_TRANSLIT_BASE_URL="${GEMINI_BASE_URL:-}" \
hatch run ai:test tests/test_live_gemini.py --run-live-nasal \
  --nasal-report "/tmp/nasal-review-$(date +%s).md" -v
```

Live evaluations send the fixture texts to the provider. Reports include source context, model decisions, reference labels and explanations.

## License

[MIT](LICENSE). Maintained by [Chechen Language](https://github.com/chechen-language).
