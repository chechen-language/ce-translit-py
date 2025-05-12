from ce_translit import Transliterator

# Create a custom transliterator with your own rules
custom_transliterator = Transliterator(
    # Custom letter mapping
    mapping={
        **Transliterator()._mapping, # First define base mapping
        # Then override specific mappings
        "й": "j",
        # Append completely new mappings
        "1": "j"
    },
    # Words that should keep the regular 'н' at the end
    blacklist=["дин", "гӏан", "сан"],
    # Words that should use 'ŋ[REPLACE]' at the end
    unsurelist=["шун", "бен", "цӏен"]
)

# Use the custom transliterator
result = custom_transliterator.transliterate("1аж, дин, шун")
print(result)  # Uses custom rules