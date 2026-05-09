from __future__ import annotations

import pathlib

# --- SteamLayer Internal Policy ---
VAULT_DIR_NAME = "__steamlayer_vault__"
DEFAULT_CACHE_DIR = pathlib.Path.home() / ".steamlayer" / ".cache"
DEFAULT_CACHE_TTL = 86_400 * 7

# --- Steam Environment Metadata ---
STEAM_API_DLLS: dict[str, str] = {
    "x86": "steam_api.dll",
    "x64": "steam_api64.dll",
}
