"""
steamlayer_core.patching.models
================================
Data classes shared across the patching subsystem.

These types are the currency passed between ``DLLScanner``, ``ExeScanner``,
``VaultManager``, and ``PatchEngine`` — they carry no behaviour, only data.

Classes
-------
PatchTarget
    A single Steam API DLL discovered in the game tree.
ExeTarget
    A game executable candidate for Steamless DRM stripping.
PatchResult
    Immutable summary returned by ``PatchEngine.patch()``.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PatchTarget:
    """
    A single Steam API DLL discovered in the game tree.

    Attributes
    ----------
    dll_path:
        Absolute path to the DLL on disk.
    architecture:
        ``"x86"`` or ``"x64"``, inferred from the filename.
    """

    dll_path: pathlib.Path
    architecture: str


@dataclass(frozen=True)
class ExeTarget:
    """
    A game executable that may need to be processed by Steamless.

    Attributes
    ----------
    exe_path:
        Absolute path to the executable on disk.
    """

    exe_path: pathlib.Path

    @property
    def name(self) -> str:
        """Filename component, e.g. ``"game.exe"``."""
        return self.exe_path.name


@dataclass
class PatchResult:
    """
    Summary of a successful ``PatchEngine.patch()`` run.

    Attributes
    ----------
    game_path:
        Root directory that was patched.
    appid:
        Steam AppID written to the Goldberg config.
    targets_patched:
        Every DLL that was replaced during this run.
    exe_targets:
        Executables backed up to the vault (ready for Steamless).
    vault_path:
        Directory where originals are stored for later restoration.
    config_path:
        ``steam_settings/`` directory written for Goldberg.
    """

    game_path: pathlib.Path
    appid: int
    targets_patched: list[PatchTarget] = field(default_factory=list)
    exe_targets: list[ExeTarget] = field(default_factory=list)
    vault_path: pathlib.Path | None = None
    config_path: pathlib.Path | None = None
