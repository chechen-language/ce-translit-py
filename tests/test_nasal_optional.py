import builtins

import pytest

from ce_translit.ai import GeminiNasalResolver
from ce_translit.errors import MissingAIDependencyError


def test_missing_sdk_has_actionable_error_without_activating_core(monkeypatch):
    original = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "google" or name.startswith("google.genai"):
            raise ImportError("Not installed.")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(MissingAIDependencyError, match=r"ce-translit\[ai\]"):
        GeminiNasalResolver(api_key="key", model="model")
