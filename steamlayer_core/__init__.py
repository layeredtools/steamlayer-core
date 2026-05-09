"""
steamlayer-core
===============
A headless, I/O-free library for Steam game identification, DLC hydration,
and emulator-agnostic patching.

Quick start
-----------
::

    from pathlib import Path
    from steamlayer_core import SteamLayerClient, GoldbergLocalVendorProvider, GoldbergConfigWriter

    with SteamLayerClient(
        vendor=GoldbergLocalVendorProvider(Path("./vendors")),
        config_writer=GoldbergConfigWriter(),
    ) as client:
        game = client.resolve(Path("/games/Portal 2"))
        result = client.patch(game, Path("/games/Portal 2"))
        print(result.targets_patched)

Public surface
--------------
Only the names imported here are considered stable API.  Everything else is
an implementation detail subject to change without notice.
"""

from steamlayer_core.adapters import (
    FixedConfirmationHandler,
    FixedDisambiguationHandler,
)
from steamlayer_core.api import SteamLayerClient, fetch_dlcs, patch_game, resolve_game
from steamlayer_core.domain.exceptions import (
    AmbiguousMatchError,
    AppIDNotFoundError,
    ConfigurationError,
    DLCCacheError,
    DLCHydrationError,
    EmulatorBinaryError,
    LowConfidenceError,
    PatchError,
    SteamLayerError,
    VaultError,
)
from steamlayer_core.domain.models import (
    DiscoveryResult,
    DLCInfo,
    ResolutionSource,
    ResolvedGame,
    SteamlayerOptions,
)
from steamlayer_core.events import AmbiguousMatchEvent, LowConfidenceEvent
from steamlayer_core.patching.config import GoldbergConfigWriter
from steamlayer_core.patching.engine import PatchEngine
from steamlayer_core.patching.models import PatchResult, PatchTarget
from steamlayer_core.patching.vendors import GoldbergLocalVendorProvider, LocalVendorProvider
from steamlayer_core.protocols import (
    ConfigWriter,
    ConfirmationHandler,
    DisambiguationHandler,
    ProgressCallback,
    VendorProvider,
)

__all__ = [
    # Client
    "SteamLayerClient",
    # API functions
    "resolve_game",
    "patch_game",
    "fetch_dlcs",
    # Models
    "SteamlayerOptions",
    "ResolvedGame",
    "DiscoveryResult",
    "ResolutionSource",
    "DLCInfo",
    # Events
    "AmbiguousMatchEvent",
    "LowConfidenceEvent",
    # Exceptions
    "SteamLayerError",
    "AppIDNotFoundError",
    "AmbiguousMatchError",
    "LowConfidenceError",
    "PatchError",
    "VaultError",
    "EmulatorBinaryError",
    "DLCHydrationError",
    "DLCCacheError",
    "ConfigurationError",
    # Protocols
    "ConfigWriter",
    "ConfirmationHandler",
    "DisambiguationHandler",
    "ProgressCallback",
    "VendorProvider",
    # Adapters
    "FixedDisambiguationHandler",
    "FixedConfirmationHandler",
    # Vendors
    "LocalVendorProvider",
    "GoldbergLocalVendorProvider",
    # Patching
    "PatchEngine",
    "PatchResult",
    "PatchTarget",
    # Config writers
    "GoldbergConfigWriter",
]
