from __future__ import annotations

import json
import logging
import pathlib
import shutil
import time

from steamlayer_core.domain.exceptions import VaultError
from steamlayer_core.patching.models import ExeTarget, PatchTarget

log = logging.getLogger("steamlayer_core.patching.vault")


class VaultManager:
    """
    Atomic backup and restore of original DLLs and executables.

    The vault is a directory containing:
    - Original DLLs and executables, preserving the relative directory structure.
    - A ``manifest.json`` (schema v2) recording original paths and metadata.

    The manifest makes restoration unambiguous even if the user rearranges
    files after patching.  Schema v1 manifests (DLLs only) are read correctly
    by ``restore()`` — ``exe_entries`` simply defaults to ``[]``.

    Parameters
    ----------
    vault_path:
        Directory that will hold backups.  Created on first ``backup()`` call.
    """

    MANIFEST_FILE = "manifest.json"
    SCHEMA_VERSION = 2

    def __init__(self, vault_path: pathlib.Path) -> None:
        self.vault_path = vault_path

    @property
    def exists(self) -> bool:
        """``True`` when a valid manifest is present in the vault directory."""
        return (self.vault_path / self.MANIFEST_FILE).exists()

    def backup(
        self,
        targets: list[PatchTarget],
        game_path: pathlib.Path,
        *,
        exe_targets: list[ExeTarget] | None = None,
    ) -> None:
        """
        Copy every *target* DLL (and optionally every *exe_target*) into the
        vault, preserving relative directory structure.

        Parameters
        ----------
        targets:
            Steam API DLL files to back up.
        game_path:
            Game root — used to compute relative vault paths.
        exe_targets:
            Game executables to back up alongside the DLLs.  Pass ``None``
            (default) to skip exe backup.

        Raises
        ------
        VaultError
            On any I/O failure.
        """
        exe_targets = exe_targets or []

        if not targets and not exe_targets:
            log.info("No targets supplied — nothing to back up.")
            return

        try:
            self.vault_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise VaultError(
                f"Cannot create vault directory '{self.vault_path}': {e}",
                vault_path=str(self.vault_path),
            ) from e

        dll_entries: list[dict] = []
        for target in targets:
            vault_relative = self._relative(target.dll_path, game_path)
            dest = self.vault_path / vault_relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(target.dll_path, dest)
            except OSError as e:
                raise VaultError(
                    f"Failed to back up '{target.dll_path}': {e}",
                    vault_path=str(self.vault_path),
                ) from e
            dll_entries.append(
                {
                    "original_path": str(target.dll_path),
                    "vault_relative": str(vault_relative),
                    "architecture": target.architecture,
                }
            )
            log.info("Backed up DLL %s → %s", target.dll_path.name, dest)

        exe_entries: list[dict] = []
        for exe in exe_targets:
            vault_relative = self._relative(exe.exe_path, game_path)
            dest = self.vault_path / vault_relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(exe.exe_path, dest)
            except OSError as e:
                raise VaultError(
                    f"Failed to back up '{exe.exe_path}': {e}",
                    vault_path=str(self.vault_path),
                ) from e
            exe_entries.append(
                {
                    "original_path": str(exe.exe_path),
                    "vault_relative": str(vault_relative),
                }
            )
            log.info("Backed up exe  %s → %s", exe.name, dest)

        self._write_manifest(game_path, dll_entries, exe_entries)

    def restore(self) -> list[pathlib.Path]:
        """
        Copy every backed-up file (DLLs *and* executables) back to its
        original location.

        Returns
        -------
        list[pathlib.Path]
            Absolute paths of all successfully restored files.

        Raises
        ------
        VaultError
            When the manifest is absent or corrupt, or on any I/O failure.
        """
        manifest = self._read_manifest()
        restored: list[pathlib.Path] = []

        all_entries = manifest.get("entries", []) + manifest.get("exe_entries", [])
        for entry in all_entries:
            src = self.vault_path / entry["vault_relative"]
            dest = pathlib.Path(entry["original_path"])

            if not src.exists():
                log.warning("Vault file missing, skipping: %s", src)
                continue

            try:
                shutil.copy2(src, dest)
                restored.append(dest)
                log.info("Restored %s → %s", src.name, dest)
            except OSError as e:
                raise VaultError(
                    f"Failed to restore '{dest}': {e}",
                    vault_path=str(self.vault_path),
                ) from e

        return restored

    def purge(self) -> None:
        """
        Delete the vault directory entirely.

        Called after a successful ``restore()`` to leave no trace.
        Failures are logged as warnings, not raised, because the game is
        already in a good state at this point.
        """
        try:
            shutil.rmtree(self.vault_path)
            log.info("Vault purged: %s", self.vault_path)
        except OSError as e:
            log.warning("Could not purge vault '%s': %s", self.vault_path, e)

    def _write_manifest(
        self,
        game_path: pathlib.Path,
        dll_entries: list[dict],
        exe_entries: list[dict] | None = None,
    ) -> None:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "created_at": int(time.time()),
            "game_path": str(game_path),
            "entries": dll_entries,
            "exe_entries": exe_entries or [],
        }
        path = self.vault_path / self.MANIFEST_FILE
        try:
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as e:
            raise VaultError(
                f"Failed to write vault manifest: {e}",
                vault_path=str(self.vault_path),
            ) from e

    def _read_manifest(self) -> dict:
        path = self.vault_path / self.MANIFEST_FILE
        if not path.exists():
            raise VaultError(
                f"No vault manifest at '{path}' — was the game ever patched?",
                vault_path=str(self.vault_path),
            )
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            raise VaultError(
                f"Corrupt vault manifest '{path}': {e}",
                vault_path=str(self.vault_path),
            ) from e

    @staticmethod
    def _relative(path: pathlib.Path, base: pathlib.Path) -> pathlib.Path:
        try:
            return path.relative_to(base)
        except ValueError as e:
            raise VaultError(
                f"File '{path}' is outside game root '{base}'",
                vault_path=str(base),
            ) from e
