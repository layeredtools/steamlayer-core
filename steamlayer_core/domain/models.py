"""
steamlayer_core.domain.models
==============================
Canonical domain models for the steamlayer-core public API.

These are the *only* types that cross the library boundary.  Internal
implementation details (e.g., raw dicts from the Steam API) never appear in
public function signatures.

Versioning contract
-------------------
Fields added here are always keyword-only with defaults so that existing
callers don't break when new fields are introduced.

Model hierarchy
---------------
``DiscoveryResult``
    Lightweight internal result produced and consumed within the resolution
    waterfall.  Returned by ``ResolutionEngine.resolve()`` and passed through
    disambiguation handlers.

``ResolvedGame``
    Rich output of ``api.resolve_game()``.  Everything a UI needs to display
    results and decide on next steps (DLC count, source badge, etc.).

``Candidate``
    A single plausible AppID match accumulated during the waterfall.
    Embedded in ``DisambiguationRequest`` and ``ResolutionResult``.

``ResolutionResult``
    Intermediate result produced by ``ResolutionEngine``.
    Richer than ``DiscoveryResult`` — includes ``candidates_seen`` for audit.

``DisambiguationRequest``
    Payload carried by ``DisambiguationRequired`` exceptions.

``SteamlayerOptions``
    Caller-supplied configuration for a single resolution run.

``DLCInfo``
    Metadata for a single DLC item.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any

from steamlayer_core.constants import DEFAULT_CACHE_DIR, DEFAULT_CACHE_TTL


class ResolutionSource(Enum):
    """Records *how* an AppID was determined — useful for telemetry and display."""

    MANUAL = auto()  # explicitly passed by the caller
    LOCAL_FILE = auto()  # steam_appid.txt or .acf manifest in the game folder
    LOCAL_INDEX = auto()  # community JSON index cached on disk
    WEB_SEARCH = auto()  # Steam store search API
    USER_SELECTED = auto()  # user broke a tie or confirmed a low-confidence hit


@dataclass
class DiscoveryResult:
    """
    Lightweight result object produced and consumed *within* the resolution
    waterfall.

    Returned by ``ResolutionEngine.resolve()`` and by all disambiguation /
    confirmation handlers (see ``steamlayer_core.protocols``).

    Note: this is intentionally simpler than ``ResolvedGame`` — it carries
    only what the engine needs to operate.  The public ``api.resolve_game()``
    function wraps it in ``ResolvedGame`` before returning to callers.

    Attributes
    ----------
    appid:
        The resolved Steam App ID.  ``None`` only in the empty sentinel state
        (e.g., while accumulating candidates; never None on a successful return).
    source:
        Which strategy produced this result.  ``None`` for the empty sentinel.
    confidence:
        Heuristic match score, 0.0 – 1.0.
    game_name:
        Steam display name for the matched game.  ``None`` when the AppID
        was supplied manually or came from a local file.
    user_selected:
        ``True`` when a human explicitly chose this result from a disambiguation
        menu or entered the AppID manually.
    """

    appid: int | None = None
    source: ResolutionSource | None = None
    confidence: float = 0.0
    game_name: str | None = None
    user_selected: bool = False


@dataclass
class ResolutionResult:
    """
    Returned by ``ResolutionEngine.resolve()`` on success.

    Attributes
    ----------
    appid:
        The resolved Steam App ID.
    game_name:
        Display name as reported by the source.  May be ``None`` when the
        AppID was supplied manually.
    source:
        Which strategy succeeded.
    confidence:
        Match score (1.0 for manual/local-file; heuristic score otherwise).
    user_selected:
        ``True`` when the caller re-submitted with an explicit ``appid``.
    candidates_seen:
        All candidates evaluated during the waterfall (useful for logging /
        debugging false positives).
    """

    appid: int
    game_name: str | None
    source: ResolutionSource
    confidence: float
    user_selected: bool = False
    candidates_seen: list[Candidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "appid": self.appid,
            "game_name": self.game_name,
            "source": self.source.value,
            "confidence": round(self.confidence, 4),
            "user_selected": self.user_selected,
            "candidates_seen": [c.to_dict() for c in self.candidates_seen],
        }


@dataclass
class Candidate:
    """
    A single plausible AppID match produced during the resolution waterfall.

    Returned inside ``DisambiguationRequest`` when the resolver cannot
    auto-select.  Also embedded in ``ResolutionResult`` as ``candidates_seen``
    for audit/logging.
    """

    appid: int
    game_name: str
    confidence: float  # 0.0 – 1.0, higher is better
    source: ResolutionSource

    def to_dict(self) -> dict[str, Any]:
        return {
            "appid": self.appid,
            "game_name": self.game_name,
            "confidence": round(self.confidence, 4),
            "source": self.source.value,
        }

    def __repr__(self) -> str:
        return (
            f"Candidate(appid={self.appid}, name={self.game_name!r}, "
            f"conf={self.confidence:.2f}, src={self.source.value})"
        )


@dataclass(slots=True)
class ResolvedGame:
    """
    Final output of a successful resolution run.

    This is what ``api.resolve_game()`` returns.
    """

    appid: int
    game_name: str | None
    confidence: float
    dlcs: dict[int, DLCInfo] | None = field(default_factory=dict)
    source: ResolutionSource | None = None

    @property
    def is_hydrated(self) -> bool:
        """
        Whether DLC metadata has been fetched for this game.

        A freshly resolved game is **not** hydrated — ``dlcs`` is ``None``
        until ``fetch_dlcs()`` has been called and the result assigned.
        This distinguishes "not yet fetched" from "fetched but no DLCs exist"
        (the latter being an empty dict).

        Use this to guard against accidentally treating an unhydrated result
        as if it had no DLCs::

            if not game.is_hydrated:
                game.dlcs = fetch_dlcs(game.appid, http_client=client)
        """
        return self.dlcs is not None

    @property
    def dlc_count(self) -> int:
        return len(self.dlcs or ())


@dataclass(slots=True, frozen=True)
class DLCInfo:
    """Metadata for a single DLC item."""

    appid: int
    name: str
    from_cache: bool = False


@dataclass(slots=True)
class SteamlayerOptions:
    """
    Controls resolution behaviour, DLC hydration, and cache configuration.

    Designed to be constructed once by the caller and passed into
    ``resolve_game()`` or ``SteamLayerClient``.  All fields have sensible
    defaults so callers only need to set what they care about.

    Attributes
    ----------
    appid:
        If set, skip all discovery and treat this as the authoritative ID.
    strict:
        When ``True`` (default), the confidence threshold for auto-acceptance
        is 0.85.  When ``False`` ("yolo" mode), it drops to 0.40.
    fetch_dlcs:
        Whether to hydrate DLC metadata after resolving the AppID.
    dlc_cache_ttl_seconds:
        How long DLC cache entries are considered fresh before a network
        refresh is attempted.  Default: 7 days.
    cache_dir:
        Directory for on-disk DLC cache files.
        Default: ``~/.steamlayer/.cache``.
    """

    appid: int | None = None
    strict: bool = True
    fetch_dlcs: bool = True
    dlc_cache_ttl_seconds: int = DEFAULT_CACHE_TTL
    cache_dir: Path | str = DEFAULT_CACHE_DIR
