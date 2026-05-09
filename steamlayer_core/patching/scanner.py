"""
steamlayer_core.patching.scanner
=================================
Discovery of Steam API DLLs and game executables inside a game tree.

Both scanners are injected into ``PatchEngine`` and can be swapped out
independently for custom discovery logic.

Classes
-------
DLLScanner
    Recursively locates ``steam_api.dll`` / ``steam_api64.dll`` up to a
    configurable depth, skipping the vault directory and deep asset trees.
ExeScanner
    Locates plausible main-game executables for Steamless processing.
    Applies a junk-pattern filter to exclude crash reporters, redists,
    anti-cheat processes, and other non-game binaries.

Constants
---------
DLL_SCAN_MAX_DEPTH
    Default depth limit for ``DLLScanner``.
EXE_SCAN_MAX_DEPTH
    Default depth limit for ``ExeScanner``.
"""

from __future__ import annotations

import logging
import pathlib

from steamlayer_core.constants import STEAM_API_DLLS, VAULT_DIR_NAME
from steamlayer_core.patching.models import ExeTarget, PatchTarget

log = logging.getLogger("steamlayer_core.patching.scanner")


#: How many directory levels below the game root we'll look for DLLs.
#: Beyond this depth we're probably inside game data, not the engine.
DLL_SCAN_MAX_DEPTH = 4
EXE_SCAN_MAX_DEPTH = 4


class DLLScanner:
    """
    Recursively locates Steam API DLLs in a game directory.

    Rules
    -----
    - Files inside the vault directory are always skipped.
    - Files deeper than ``max_depth`` levels are skipped (likely game assets,
      not engine DLLs).
    - Results are sorted by depth, shallowest first, so callers can treat
      the first entry as the "primary" DLL location.

    Parameters
    ----------
    max_depth:
        Maximum directory depth below the game root to search.
        Default: ``DLL_SCAN_MAX_DEPTH`` (4).
    """

    def __init__(self, max_depth: int = DLL_SCAN_MAX_DEPTH) -> None:
        self.max_depth = max_depth

    def scan(self, game_path: pathlib.Path) -> list[PatchTarget]:
        """
        Walk *game_path* and return every Steam API DLL found.

        Parameters
        ----------
        game_path:
            Root of the game installation.

        Returns
        -------
        list[PatchTarget]
            DLLs sorted by depth (shallowest first), then by architecture.
        """
        targets: list[PatchTarget] = []

        for arch, filename in STEAM_API_DLLS.items():
            for dll_path in sorted(game_path.rglob(filename)):
                if VAULT_DIR_NAME in dll_path.parts:
                    log.debug("Skipping vaulted DLL: %s", dll_path)
                    continue

                try:
                    depth = len(dll_path.relative_to(game_path).parts) - 1
                except ValueError:
                    continue

                if depth > self.max_depth:
                    log.debug("Skipping DLL at depth %d (max %d): %s", depth, self.max_depth, dll_path)
                    continue

                targets.append(PatchTarget(dll_path=dll_path, architecture=arch))
                log.info("Found %s DLL at depth %d: %s", arch, depth, dll_path)

        # Stable sort: shallowest first, then x86 before x64 within same depth.
        targets.sort(key=lambda t: (len(t.dll_path.parts), t.architecture))
        return targets


class ExeScanner:
    """
    Locates the main game executable(s) for Steamless processing.

    Heuristics
    ----------
    - Only searches ``max_depth`` levels below the game root (default: 4).
    - Skips the vault directory.
    - Filters out well-known non-game executables (crash handlers, redists,
      launchers, anti-cheat processes, etc.) via ``JUNK_PATTERNS``.
    - When a ``primary_dll_dir`` hint is provided, executables in that
      directory are ranked first (the main DLL and main exe are usually
      co-located).
    - Within the same directory tier, candidates are sorted by file size
      descending — the main executable is almost always the largest.

    Parameters
    ----------
    max_depth:
        Maximum directory depth to search.  Default: ``EXE_SCAN_MAX_DEPTH``.
    """

    #: Glob-style patterns matched case-insensitively against the bare filename.
    #: Any exe whose name matches one of these is treated as junk.
    JUNK_PATTERNS: list[str] = [
        "unins*",  # Inno Setup uninstallers
        "setup*",  # generic setup launchers
        "install*",  # generic install helpers
        "dxsetup*",  # DirectX redistributable
        "vcredist*",  # MSVC redistributable
        "vc_redist*",
        "dotnetfx*",  # .NET Framework redistributable
        "directx*",
        "crashreporter*",  # crash reporter processes
        "crashhandler*",
        "unitycrashhandler*",
        "ue4prereqsetup*",  # Unreal Engine prerequisites
        "ue5prereqsetup*",
        "redist*",  # miscellaneous redistributables
        "easyanticheat*",  # anti-cheat processes
        "battleye*",
        "be_service*",
        "eac_launcher*",
        "galaxyclient*",  # GOG Galaxy launcher helper
        "gog*",
        "steamwebhelper*",  # Steam internal process
        "steam*helper*",
        "upc*",  # Ubisoft Connect
        "uplay*",
        "legacylauncher*",
    ]

    def __init__(self, max_depth: int = EXE_SCAN_MAX_DEPTH) -> None:
        self.max_depth = max_depth

    def scan(
        self,
        game_path: pathlib.Path,
        *,
        primary_dll_dir: pathlib.Path | None = None,
    ) -> list[ExeTarget]:
        """
        Return all plausible main-game executables under *game_path*.

        Parameters
        ----------
        game_path:
            Root of the game installation.
        primary_dll_dir:
            Directory containing the primary Steam API DLL (hint).
            Executables here are promoted to the front of the result list.

        Returns
        -------
        list[ExeTarget]
            Candidates sorted so the most-likely main exe comes first:
            1. Executables co-located with the primary DLL, largest first.
            2. Remaining executables, largest first.
        """
        import fnmatch

        candidates: list[ExeTarget] = []
        for exe_path in game_path.rglob("*.exe"):
            if VAULT_DIR_NAME in exe_path.parts:
                continue

            try:
                depth = len(exe_path.relative_to(game_path).parts) - 1
            except ValueError:
                continue

            if depth > self.max_depth:
                log.debug("Skipping deep exe (%d levels): %s", depth, exe_path)
                continue

            name_lower = exe_path.name.lower()
            if any(fnmatch.fnmatch(name_lower, pat) for pat in self.JUNK_PATTERNS):
                log.debug("Skipping junk exe: %s", exe_path.name)
                continue

            candidates.append(ExeTarget(exe_path=exe_path))

        def sort_key(t: ExeTarget) -> tuple[int, int]:
            tier = 0 if (primary_dll_dir and t.exe_path.parent == primary_dll_dir) else 1
            try:
                size = -t.exe_path.stat().st_size
            except OSError:
                size = 0
            return (tier, size)

        candidates.sort(key=sort_key)
        log.info("Found %d exe candidate(s): %s", len(candidates), [t.name for t in candidates])
        return candidates
