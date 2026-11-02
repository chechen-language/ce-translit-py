"""Optional AI adapters. Importing the core never imports this package."""

from ce_translit.ai._gemini import GeminiNasalResolver

__all__ = ["GeminiNasalResolver"]
