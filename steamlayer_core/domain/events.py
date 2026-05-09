"""
steamlayer_core.domain.events
==============================
Event types that flow between the core resolver and the outer application
layer (CLI, FastAPI, GUI).

The primary event is ``DisambiguationRequest``, which is *embedded* inside
``DisambiguationRequired`` exceptions.  By exporting it here we give callers
a stable import path that won't change if the exception module is reorganised.

Design principles
-----------------
1. Events are *plain data* — no business logic, no external dependencies.
2. Every field has a ``to_dict()`` method so FastAPI can return them as JSON
   without a custom encoder or Pydantic dependency.
3. The ``DisambiguationKind`` enum encodes *why* the human is needed, letting
   the UI adapt its wording (e.g. "Multiple close matches" vs "Low confidence").
"""

from __future__ import annotations

from dataclasses import dataclass

from steamlayer_core.domain.models import DiscoveryResult


@dataclass(frozen=True)
class AmbiguousMatchEvent:
    """
    Dispatched when multiple candidates score too close to auto-select.
    """

    candidates: tuple[DiscoveryResult, ...]
    game_folder_name: str


@dataclass(frozen=True)
class LowConfidenceEvent:
    """
    Dispatched when the single best candidate is below the acceptance threshold.
    """

    candidate: DiscoveryResult
    threshold: float
    game_folder_name: str
