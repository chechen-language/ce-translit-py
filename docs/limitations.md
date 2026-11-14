# Known Limitations

## Deferred: Invisible Characters Inside Words

Status: documented, not scheduled for implementation in the current work. The owner explicitly requested that these cases remain unprocessed for now.

The tokenizer groups Unicode letters, decimal digits and attached combining marks. Format characters such as U+00AD SOFT HYPHEN and U+200D ZERO WIDTH JOINER currently delimit tokens, even when they are visually embedded in a word. The original characters are preserved in the output.

For example, the code-point sequence `са\u00adн` can look like `сан`, but it is tokenized as `са` and `н`. The resolver can consequently receive the isolated final `н` rather than the complete word. A soft hyphen can also make a following `е` count as word-initial.

This is a potential issue with copied or OCR-derived text. No such format characters were found in the 741-record corpus checked during the November 2026 review; that does not establish their absence in other input.

Future work must distinguish legitimate word boundaries from in-word formatting and preserve original source spans. Do not remove every invisible character indiscriminately or silently normalize the input. This file records the limitation only; it does not authorize that change.
