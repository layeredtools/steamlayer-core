"""
steamlayer_core.patching.config
=================================
Minimal ``ConfigWriter`` Implementation for goldberg; Only handles DLCs.
Writes the ``steam_settings/`` directory consumed by the Goldberg emulator.

Goldberg reads its configuration from a directory co-located with the
patched DLL.  This module owns the exact file names and formats that
Goldberg expects so they are never scattered across the codebase.

Files written
-------------
``steam_appid.txt``
    The game's numeric AppID, bare (e.g. ``620``).
``configs.app.ini``
    One ``<appid>=<name>`` line per DLC, sorted by AppID.
    Omitted entirely when the game has no DLCs.

Classes
-------
ConfigWriter
    Stateless writer — construct once, call ``write()`` as many times as
    needed.  All failures raise ``PatchError``.
"""

from __future__ import annotations

import logging
import pathlib

from steamlayer_core.domain.exceptions import PatchError
from steamlayer_core.domain.models import DLCInfo

log = logging.getLogger("steamlayer_core.patching.config")


class GoldbergConfigWriter:
    """
    Minimal ``ConfigWriter`` Implementation for goldberg; Only handles DLCs.
    Writes the ``steam_settings/`` directory consumed by the gbe_fork
    Goldberg emulator (configs.app.ini format, schema v2+).

    Files written
    -------------
    ``steam_appid.txt``
        The game's numeric AppID, bare (e.g. ``620``).
        Still read by the emulator as a fallback.
    ``configs.app.ini``
        INI file consumed by gbe_fork.  The ``[app::dlcs]`` section lists
        every DLC as ``id=name`` with ``unlock_all=0``.
        Omitted entirely when the game has no DLCs.
    """

    def write(
        self,
        dll_dir: pathlib.Path,
        appid: int,
        dlcs: dict[int, DLCInfo],
    ) -> None:
        config_path = dll_dir / "steam_settings"
        try:
            config_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise PatchError(f"Cannot create config directory '{config_path}': {e}") from e

        self._write_appid(config_path, appid)

        if dlcs:
            self._write_app_ini(config_path, dlcs)

        log.info(
            "Config written to '%s' (%d DLC entr%s).",
            config_path,
            len(dlcs),
            "y" if len(dlcs) == 1 else "ies",
        )

    def _write_appid(self, config_path: pathlib.Path, appid: int) -> None:
        try:
            (config_path / "steam_appid.txt").write_text(str(appid), encoding="utf-8")
        except OSError as e:
            raise PatchError(f"Failed to write steam_appid.txt: {e}") from e

    def _write_app_ini(self, config_path: pathlib.Path, dlcs: dict[int, DLCInfo]) -> None:
        lines = [
            "[app::dlcs]",
            "# 0=report only the DLCs listed below",
            "unlock_all=0",
        ]
        lines += [f"{dlc_id}={info.name}" for dlc_id, info in sorted(dlcs.items())]

        try:
            (config_path / "configs.app.ini").write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as e:
            raise PatchError(f"Failed to write configs.app.ini: {e}") from e
