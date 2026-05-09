"""
steamlayer_core.api
===================
The sole public interface for ``steamlayer-core``.

Consumers should **only** import from this module.
Everything below the API boundary is an implementation detail.

Usage
-----
Quick one-shot functions for simple scripts::

    game = resolve_game(Path("C:/games/Euro Truck Simulator 2"))
    patch_game(game, Path("C:/games/Euro Truck Simulator 2"), vendor=vendor, config_writer=writer)

Stateful client for when you need shared lifecycle management (HTTP session,
resolver reuse, progress hooks wired once)::

    with SteamLayerClient(vendor=vendor, config_writer=writer) as client:
        game = client.resolve(Path("C:/games/Euro Truck Simulator 2"))
        result = client.patch(game, Path("C:/games/Euro Truck Simulator 2"))

Classes
-------
SteamLayerClient
    Stateful orchestrator. Manages HTTP session lifecycle, resolver
    construction, and exposes ``resolve()``, ``patch()``, ``unpatch()``,
    ``fetch_dlcs()``, and ``is_patched()`` as methods.

Functions
---------
resolve_game(game_path, options, ...)
    One-shot wrapper around ``SteamLayerClient.resolve()``.  Runs the full
    waterfall (local file → index → web search → disambiguation) and
    optionally hydrates DLC metadata.  Returns a ``ResolvedGame``.

patch_game(game, game_path, ...)
    One-shot wrapper around ``SteamLayerClient.patch()``.  Applies an
    emulator patch to a game directory.  Returns a ``PatchResult``.

fetch_dlcs(appid, ...)
    One-shot wrapper around ``SteamLayerClient.fetch_dlcs()``.  Hydrates
    DLC metadata for a known AppID.  Returns ``dict[int, DLCInfo]``.

Design notes
------------
- No ``input()`` or ``print()`` calls here or anywhere reachable from here.
- All human-interaction events are delegated to injected handlers.
- Exceptions are always typed (see ``steamlayer_core.domain.exceptions``).
- ``pathlib.Path | str`` is accepted for all filesystem arguments.
- ``SteamLayerClient`` is the canonical entry point; the module-level
  functions are thin convenience wrappers that open and close a client
  for a single call.
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any

from steamlayer_core.discovery.engine import ResolutionEngine
from steamlayer_core.domain.exceptions import AppIDNotFoundError, PatchError
from steamlayer_core.domain.models import (
    DLCInfo,
    ResolvedGame,
    SteamlayerOptions,
)
from steamlayer_core.http_client import HTTPClient
from steamlayer_core.patching.models import PatchResult
from steamlayer_core.protocols import (
    NULL_PROGRESS,
    ConfigWriter,
    ConfirmationHandler,
    DisambiguationHandler,
    HTTPClientProtocol,
    ProgressCallback,
    SteamWebClientProtocol,
    VendorProvider,
)

log = logging.getLogger("steamlayer_core.api")


class SteamLayerClient:
    """
    A stateful, emulator-agnostic orchestrator for the SteamLayer pipeline.

    The client serves as a universal interface for identifying and patching
    Steam games. By decoupling the patching logic from specific emulator
    implementations, it can support any Steam-emulator environment (Goldberg,
    etc.) simply by injecting the appropriate VendorProvider and ConfigWriter.

    The client manages the shared lifecycle of dependencies, such as HTTP
    sessions and resolution engines, ensuring resource efficiency and
    clean cleanup.

    Parameters
    ----------
    options: `SteamlayerOptions | None`
        Configuration for game and DLC resolution logic.
    allow_network: `bool`
        If True (default), the client ensures an HTTP session is available for
        web-based metadata hydration and store searches.
    vendor: `VendorProvider | None`
        Provider for emulator binaries and metadata. Required for patching.
    config_writer: `ConfigWriter | None`
        Custom logic for writing emulator configuration files. If None,
        the engine uses its default implementation.
    on_disambiguation: `DisambiguationHandler | None`
        Callback for resolving ties between multiple game candidates.
    on_confirmation: `ConfirmationHandler | None`
        Callback for verifying low-confidence matches.
    http_client: `HTTPClientProtocol | None`
        A custom HTTP client implementation. If provided, this instance
        is used regardless of the ``allow_network`` setting. If None and
        ``allow_network`` is True, a default internal client is initialized.
    progress: `ProgressCallback`
        Hook for reporting operation status (e.g., UI progress bars).
    """

    def __init__(
        self,
        *,
        options: SteamlayerOptions | None = None,
        allow_network: bool = True,
        vendor: VendorProvider | None = None,
        config_writer: ConfigWriter | None = None,
        on_disambiguation: DisambiguationHandler | None = None,
        on_confirmation: ConfirmationHandler | None = None,
        progress: ProgressCallback = NULL_PROGRESS,
        http_client: HTTPClientProtocol | None = None,
    ) -> None:
        self.options = options or SteamlayerOptions()
        self.allow_network = allow_network
        self.vendor = vendor
        self.config_writer = config_writer
        self.on_disambiguation = on_disambiguation
        self.on_confirmation = on_confirmation
        self.progress = progress
        self._http_client = http_client
        self.__resolver: ResolutionEngine | None = None

    @property
    def _resolver(self) -> ResolutionEngine:
        if self.__resolver is None:
            self.__resolver = self._build_resolver()
        return self.__resolver

    def _build_resolver(self) -> ResolutionEngine:
        from steamlayer_core.discovery.local import LocalDiscovery
        from steamlayer_core.discovery.matcher import NameMatcher
        from steamlayer_core.discovery.query_strategy import QueryStrategy
        from steamlayer_core.discovery.repository import AppIndexRepository
        from steamlayer_core.discovery.web import SteamWebClient

        matcher = NameMatcher()
        repo = AppIndexRepository(http=self._http_client)
        web: SteamWebClientProtocol = (
            SteamWebClient(http=self._http_client) if self._http_client else _OfflineSteamWebClient()
        )

        return ResolutionEngine(
            local_discovery=LocalDiscovery(),
            app_index_repository=repo,
            steam_web_client=web,
            name_matcher=matcher,
            query_strategy=QueryStrategy(matcher),
        )

    def resolve(self, game_path: pathlib.Path | str) -> ResolvedGame:
        """
        Identify a game and hydrate its metadata.

        Uses the internal HTTP client if ``allow_network`` was set to True during
        initialization.

        Parameters
        ----------
        game_path: `pathlib.Path | str`
            The filesystem path to the game's root directory.

        Returns
        -------
        `ResolvedGame`
            The identified game metadata.
        """
        game_path = pathlib.Path(game_path)

        result = self._resolver.resolve(
            game_path,
            options=self.options,
            allow_network=self.allow_network,
            on_disambiguation=self.on_disambiguation,
            on_confirmation=self.on_confirmation,
            progress=self.progress,
        )

        if result.appid is None:
            raise AppIDNotFoundError(str(game_path))

        dlcs: dict[int, DLCInfo] = {}
        if self.options.fetch_dlcs and self.allow_network:
            dlcs = self.fetch_dlcs(result.appid)

        return ResolvedGame(
            appid=result.appid,
            game_name=result.game_name,
            source=result.source,
            confidence=result.confidence,
            dlcs=dlcs,
        )

    def patch(self, game: ResolvedGame, game_path: pathlib.Path | str) -> PatchResult:
        """
        Apply an emulator patch to the specified game directory.

        Parameters
        ----------
        game: `ResolvedGame`
            Metadata identifying the game and its components.
        game_path: `pathlib.Path | str`
            The filesystem path to the game's root directory.

        Returns
        -------
        PatchResult
            Summary of the files modified and backups created.
        """
        from steamlayer_core.patching import PatchEngine

        if self.vendor is None:
            raise PatchError(
                f"Failed to patch game at '{game_path}': No VendorProvider configured. "
                "The SteamLayerClient requires a vendor (e.g., LocalVendorProvider) "
                "to supply emulator binaries before a patch can be applied."
            )

        if self.config_writer is None:
            raise PatchError(
                f"Failed to patch game at '{game_path}': No ConfigWriter configured. "
                "While a vendor provides the binaries, a ConfigWriter is required to "
                "define how and where the emulator settings (AppID, DLCs) are stored."
            )

        path = pathlib.Path(game_path)
        engine = PatchEngine(vendor=self.vendor, config_writer=self.config_writer)

        return engine.patch(game, path, progress=self.progress)

    def unpatch(self, game_path: pathlib.Path | str, *, purge_vault: bool = True) -> list[pathlib.Path]:
        """
        Revert a patch and restore original Steam binaries from the vault.

        Parameters
        ----------
        game_path: `pathlib.Path | str`
            The filesystem path to the game's root directory.
        purge_vault: `bool`
            Whether to delete the backup vault after a successful restoration.

        Returns
        -------
        `list[pathlib.Path]`
            A list of files restored to their original locations.
        """
        from steamlayer_core.patching.engine import PatchEngine

        # Vendor is None because unpatching is emulator-agnostic; it only
        # cares about the files stored in the vault.
        engine = PatchEngine(vendor=None, config_writer=self.config_writer)  # type: ignore
        return engine.unpatch(pathlib.Path(game_path), purge_vault=purge_vault, progress=self.progress)

    def fetch_dlcs(self, appid: int) -> dict[int, DLCInfo]:
        """
        Hydrate DLC metadata for a known AppID.

        Results are cached on disk as ``dlcs_{appid}.json`` under *cache_dir*.
        On a cache hit the network is never touched.  On a miss, the Steam Web
        API is queried and the result is written back to disk before returning.

        Parameters
        ----------
        appid:
            Steam AppID to look up.

        Returns
        -------
        dict[int, DLCInfo]
            Mapping of DLC AppID → ``DLCInfo``.  ``DLCInfo.from_cache`` is
            ``True`` when the result was served from disk.  Returns an empty
            dict when no DLCs are found, the cache is cold, or the API is
            unreachable.
        """
        from steamlayer_core.discovery.dlc import DLCService
        from steamlayer_core.discovery.repository import AppIndexRepository
        from steamlayer_core.discovery.web import SteamWebClient

        cache_dir = self.options.cache_dir
        ttl = self.options.dlc_cache_ttl_seconds
        cache_path = pathlib.Path(cache_dir) / f"dlcs_{appid}.json"

        self.progress("fetching_dlcs", f"Hydrating DLC metadata for AppID {appid}...")

        repo = AppIndexRepository(http=self._http_client)
        web: SteamWebClientProtocol = (
            SteamWebClient(http=self._http_client) if self._http_client else _OfflineSteamWebClient()
        )
        service = DLCService(
            repo=repo,
            web=web,
            cache_path=cache_path,
            allow_network=self.allow_network and self._http_client is not None,
            ttl_seconds=ttl,
        )

        raw, from_cache = service.fetch(appid)
        return {int(k): DLCInfo(appid=int(k), name=str(v), from_cache=from_cache) for k, v in raw.items()}

    def is_patched(self, game_path: pathlib.Path | str) -> bool:
        """
        Determine if the specified directory contains an active SteamLayer patch.

        Parameters
        ----------
        game_path: `pathlib.Path | str`
            The filesystem path to the game's root directory.

        Returns
        -------
        bool
            True if a valid vault and patch signature are detected.
        """
        from steamlayer_core.patching.engine import PatchEngine

        engine = PatchEngine(vendor=None, config_writer=self.config_writer)  # type: ignore
        return engine.is_patched(pathlib.Path(game_path))

    def __enter__(self) -> SteamLayerClient:
        if self._http_client is None and self.allow_network:
            self._http_client = HTTPClient()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._http_client is not None:
            self._http_client.close()
        return


def resolve_game(
    game_path: pathlib.Path | str,
    options: SteamlayerOptions | None = None,
    *,
    allow_network: bool = True,
    on_disambiguation: DisambiguationHandler | None = None,
    on_confirmation: ConfirmationHandler | None = None,
    progress: ProgressCallback = NULL_PROGRESS,
) -> ResolvedGame:
    """
    Resolve a game directory to a Steam AppID and (optionally) its DLC list.

    Parameters
    ----------
    game_path:
        Path to the game's root directory.
    options:
        Resolution configuration.  Defaults to strict mode with network enabled.
    allow_network: bool
        Whether to allow network access for metadata hydration.
    on_disambiguation:
        Handler for ambiguous matches.  If ``None``, raises
        ``AmbiguousMatchError`` when disambiguation is needed.
    on_confirmation:
        Handler for low-confidence matches.  If ``None``, raises
        ``LowConfidenceError`` when confirmation is needed.
    progress:
        Optional progress hook for UI updates.

    Returns
    -------
    ResolvedGame
        Contains ``appid``, ``game_name``, ``source``, ``confidence``, and
        ``dlcs`` (populated if ``options.fetch_dlcs`` is True).

    Raises
    ------
    AppIDNotFoundError
        No candidate could be found.
    AmbiguousMatchError
        Tie-breaking needed but no ``on_disambiguation`` handler provided.
    LowConfidenceError
        Confirmation needed but no ``on_confirmation`` handler provided.
    """
    with SteamLayerClient(
        options=options,
        allow_network=allow_network,
        on_disambiguation=on_disambiguation,
        on_confirmation=on_confirmation,
        progress=progress,
    ) as client:
        return client.resolve(game_path)


def patch_game(
    game: ResolvedGame,
    game_path: pathlib.Path | str,
    *,
    vendor: VendorProvider,
    config_writer: ConfigWriter,
    progress: ProgressCallback = NULL_PROGRESS,
) -> PatchResult:
    """
    Apply an emulator patch and strip Steam DRM from a game directory.

    This function orchestrates a generic patching lifecycle: scanning for Steam
    API DLLs, creating backups in a local vault, running DRM removal on
    executables, and writing emulator-specific configuration files.

    The specific emulator binaries used and the format of the configuration
    files are determined by the injected ``vendor`` and the ``config_writer``.

    Parameters
    ----------
    game:
        The ``ResolvedGame`` metadata containing AppID and secondary data.
    game_path:
        Root directory of the game installation to be patched.
    vendor:
        An injected ``VendorProvider`` that supplies the emulator binaries.
    config_writer:
        ``ConfigWriter`` implementation that defines the emulator config
        format and destination.
    progress:
        Optional progress hook for UI updates.

    Returns
    -------
    PatchResult
        A summary of the operation, including the vault path and patched targets.

    Raises
    ------
    PatchError
        If no Steam API DLLs are found, I/O operations fail, or
        configuration writing fails.
    VaultError
        If a backup cannot be created or a vault already exists.
    """

    with SteamLayerClient(
        vendor=vendor,
        config_writer=config_writer,
        progress=progress,
    ) as client:
        return client.patch(game, game_path)


def fetch_dlcs(
    appid: int,
    *,
    options: SteamlayerOptions | None = None,
    allow_network: bool = True,
    progress: ProgressCallback = NULL_PROGRESS,
) -> dict[int, DLCInfo]:
    """
    Hydrate DLC metadata for a known AppID.

    Convenience wrapper around ``SteamLayerClient.fetch_dlcs()`` for
    one-shot use.  For repeated calls or shared HTTP session lifecycle,
    use ``SteamLayerClient`` directly.

    Results are cached on disk under ``options.cache_dir`` (default:
    ``~/.steamlayer/.cache``).  On a cache hit the network is never
    touched.  On a miss, the Steam Web API is queried and the result is
    written back to disk before returning.

    Parameters
    ----------
    appid:
        Steam AppID to look up.
    options:
        Resolution configuration.  Controls ``cache_dir`` and
        ``dlc_cache_ttl_seconds``.  Defaults to ``SteamlayerOptions()``.
    allow_network:
        Set to ``False`` to prevent any outbound HTTP calls.  Only a
        warm cache can produce a non-empty result in that case.
    progress:
        Optional progress hook for surfacing status to a UI.

    Returns
    -------
    dict[int, DLCInfo]
        Mapping of DLC AppID → ``DLCInfo``.  ``DLCInfo.from_cache`` is
        ``True`` when the result was served from disk.  Returns an empty
        dict when no DLCs are found, the cache is cold, or the API is
        unreachable.
    """
    with SteamLayerClient(
        options=options,
        allow_network=allow_network,
        progress=progress,
    ) as client:
        return client.fetch_dlcs(appid)


class _OfflineSteamWebClient:
    """Satisfies the SteamWebClient interface but always returns empty data."""

    def search_store(self, term: str) -> dict:
        return {}

    def get_app_details(self, appid: int) -> dict:
        return {}
