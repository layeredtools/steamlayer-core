"""
steamlayer_core.patching
========================
Game-patching subsystem — replaces Steam API DLLs with the Goldberg
emulator and writes the required config files.

Public surface
--------------
Only the names imported here are considered stable API.
"""

from steamlayer_core.patching.config import (
    GoldbergConfigWriter as GoldbergConfigWriter,
)
from steamlayer_core.patching.engine import (
    PatchEngine as PatchEngine,
)
from steamlayer_core.patching.models import (
    ExeTarget as ExeTarget,
)
from steamlayer_core.patching.models import (
    PatchResult as PatchResult,
)
from steamlayer_core.patching.models import (
    PatchTarget as PatchTarget,
)
from steamlayer_core.patching.scanner import (
    DLL_SCAN_MAX_DEPTH as DLL_SCAN_MAX_DEPTH,
)
from steamlayer_core.patching.scanner import (
    EXE_SCAN_MAX_DEPTH as EXE_SCAN_MAX_DEPTH,
)
from steamlayer_core.patching.scanner import (
    DLLScanner as DLLScanner,
)
from steamlayer_core.patching.scanner import (
    ExeScanner as ExeScanner,
)
from steamlayer_core.patching.vault import (
    VaultManager as VaultManager,
)
from steamlayer_core.patching.vendors import (
    GoldbergLocalVendorProvider as GoldbergLocalVendorProvider,
)
from steamlayer_core.protocols import (
    ConfigWriter as ConfigWriter,
)
from steamlayer_core.protocols import (
    VendorProvider as VendorProvider,
)

__all__ = [
    "VendorProvider",
    "GoldbergLocalVendorProvider",
    "PatchEngine",
    "PatchResult",
    "PatchTarget",
    "ExeTarget",
    "DLLScanner",
    "ExeScanner",
    "VaultManager",
    "ConfigWriter",
    "GoldbergConfigWriter",
    "DLL_SCAN_MAX_DEPTH",
    "EXE_SCAN_MAX_DEPTH",
]
