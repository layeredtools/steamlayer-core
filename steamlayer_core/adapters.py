from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from steamlayer_core.domain.exceptions import AppIDNotFoundError, AppIDResolutionError

if TYPE_CHECKING:
    from steamlayer_core.domain.models import DiscoveryResult
    from steamlayer_core.events import AmbiguousMatchEvent, LowConfidenceEvent

logger = logging.getLogger(__name__)


class FixedDisambiguationHandler:
    """
    Adapter used when the user has already provided a specific AppID (e.g., via CLI).
    Instead of asking, it searches the candidates for a match and returns it.
    """

    def __init__(self, target_appid: int) -> None:
        self.target_appid = target_appid

    def handle_disambiguation(self, event: AmbiguousMatchEvent) -> DiscoveryResult:
        logger.debug(f"Fixed handler looking for AppID {self.target_appid} in candidates.")

        for candidate in event.candidates:
            if candidate.appid == self.target_appid:
                return candidate

        raise ValueError(f"Provided AppID {self.target_appid} not found in resolution candidates.")


class FixedConfirmationHandler:
    """
    Adapter used for 'non-interactive' mode (e.g., a --yes flag).
    Automatically accepts or rejects low-confidence matches.
    """

    def __init__(self, auto_confirm: bool = True) -> None:
        self.auto_confirm = auto_confirm

    def handle_confirmation(self, event: LowConfidenceEvent) -> DiscoveryResult:
        logger.info(
            f"Auto-confirming ({self.auto_confirm}) match for {event.game_folder_name} "
            f"with confidence {event.candidate.confidence:.2f}"
        )
        if self.auto_confirm:
            return event.candidate
        raise AppIDNotFoundError(event.game_folder_name)


class CLIHandler:
    """
    The primary interactive adapter for terminal users.
    """

    def handle_disambiguation(self, event: AmbiguousMatchEvent) -> DiscoveryResult:
        print(f"\n[!] Multiple matches found for folder: '{event.game_folder_name}'")
        for i, c in enumerate(event.candidates, 1):
            print(f"  {i}) {c.game_name} (AppID: {c.appid}) [Confidence: {c.confidence:.2f}]")

        while True:
            choice = input("\nSelect the correct game (or 'q' to abort): ").strip().lower()
            if choice == "q":
                raise KeyboardInterrupt()
            if choice.isdigit() and 1 <= int(choice) <= len(event.candidates):
                return event.candidates[int(choice) - 1]

    def handle_confirmation(self, event: LowConfidenceEvent) -> DiscoveryResult:
        print(f"\n[?] Low confidence match for '{event.game_folder_name}':")
        print(f"    Suggested: {event.candidate.game_name} (AppID: {event.candidate.appid})")
        print(f"    Confidence: {event.candidate.confidence:.2f} (Threshold: {event.threshold:.2f})")

        choice = input("Is this correct? [y/N]: ").strip().lower()
        if choice == "y":
            return event.candidate
        raise AppIDResolutionError("User rejected candidate.")
