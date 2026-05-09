"""
steamlayer_core.patching.vendors
=================================
Concrete ``VendorProvider`` implementations shipped with the library.

The ``PatchEngine`` never acquires binaries itself — it delegates to an
injected ``VendorProvider``.  This module provides both a generic
implementation for any emulator and a convenience subclass pre-wired for
the Goldberg emulator (gbe_fork).

Classes
-------
``LocalVendorProvider``
    Generic provider — point it at the right directories for each
    architecture and it works with any emulator.
``GoldbergLocalVendorProvider``
    Convenience subclass pre-wired for the standard gbe_fork directory
    layout.  Use this if you're using Goldberg and don't need a custom
    directory structure.

Acquiring binaries
------------------
This library does **not** download or bundle vendor binaries.  You are
responsible for obtaining them and placing them in the correct directories,
tho you could implement a vendor that automatically downloads the files and
serves them to the engine.

- Goldberg (gbe_fork): https://github.com/Detanup01/gbe_fork/releases
- Steamless: https://github.com/atom0s/Steamless/releases

Steamless is optional — if the executable path is absent or ``None``,
the patch engine skips DRM stripping without error.

Usage
-----
Generic (any emulator)::

    from steamlayer_core.patching.vendors import LocalVendorProvider

    vendor = LocalVendorProvider(
        x64_dir=Path("./myemu/x64"),
        x86_dir=Path("./myemu/x86"),
        steamless_exe=Path("./steamless/Steamless.CLI.exe"),
    )

Goldberg shorthand::

    from steamlayer_core.patching.vendors import GoldbergLocalVendorProvider

    vendor = GoldbergLocalVendorProvider(Path("./vendors"))

Extensibility
-------------
For custom binary acquisition (e.g. downloading from a specific release,
version pinning, extraction from an archive), implement the
``VendorProvider`` protocol directly and inject it into ``PatchEngine``.
``LocalVendorProvider`` is the reference implementation, not the ceiling.
"""

from __future__ import annotations

import pathlib

from steamlayer_core.constants import STEAM_API_DLLS
from steamlayer_core.domain.exceptions import EmulatorBinaryError
from steamlayer_core.protocols import VendorProvider


class LocalVendorProvider(VendorProvider):
    """
    A ``VendorProvider`` that serves emulator binaries from user-managed
    local directories.

    Architecture directories are specified explicitly at construction time,
    so the provider is agnostic to the emulator's directory layout.

    Parameters
    ----------
    x64_dir:
        Directory containing the x64 replacement ``steam_api64.dll``.
    x86_dir:
        Directory containing the x86 replacement ``steam_api.dll``.
    steamless_exe:
        Path to the Steamless CLI executable.  Pass ``None`` to disable
        DRM stripping entirely.
    """

    def __init__(
        self,
        *,
        x64_dir: pathlib.Path,
        x86_dir: pathlib.Path,
        steamless_exe: pathlib.Path | None = None,
    ) -> None:
        self._dirs = {"x64": x64_dir, "x86": x86_dir}
        self._steamless_exe = steamless_exe

    def get_emulator_dll(self, architecture: str) -> pathlib.Path:
        directory = self._dirs.get(architecture)
        if directory is None:
            raise EmulatorBinaryError(f"steam_api ({architecture})")

        dll_name = STEAM_API_DLLS.get(architecture)
        if dll_name is None:
            raise EmulatorBinaryError(f"steam_api ({architecture})")

        path = directory / dll_name
        if not path.exists():
            raise EmulatorBinaryError(path.name)
        return path

    def get_steamless_exe(self) -> pathlib.Path | None:
        return self._steamless_exe if (self._steamless_exe and self._steamless_exe.exists()) else None


class GoldbergLocalVendorProvider(LocalVendorProvider):
    """
    Convenience subclass of ``LocalVendorProvider`` pre-wired for the
    standard gbe_fork directory layout.

    Equivalent to constructing ``LocalVendorProvider`` manually with the
    paths ``goldberg/regular/x64/``, ``goldberg/regular/x86/``, and
    ``steamless/Steamless.CLI.exe`` under *vendors_dir*.

    Parameters
    ----------
    vendors_dir:
        Root directory containing ``goldberg/`` and optionally
        ``steamless/`` subdirectories.

    Example
    -------
    ::

        vendor = GoldbergLocalVendorProvider(Path("./vendors"))
        engine = PatchEngine(vendor=vendor, config_writer=GoldbergConfigWriter())
        engine.patch(game, game_path)
    """

    def __init__(self, vendors_dir: pathlib.Path) -> None:
        super().__init__(
            x64_dir=vendors_dir / "goldberg" / "regular" / "x64",
            x86_dir=vendors_dir / "goldberg" / "regular" / "x86",
            steamless_exe=vendors_dir / "steamless" / "Steamless.CLI.exe",
        )
