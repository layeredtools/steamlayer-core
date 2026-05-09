"""
steamlayer_core.patching.engine
================================
Orchestrates the full emulator patching lifecycle.

Lifecycle
---------
1. **Scan**       — ``DLLScanner`` walks the game tree for ``steam_api*.dll``.
2. **Vault**      — ``VaultManager`` backs up originals with a JSON manifest.
3. **Replace**    — Emulator DLLs (sourced via ``VendorProvider``) overwrite
                    the originals in-place.
4. **Configure**  — ``ConfigWriter`` writes emulator configuration files.

Design notes
------------
- ``PatchEngine`` is entirely emulator-agnostic — it never knows which
  emulator is being used, where its binaries live, or what format its
  config files take.  All of that is delegated to the injected
  ``VendorProvider`` and ``ConfigWriter``.  This lets any emulator be
  supported without touching the engine.
- No ``input()`` or ``print()`` calls anywhere in this module.
- All errors are typed (see ``steamlayer_core.domain.exceptions``).
- ``unpatch()`` is the inverse of ``patch()``; the vault manifest makes it
  unambiguous even if the user renames files after patching.
"""

from __future__ import annotations

import logging
import pathlib
import shutil

from steamlayer_core.constants import VAULT_DIR_NAME
from steamlayer_core.domain.exceptions import PatchError, VaultError
from steamlayer_core.domain.models import ResolvedGame
from steamlayer_core.patching.models import ExeTarget, PatchResult, PatchTarget
from steamlayer_core.patching.scanner import DLLScanner, ExeScanner
from steamlayer_core.patching.vault import VaultManager
from steamlayer_core.protocols import NULL_PROGRESS, ConfigWriter, ProgressCallback, VendorProvider

log = logging.getLogger("steamlayer_core.patching.engine")


class PatchEngine:
    """
    Orchestrates the full patching and unpatching lifecycle.

    The engine is emulator-agnostic: inject any ``VendorProvider`` and
    ``ConfigWriter`` and the engine will use them transparently.  All
    sub-components (scanner, vault, config writer) are also injectable
    for testing.

    Parameters
    ----------
    vendor:
        Supplies paths to emulator DLLs and auxiliary tools.
    scanner:
        Locates Steam API DLLs in the game tree.
        Defaults to ``DLLScanner()``.
    exe_scanner:
        Locates the main game executable(s) for DRM stripping.
        Defaults to ``ExeScanner()``.  Pass ``None`` to disable exe scanning.
    config_writer:
        Writes emulator configuration files next to the patched DLLs.
    vault_dir_name:
        Name of the backup subdirectory inside the game root.
        Defaults to ``VAULT_DIR_NAME``.
    config_dir_name:
        Name of the config subdirectory placed next to the primary DLL.
        Defaults to ``CONFIG_DIR_NAME``.
    """

    def __init__(
        self,
        vendor: VendorProvider,
        config_writer: ConfigWriter,
        *,
        scanner: DLLScanner | None = None,
        exe_scanner: ExeScanner | None = None,
        vault_dir_name: str = VAULT_DIR_NAME,
    ) -> None:
        self._vendor = vendor
        self._scanner = scanner or DLLScanner()
        self._exe_scanner: ExeScanner | None = exe_scanner if exe_scanner is not None else ExeScanner()
        self._config_writer = config_writer
        self._vault_dir_name = vault_dir_name

    def _run_steamless(self, exe_target: ExeTarget) -> bool:
        """
        Run Steamless on a single executable.

        Steamless writes a ``<name>.exe.unpacked`` file alongside the original.
        On success this method atomically replaces the original with the
        unpacked version.

        Parameters
        ----------
        exe_target:
            The executable to process.

        Returns
        -------
        bool
            ``True`` if Steamless ran successfully and the original was replaced.
            ``False`` on any failure — the original is left untouched.
        """
        import subprocess

        steamless_exe = self._vendor.get_steamless_exe()
        if steamless_exe is None:
            log.debug("Steamless not found at '%s' — skipping DRM strip.", steamless_exe)
            return False

        unpacked = exe_target.exe_path.with_name(exe_target.exe_path.name + ".unpacked.exe")

        try:
            result = subprocess.run(
                [str(steamless_exe), "--quiet", "--keepbind", str(exe_target.exe_path)],
                capture_output=True,
                timeout=120,
            )

            if result.returncode != 0:
                stdout = result.stdout.decode(errors="replace")

                # Steamless exit code 1 is a catch-all for both "no DRM found" and genuine
                # failures. The only way to distinguish them is stdout parsing. This string
                # has been stable since 2022 — if Steamless ever changes it, update here.
                if "All unpackers failed to unpack file" in stdout:
                    log.debug("Steamless found no DRM in '%s' — skipping.", exe_target.name)
                else:
                    log.warning(
                        "Steamless exited with code %d for '%s': %s",
                        result.returncode,
                        exe_target.name,
                        stdout.strip(),
                    )
                return False

            if not unpacked.exists():
                log.warning("Steamless succeeded but output file not found: '%s'", unpacked)
                return False

            unpacked.replace(exe_target.exe_path)
            log.info("Steamless stripped DRM from '%s'.", exe_target.name)
            return True

        except subprocess.TimeoutExpired:
            log.warning("Steamless timed out processing '%s'.", exe_target.name)
            unpacked.unlink(missing_ok=True)
            return False

        except OSError as e:
            log.warning("Failed to run Steamless on '%s': %s", exe_target.name, e)
            return False

    def patch(
        self,
        game: ResolvedGame,
        game_path: pathlib.Path,
        *,
        progress: ProgressCallback = NULL_PROGRESS,
    ) -> PatchResult:
        """
        Apply an emulator patch to *game_path*.

        Parameters
        ----------
        game:
            Resolved game metadata (AppID, DLC map, display name, …).
        game_path:
            Root directory of the game installation.
        progress:
            Optional hook for surfacing progress steps to a UI.

        Returns
        -------
        PatchResult
            Summary of what was patched and where artefacts were written.

        Raises
        ------
        PatchError
            On I/O failures during DLL replacement or config writing.
        VaultError
            When backup creation fails.
        EmulatorBinaryError
            When the vendor cannot supply a required emulator DLL.
        """
        result = PatchResult(game_path=game_path, appid=game.appid)

        progress("scan_dlls", f"Scanning '{game_path.name}' for Steam API DLLs…")
        targets = self._scanner.scan(game_path)

        if not targets:
            raise PatchError(f"No steam_api*.dll found in '{game_path}'. Is this the correct game directory?")

        log.info(
            "Found %d DLL target(s): %s",
            len(targets),
            [t.dll_path.name for t in targets],
        )

        exe_targets: list[ExeTarget] = []
        if self._exe_scanner is not None:
            progress("scan_exes", "Scanning for game executables…")
            primary_dll_dir = targets[0].dll_path.parent
            exe_targets = self._exe_scanner.scan(game_path, primary_dll_dir=primary_dll_dir)

        result.exe_targets = exe_targets

        vault_path = game_path / self._vault_dir_name
        vault = VaultManager(vault_path)

        if vault.exists:
            # Protect the user: never overwrite an existing vault because it
            # may contain their original (unpatched) Steam DLLs.
            log.warning(
                "Vault already exists at '%s'. The game may already be patched. "
                "Skipping backup and DRM strip to avoid overwriting originals.",
                vault_path,
            )
        else:
            n_files = len(targets) + len(exe_targets)
            progress("backup", f"Backing up {n_files} original file(s)…")
            vault.backup(targets, game_path, exe_targets=exe_targets if exe_targets else None)

            if exe_targets:
                progress("steamless", "Stripping Steam DRM from executable(s)…")
                stripped = sum(1 for exe in exe_targets if self._run_steamless(exe))
                if stripped:
                    log.info("Steamless stripped %d/%d executable(s).", stripped, len(exe_targets))
                else:
                    log.debug("Steamless made no changes.")

        result.vault_path = vault_path

        progress("replace_dlls", "Replacing Steam API DLLs with emulator binaries…")
        patched: list[PatchTarget] = []
        for target in targets:
            emulator_dll = self._vendor.get_emulator_dll(target.architecture)

            try:
                shutil.copy2(emulator_dll, target.dll_path)
            except OSError as e:
                raise PatchError(f"Failed to replace '{target.dll_path}' with emulator DLL '{emulator_dll}': {e}")

            patched.append(target)
            log.info(
                "Replaced %s (%s) ← %s",
                target.dll_path.name,
                target.architecture,
                emulator_dll.name,
            )

        result.targets_patched = patched

        progress("write_config", f"Writing emulator config for AppID {game.appid}…")
        for patched_target in patched:
            self._config_writer.write(
                patched_target.dll_path.parent,
                game.appid,
                game.dlcs if game.dlcs else {},
            )
        result.config_path = patched[0].dll_path.parent

        progress("patch_complete", f"Done — {len(patched)} DLL(s) patched.")
        log.info(
            "Patch complete for AppID %d (%d DLL(s) replaced).",
            game.appid,
            len(patched),
        )

        return result

    def unpatch(
        self,
        game_path: pathlib.Path,
        *,
        purge_vault: bool = True,
        progress: ProgressCallback = NULL_PROGRESS,
    ) -> list[pathlib.Path]:
        """
        Restore original DLLs from the vault, undoing a previous ``patch()``.

        Parameters
        ----------
        game_path:
            Root directory of the game installation.
        purge_vault:
            When ``True`` (default), delete the vault directory after
            restoring so the game directory is left clean.
        progress:
            Optional progress hook.

        Returns
        -------
        list[pathlib.Path]
            Absolute paths of all restored files.

        Raises
        ------
        VaultError
            When the vault is absent, corrupt, or a restore fails.
        """
        vault_path = game_path / self._vault_dir_name
        vault = VaultManager(vault_path)

        if not vault.exists:
            raise VaultError(
                f"No vault found at '{vault_path}'. Is the game actually patched?",
                vault_path=str(vault_path),
            )

        progress("restore_dlls", "Restoring original Steam API DLLs from vault…")
        restored = vault.restore()
        log.info("Restored %d DLL(s).", len(restored))

        if purge_vault:
            progress("purge_vault", "Cleaning up vault…")
            vault.purge()

        progress("unpatch_complete", f"Done — {len(restored)} file(s) restored.")
        return restored

    def is_patched(self, game_path: pathlib.Path) -> bool:
        """
        Return ``True`` when *game_path* appears to be patched.

        The check is based solely on vault presence — it does not inspect
        the DLL contents.

        Parameters
        ----------
        game_path:
            Root directory of the game installation.
        """
        return VaultManager(game_path / self._vault_dir_name).exists
