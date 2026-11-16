# Known Limitations

## Uppercase Latin Expansions

Some uppercase Cyrillic letters expand to more than one Latin letter. `Я` and `Ю` map to `Ya` and `Yu`, and `ЯЬ` and `ЮЬ` map to `Yä` and `Yü`, even in all-caps input. These expansions are not automatically converted to all-uppercase Latin spellings.

## Invisible Characters Inside Words

The tokenizer groups Unicode letters, decimal digits and attached combining marks. Format characters such as U+00AD SOFT HYPHEN and U+200D ZERO WIDTH JOINER currently delimit tokens, even when they are visually embedded in a word. The original characters are preserved in the output.

For example, the code-point sequence `са\u00adн` can look like `сан`, but it is tokenized as `са` and `н`. The resolver can consequently receive the isolated final `н` rather than the complete word. A soft hyphen can also make a following `е` count as word-initial.

This can affect copied or OCR-derived text. The library preserves these characters and does not repair the surrounding word boundaries. Review affected input before conversion; removing every invisible character indiscriminately can also remove meaningful boundaries.
