<h1 align="center">Chechen Transliterator</h1>

<p align="center">
  <a href="https://pypi.org/project/ce-translit/"><img src="https://img.shields.io/pypi/v/ce-translit.svg" alt="PyPI"></a>
</p>

`ce-translit` converts Chechen Cyrillic to the Chechen Latin alphabet. Offline conversion is deterministic, preserves punctuation and whitespace, and has no third-party runtime dependencies. An optional Gemini resolver distinguishes nasalized and consonantal readings of final `н` using context.

| Cyrillic input | Offline output |
| --- | --- |
| Нохчийн мотт | Noxçiyn mott |
| Со цунах хӏинца шекьяьлла | So cunax hinca şekyälla |
| Арахь чӏогӏа шелъелла вайна | Araẋ ç̇oġa şelyella vayna |

Requires Python 3.10 or later.

## Installation

Install with [uv](https://docs.astral.sh/uv/) or pip:

```bash
uv add ce-translit        # or: pip install ce-translit
```

## Quick Start

```python
from ce_translit import transliterate

print(transliterate("Нохчийн мотт"))  # Noxçiyn mott
```

Offline conversion uses the standard character mapping, including `н → n`.

## API And Results

| Function or `Transliterator` method | Returns |
| --- | --- |
| `transliterate(text)` | Latin text as `str`. |
| `transliterate_detailed(text)` | `TransliterationResult` with text and decisions. |
| `await atransliterate(text)` | Latin text as `str`. |
| `await atransliterate_detailed(text)` | `TransliterationResult` with text and decisions. |

Module-level functions provide offline conversion. Use a `Transliterator(nasal_resolver=...)` instance for contextual nasalization. For a custom alphabet, `Transliterator(mapping=...)` replaces the default mapping; built-in word-level rules still apply.

Detailed results contain `text`, `ai_used` and an ordered tuple of `decisions`. `ai_used` is true when a resolver was consulted for at least one final-`н` occurrence; offline results have `ai_used=False` and no decisions. See [decision fields and source spans](https://github.com/chechen-language/ce-translit-py/blob/main/docs/contextual-nasalization.md#decisions-and-source-spans) when inspecting individual readings.

## Transliteration

The offline engine applies the [Chechen alphabet mapping](https://github.com/chechen-language/ce-translit-py/blob/main/src/ce_translit/data/cyrl_latn_map.json) to letters and character combinations. Longer combinations are matched before their component letters. Representative mappings include:

| Group | Examples |
| --- | --- |
| Vowels | `аь → ä`, `оь → ö`, `уь → ü`, `яь → yä`, `юь → yü` |
| Consonant combinations | `гӏ → ġ`, `кх → q`, `къ → q̇`, `кӏ → k̇`, `хь → ẋ`, `хӏ → h` |
| Doubled consonants | `ггӏ → ġġ`, `ккх → qq`, `ттӏ → ṫṫ`, `ххь → ẋẋ` |

Both palochka spellings, `ӏ` (U+04CF) and `Ӏ` (U+04C0), are recognized. The mapping includes lowercase and uppercase forms. `ь` and `ы` have no standalone Latin output; `ъ` maps to `ə` when it is not a separator or part of a consonant combination.

Words are runs of Unicode letters, decimal digits and attached combining marks; hyphens and other punctuation separate words. Word-level spelling rules also apply: standalone `а` becomes `ə`, and `е` becomes `ye` at word start, after a Cyrillic vowel or after a separating `ъ` or `ь`. Signs within consonant combinations are treated as part of that consonant.

Whitespace, punctuation and emoji are preserved. Unmapped letters stay in their source script, and digits remain literal unless explicitly mapped. Word output uses Unicode NFC normalization. Source stress and annotation marks attached to Cyrillic letters are removed while structural diacritics in letters such as `ё` and `й`, and in the target Latin alphabet, are retained.

See [known limitations](https://github.com/chechen-language/ce-translit-py/blob/main/docs/limitations.md) for uppercase Latin expansions and invisible format characters inside words.

## Contextual Nasalization

Chechen homographs can share a Cyrillic spelling while differing in meaning and pronunciation:

| Cyrillic | Meaning | Latin |
| --- | --- | --- |
| шун | your | şuŋ |
| шун | table / tray | şun |
| бен | only / except | beŋ |
| бен | nest / den | ben |

In the adopted Latin orthography, `ŋ` denotes vowel nasalization; `n` represents the pronounced consonant. The resolver analyses each occurrence separately using surrounding text. Predictions can contain linguistic errors.

Install the optional dependencies:

```bash
uv add 'ce-translit[ai]'   # or: pip install 'ce-translit[ai]'
```

Set `GEMINI_API_KEY` to your API key and `GEMINI_MODEL` to a model available on your service. `GEMINI_BASE_URL` is optional; leave it unset for Google's Gemini API. The example reads environment variables explicitly; the library does not load variables or `.env` files automatically.

```python
import os

from ce_translit import Transliterator
from ce_translit.ai import GeminiNasalResolver

source = "цхьа стаг бен вацар арахь"
with GeminiNasalResolver(
    api_key=os.environ["GEMINI_API_KEY"],
    model=os.environ["GEMINI_MODEL"],
    base_url=os.environ.get("GEMINI_BASE_URL") or None,
    context="adjacent",
    thinking_level=os.environ.get("GEMINI_THINKING_LEVEL") or "low",
) as resolver:
    transliterator = Transliterator(nasal_resolver=resolver)
    result = transliterator.transliterate_detailed(source)
    print(result.text)
    for decision in result.decisions:
        print(decision.word, decision.kind, decision.reason)
```

An expected reading is `cẋa stag beŋ vacar araẋ`; actual model decisions may differ. Reuse the resolver inside the `with` block, which closes its network resources on exit. `include_reasons=False` omits visible explanations for bulk conversion.

This example selects adjacent-sentence context and defaults to low reasoning, overridable with `GEMINI_THINKING_LEVEL`. See [resolver configuration and defaults](https://github.com/chechen-language/ce-translit-py/blob/main/docs/contextual-nasalization.md#configuration) for these options, Gemini-compatible gateways, async use, request limits and error handling. If the optional dependencies are missing, constructing the resolver raises `MissingAIDependencyError`; install `ce-translit[ai]`.

AI processing sends source context to the configured provider and consumes its API quota. Review that provider's pricing and data-handling terms before processing sensitive texts.

## Development

```bash
uv run --extra ai --with pytest pytest
uv build
```

The offline tests cover transliteration, Unicode handling, contexts, occurrence tracking and SDK requests to local HTTP servers. They need no provider key or Gemini endpoint. For opt-in provider checks, see [live evaluation](https://github.com/chechen-language/ce-translit-py/blob/main/docs/contextual-nasalization.md#live-evaluation).

Report bugs or ask questions in [GitHub Issues](https://github.com/chechen-language/ce-translit-py/issues).
