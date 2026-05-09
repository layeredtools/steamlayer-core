"""
steamlayer_core.events
======================
Typed events that the resolution engine emits when it needs human input.

Architecture rationale
----------------------
The solution is **structured suspension**: instead of blocking on I/O, the
resolver constructs one of these event objects and hands it to a
``DisambiguationHandler`` (a plain callable defined in ``protocols.py``).

The handler is *injected* at call-site — the CLI injects one that calls
``input()``, the FastAPI bridge injects one that stores the event in a
session and polls for a frontend POST, and tests inject a deterministic fake.

No ``input()`` call exists anywhere in ``steamlayer_core``.

Decision types
--------------
``AmbiguousMatchEvent``
    Two or more candidates scored close enough that auto-selection would be
    unreliable.  The handler must return the chosen ``DiscoveryResult``.

``LowConfidenceEvent``
    A single best candidate was found but its score is below the strict
    threshold.  The handler may accept it, reject it, or supply a manual AppID.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from steamlayer_core.domain.models import DiscoveryResult


@dataclass(frozen=True, slots=True)
class AmbiguousMatchEvent:
    """
    Emitted when multiple candidates are too close to auto-select.

    Attributes
    ----------
    candidates:
        Top-scored candidates, sorted highest-confidence first.
        Guaranteed non-empty (len >= 2).
    game_folder_name:
        The raw folder name that triggered the search.  Useful for
        display purposes.
    """

    candidates: tuple[DiscoveryResult, ...]
    game_folder_name: str

    def __post_init__(self) -> None:
        if len(self.candidates) < 2:
            raise ValueError("AmbiguousMatchEvent requires at least 2 candidates.")


@dataclass(frozen=True, slots=True)
class LowConfidenceEvent:
    """
    Emitted when the best match scores below the acceptance threshold.

    Attributes
    ----------
    candidate:
        The best (but uncertain) match.
    threshold:
        The minimum score needed for auto-acceptance in the current mode.
    game_folder_name:
        Raw folder name for display.
    """

    candidate: DiscoveryResult
    threshold: float
    game_folder_name: str


type ResolutionEvent = AmbiguousMatchEvent | LowConfidenceEvent
