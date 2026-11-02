"""Public, provider-independent AI failures. Messages contain no source text."""


class MissingAIDependencyError(ImportError):
    """Install ce-translit[ai] to use the Gemini resolver."""


class NasalResolutionError(RuntimeError):
    """Base class for failures of an enabled nasal resolver."""


class NasalInputError(NasalResolutionError):
    """An input cannot be processed within the context limits."""


class NasalAPIError(NasalResolutionError):
    """An API request failed; no partially transliterated text is returned."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class NasalResponseError(NasalResolutionError):
    """The model response is incomplete, blocked or structurally invalid."""
