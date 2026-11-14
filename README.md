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
| `GEMINI_API_KEY` | API key for the configured service, or a non-empty placeholder for an unauthenticated gateway. |
| `GEMINI_MODEL` | Model name available on that service. |
| `GEMINI_BASE_URL` | Optional service root for a Gemini-compatible endpoint. |
| `GEMINI_THINKING_LEVEL` | Reasoning level for the examples, defaulting to `low`: `minimal`, `low`, `medium`, `high`, or `xhigh`. |

With `GEMINI_BASE_URL` unset, the resolver connects to Google's Gemini API. Set it to your service root to use a Gemini-compatible gateway such as CLIProxyAPI. The endpoint must support Gemini's `generateContent` protocol under `/v1beta`.

The same client works with both services: change only `base_url`, `model` and `api_key`. The resolver requires a non-empty key; for a gateway without client authentication, set `GEMINI_API_KEY` to a placeholder such as `local-gateway`. Google's Gemini API requires a valid key. Set `thinking_level` independently of the model name. Supported levels depend on the selected model and service.

The examples use adjacent-sentence context and `low` reasoning, with an environment override for the reasoning level. The resolver's constructor defaults remain `context="sentence"` and `thinking_level=None`; omitting the reasoning argument or passing `None` uses the provider's default.

### Usage

```python
import os

from ce_translit import Transliterator
from ce_translit.ai import GeminiNasalResolver

with GeminiNasalResolver(
    api_key=os.environ["GEMINI_API_KEY"],
    model=os.environ["GEMINI_MODEL"],
    base_url=os.environ.get("GEMINI_BASE_URL") or None,
    context="adjacent",
    thinking_level=os.environ.get("GEMINI_THINKING_LEVEL") or "low",
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
        base_url=os.environ.get("GEMINI_BASE_URL") or None,
        context="adjacent",
        thinking_level=os.environ.get("GEMINI_THINKING_LEVEL") or "low",
    ) as resolver:
        transliterator = Transliterator(nasal_resolver=resolver)
        return [await transliterator.atransliterate(text) for text in texts]
```

For a long-running application, keep one resolver open for its lifecycle and close it during shutdown. Asynchronous use requires `async with` or `await resolver.aclose()`, in the same event loop that uses the resolver. Finish or cancel and await pending conversions before closing. Synchronous conversions can share a resolver across threads; a resolver used asynchronously must be closed asynchronously.

## API And Results

| `Transliterator` method | Returns |
| --- | --- |
| `transliterate(text)` | Latin text as `str`. |
| `transliterate_detailed(text)` | `TransliterationResult` with text and decisions. |
| `await atransliterate(text)` | Latin text as `str`. |
| `await atransliterate_detailed(text)` | `TransliterationResult` with text and decisions. |

The module-level functions with these names provide basic transliteration. Use a `Transliterator` instance with a resolver for contextual nasalization. For a custom alphabet, pass a character mapping to `Transliterator(mapping=...)`; it replaces the default mapping and determines the multi-character units recognized by positional rules.

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

Each occurrence is analysed in its complete sentence. Multiple independent sentence contexts can share one request; sentences without target occurrences are not sent. Set `context="adjacent"` on `GeminiNasalResolver` to include the previous and next sentence explicitly. An unresolved reading does not trigger hidden follow-up requests.

Sentence boundaries use Unicode UAX #29 with tailoring for single-line wraps, paragraph breaks, initials, common Russian abbreviations and web addresses. Single line breaks may remain inside a sentence; blank lines separate fragments. Unpunctuated input is treated as a fragment. Plain-text sentence boundaries can be ambiguous; the library does not infer missing punctuation.

Requests are packed sequentially with configurable `max_targets_per_request=64` and `max_context_chars=12000`. The character limit applies to the sum of source contexts in one request, not JSON overhead or provider tokens. If a sentence contains more target occurrences than fit in one request, its full context is repeated with disjoint target lists. If a complete context exceeds the character limit, conversion raises `NasalInputError` before any request; increase the limit for that input. Contexts are never truncated.

The default timeout is 60 seconds per request attempt, configurable through `GeminiNasalResolver(timeout=...)`. Temporary network and API failures receive up to two retries. Provider `Retry-After` delays are honoured; delays above the 60-second automatic wait limit raise `NasalAPIError` with `retry_after` instead of retrying early. HTTPX environment proxy settings apply to both sync and async calls. HTTP redirects are rejected without forwarding credentials or text to another address.

Failures raise exceptions from `ce_translit.errors`:

| Exception | Meaning |
| --- | --- |
| `NasalAPIError` | A network or provider request failed; `status_code` is available for API errors. |
| `NasalResponseError` | The response was blocked, truncated or failed decision validation. |
| `NasalInputError` | A complete context exceeds the configured limit or occurrence spans are invalid. |
| `NasalLifecycleError` | The resolver is closed, used from a different event loop, or closed with operations still running. |

These inherit from `NasalResolutionError`. A failed conversion raises an exception rather than returning partially processed text.

AI processing sends source context to the configured provider and consumes its API quota. Review the provider's pricing and data-handling terms before processing sensitive texts.

## Text Handling

Words consist of Unicode letters, decimal digits and attached combining marks. Hyphens, quotes, brackets and underscores delimit words; contiguous mixed-script text forms one word. Whitespace, punctuation and emoji retain their original positions among the transformed words.

The letter `е` becomes `ye` at the start of a word or after a separating `ъ` or `ь`: `елла → yella`, `шелъелча → şelyelça`, `шельелла → şelyella`. Signs consumed as part of mapped letters, such as `къ` and `хь`, do not act as separators.

Input is mapped as supplied. Word outputs are normalized to NFC, and separators are preserved exactly. Digits remain literal unless explicitly mapped.

## Development

```bash
hatch run test
hatch run ai:test
hatch build
```

The offline test suite covers transliteration rules, Unicode boundaries, sentence contexts, occurrence tracking and SDK requests to local HTTP servers. It requires neither a provider key nor access to a Gemini endpoint. CI runs the core, optional AI dependencies and minimum supported SDK versions separately. Live evaluations compare `sentence` and `adjacent` modes on 93 previously native-speaker-reviewed positions, reporting every detected occurrence, per-class results, HTTP attempts, elapsed time and provider-reported token usage. Unlabelled occurrences are shown but not scored; missing usage is reported as unknown. These previously reviewed samples are not an independent estimate of linguistic accuracy.

With the Gemini environment variables configured, run a live evaluation:

```bash
CE_TRANSLIT_API_KEY="$GEMINI_API_KEY" \
CE_TRANSLIT_MODEL="$GEMINI_MODEL" \
CE_TRANSLIT_BASE_URL="${GEMINI_BASE_URL:-}" \
CE_TRANSLIT_THINKING_LEVEL="${GEMINI_THINKING_LEVEL:-low}" \
hatch run ai:test tests/test_live_gemini.py --run-live-nasal \
  --nasal-report "/tmp/nasal-review-$(date +%s).md" -v
```

Live evaluations send the fixture texts to the provider. Reports include source context, model decisions, reference labels and explanations.

## License

[MIT](LICENSE). Maintained by [Chechen Language](https://github.com/chechen-language).
