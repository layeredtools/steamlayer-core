"""
steamlayer_core.protocols
=========================
``typing.Protocol`` definitions for every injectable boundary in the library.

Handler contracts
-----------------
``DisambiguationHandler``
    Invoked when multiple candidates score too close to auto-select.
    Must return the chosen ``DiscoveryResult`` (or raise to abort).

``ConfirmationHandler``
    Invoked when the single best candidate is below the acceptance threshold.
    Must return the ``DiscoveryResult`` to proceed with, or raise to abort.
    Returning a result whose ``appid`` differs from the event's candidate
    is valid — the user may supply a completely different ID.

``ProgressCallback``
    Optional callback for reporting progress steps to the caller.
    The ``step`` field is a slug like ``"fetching_dlcs"``; ``detail`` is a
    human-readable description for display.

Both handler protocols support both synchronous and asynchronous callers.
See ``steamlayer_core.adapters`` for ready-made implementations.
"""

from __future__ import annotations

import pathlib
from typing import Any, Protocol, runtime_checkable

from steamlayer_core.domain.events import AmbiguousMatchEvent, LowConfidenceEvent
from steamlayer_core.domain.models import DiscoveryResult, DLCInfo


@runtime_checkable
class DisambiguationHandler(Protocol):
    """
    Called when the engine finds multiple near-identical candidates.

    The implementation must either:
    - Return one of the provided candidates (or a manual ``DiscoveryResult``).
    - Raise ``steamlayer_core.exceptions.ResolutionError`` to abort resolution.

    Parameters
    ----------
    event:
        Contains ``event.candidates`` (sorted by confidence, highest first)
        and ``event.game_folder_name`` for display.

    Example (sync CLI adapter)::

        def cli_disambiguate(event: AmbiguousMatchEvent) -> DiscoveryResult:
            for i, c in enumerate(event.candidates, 1):
                print(f"{i}. {c.game_name} ({c.appid})")
            idx = int(input("Choice: ")) - 1
            return event.candidates[idx]
    """

    def __call__(self, event: AmbiguousMatchEvent) -> DiscoveryResult: ...


@runtime_checkable
class ConfirmationHandler(Protocol):
    """
    Called when the best candidate scores below the acceptance threshold.

    The implementation must either:
    - Return the candidate as-is to accept it.
    - Return a new ``DiscoveryResult`` with a different ``appid`` to override.
    - Raise ``steamlayer_core.exceptions.LowConfidenceError`` to abort.

    Parameters
    ----------
    event:
        Contains ``event.candidate``, ``event.threshold``, and
        ``event.game_folder_name``.
    """

    def __call__(self, event: LowConfidenceEvent) -> DiscoveryResult: ...


@runtime_checkable
class ProgressCallback(Protocol):
    """
    Optional hook for surfacing progress to a UI.

    Parameters
    ----------
    step:
        Machine-readable slug (e.g., ``"local_scan"``, ``"web_search"``,
        ``"fetching_dlcs"``).
    detail:
        Human-readable description for display.
    """

    def __call__(self, step: str, detail: str) -> None: ...


@runtime_checkable
class HTTPClientProtocol(Protocol):
    def get(self, url: str, *, params: dict | None = None, **kwargs: Any) -> Any: ...
    def download(self, url: str, *, dest: pathlib.Path, **kwargs: Any) -> None: ...
    def close(self) -> None: ...


@runtime_checkable
class SteamWebClientProtocol(Protocol):
    def search_store(self, term: str) -> dict: ...
    def get_app_details(self, appid: int) -> dict: ...


@runtime_checkable
class AppIndexRepositoryProtocol(Protocol):
    def get_app_index(self) -> dict[str, int]: ...
    def get_dlc_index(self) -> dict[int, str]: ...


# These satisfy the protocols and can be used as drop-in no-ops.
class _NullProgress:
    """A progress callback that silently discards all events."""

    def __call__(self, step: str, detail: str) -> None:
        pass


NULL_PROGRESS: ProgressCallback = _NullProgress()


@runtime_checkable
class VendorProvider(Protocol):
    """
    Source of vendor binaries required for patching.

    ``PatchEngine`` never hardcodes where binaries live — it delegates to an
    injected provider.  This allows the CLI, GUI, CI runners, and end users to
    each manage binaries differently without touching the engine.

    Implementations
    ---------------
    ``LocalVendorProvider``
        Points at user-managed paths on disk.  The canonical implementation
        for most use cases.
    """

    def get_emulator_dll(self, architecture: str) -> pathlib.Path:
        """
        Return the path to the emulator replacement DLL for *architecture*.

        Parameters
        ----------
        architecture:
            ``"x86"`` or ``"x64"``.

        Returns
        -------
        pathlib.Path
            Absolute path to the DLL file.

        Raises
        ------
        EmulatorBinaryError
            When the binary cannot be located for the requested architecture.
        """
        ...

    def get_steamless_exe(self) -> pathlib.Path | None:
        """
        Return the path to the Steamless CLI executable, or ``None`` if
        Steamless is not available.

        When this returns ``None``, the patch engine skips DRM stripping
        entirely — it is not treated as an error.

        Returns
        -------
        pathlib.Path | None
            Absolute path to ``Steamless.CLI.exe``, or ``None``.
        """
        ...


class ConfigWriter(Protocol):
    """
    Writes emulator configuration files for a patched game.

    Implement this protocol to add support for emulators other than
    Goldberg.  Inject your implementation via ``PatchEngine(config_writer=...)``.
    """

    def write(
        self,
        dll_dir: pathlib.Path,
        appid: int,
        dlcs: dict[int, DLCInfo],
    ) -> None: ...
