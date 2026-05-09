"""
steamlayer_core.domain.exceptions
==============================
All domain-specific exceptions.  The public API only raises these — never raw
`OSError`, `requests.exceptions.*`, etc. Wrappers should catch at
this boundary and translate to HTTP status codes or user-facing messages.

Exception hierarchy
-------------------
```text
SteamLayerError                     (base)
├── ConfigurationError              (bad inputs before work starts)
├── NetworkError                    (transport-level failure)
├── AppIDResolutionError            (base for resolution failures)
│   ├── AppIDNotFoundError          (exhausted all strategies, nothing found)
│   ├── AmbiguousMatchError         (multiple candidates scored too close to auto-select)
│   └── LowConfidenceError          (best candidate scored below acceptance threshold)
├── DLCHydrationError               (DLC fetching failed, possibly partial)
│   └── DLCCacheError               (cache read/write failed)
└── PatchError                      (filesystem / patching errors)
    ├── VaultError                  (backup vault problems)
    └── EmulatorBinaryError         (Goldberg / Steamless not found)
```
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from steamlayer_core.domain.models import ResolvedGame


class SteamLayerError(Exception):
    """Root exception for all steamlayer_core errors."""


class ConfigurationError(SteamLayerError):
    """
    Raised when caller-supplied configuration is invalid before any work starts.

    Examples: unknown language code, negative TTL, unrecognised config key.
    """


class NetworkError(SteamLayerError):
    """
    Transport-level failure (DNS, connection refused, timeout, non-2xx).

    Attributes
    ----------
    url:         The URL that failed (if known).
    status_code: HTTP status code (None for connection-level errors).
    """

    def __init__(self, message: str, *, url: str | None = None, status_code: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status_code = status_code


class AppIDResolutionError(SteamLayerError):
    """Base class for all AppID resolution failures."""


class AmbiguousMatchError(AppIDResolutionError):
    def __init__(self, candidates: Sequence[ResolvedGame]) -> None:
        self.candidates = candidates
        super().__init__(
            f"Ambiguous match: {len(candidates)} candidates scored too close to auto-select. "
            "Provide a DisambiguationHandler or pass --appid explicitly."
        )


class LowConfidenceError(AppIDResolutionError):
    def __init__(self, candidate: ResolvedGame, *, threshold: float) -> None:
        self.candidate = candidate
        self.threshold = threshold
        super().__init__(
            f"Low confidence match: '{candidate.game_name}' "
            f"scored {candidate.confidence:.2f} < threshold {threshold:.2f}."
        )


class AppIDNotFoundError(AppIDResolutionError):
    """
    Raised when every resolution strategy (local, index, web) was exhausted
    without finding a plausible match.

    Attributes
    ----------
    game_name: The folder/display name that was searched for.
    """

    def __init__(self, game_name: str) -> None:
        super().__init__(f"Could not resolve AppID for '{game_name}' — all strategies exhausted.")
        self.game_name = game_name


class DLCHydrationError(SteamLayerError):
    """
    Raised when DLC metadata fetching fails entirely.

    A *partial* failure (some DLCs resolved, some used fallback names) is NOT
    raised as an exception — it is reflected in the ``DLCResult`` model.
    """

    def __init__(self, appid: int, reason: str) -> None:
        super().__init__(f"DLC hydration failed for AppID {appid}: {reason}")
        self.appid = appid


class DLCCacheError(DLCHydrationError):
    """Raised when the DLC cache cannot be read or written (permissions, corruption)."""


class PatchError(SteamLayerError):
    """Base class for patching and filesystem errors."""


class VaultError(PatchError):
    """
    Raised when the backup vault cannot be created, read, or restored from.

    Attributes
    ----------
    vault_path: Path to the vault directory.
    """

    def __init__(self, message: str, vault_path: str | None = None) -> None:
        super().__init__(message)
        self.vault_path = vault_path


class EmulatorBinaryError(PatchError):
    """
    Raised when a required vendor binary is
    missing or fails to execute.

    Attributes
    ----------
    binary_name: Human-readable name of the missing binary.
    """

    def __init__(self, binary_name: str) -> None:
        super().__init__(f"Required binary '{binary_name}' not found.")
        self.binary_name = binary_name
