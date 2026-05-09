from __future__ import annotations

import json
import logging
import pathlib
import time
from collections.abc import Callable
from typing import Any

from steamlayer_core.constants import DEFAULT_CACHE_TTL
from steamlayer_core.http_client import NetworkError
from steamlayer_core.protocols import HTTPClientProtocol

log = logging.getLogger("steamlayer.discovery.repository")


class AppIndexRepository:
    APP_LIST_URL = "https://raw.githubusercontent.com/jsnli/steamappidlist/refs/heads/master/data/games_appid.json"
    DLC_LIST_URL = "https://raw.githubusercontent.com/jsnli/steamappidlist/refs/heads/master/data/dlc_appid.json"

    def __init__(
        self,
        http: HTTPClientProtocol | None,
        data_dir: pathlib.Path | None = None,
    ) -> None:
        self._http = http
        self._allow_network = http is not None
        self.data_dir = data_dir or pathlib.Path.home() / ".steamlayer"
        self.app_list_path = self.data_dir / "steam_app_index.json"
        self.dlc_index_path = self.data_dir / "steam_dlc_index.json"
        self._app_index: dict[str, int] = {}
        self._app_name_map: dict[str, str] = {}
        self._dlc_index: dict[int, str] = {}

    def _ensure_http(self) -> HTTPClientProtocol:
        if self._http is None:
            raise NetworkError(
                "Network access required but no HTTP client is configured. "
                "Pass an HTTPClient instance or set allow_network=True."
            )
        return self._http

    def _ensure_index(self, path: pathlib.Path, url: str, label: str) -> bool:
        file_exists = path.exists()

        if not file_exists:
            if not self._allow_network:
                log.warning(f"No local {label} index found and network is disabled.")
                return False

            try:
                log.info(f"Downloading community {label} index mirror...")
                self._ensure_http().download(url, dest=path)
                log.info(f"Successfully updated {label} index.")
                return True

            except NetworkError as e:
                log.warning(f"Could not download {label} index: {e}.")
                return False

        if (time.time() - path.stat().st_mtime) > DEFAULT_CACHE_TTL:
            log.info(f"Local {label} index is outdated, attempting refresh...")
            if not self._allow_network:
                log.info(f"Network disabled; using stale {label} index.")
                return True  # old file but we cant update it; use it anyways.
            try:
                self._ensure_http().download(url, dest=path)
                log.info(f"Successfully refreshed {label} index.")
            except NetworkError as e:
                log.warning(f"Could not refresh {label} index: {e}. Using stale copy.")

        return True

    def _load_index(
        self,
        path: pathlib.Path,
        url: str,
        label: str,
        transform: Callable[[list[Any]], dict],
    ) -> dict:
        if not self._ensure_index(path, url, label):
            return {}

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return transform(raw)
        except Exception as e:
            log.warning(f"{label} index load error: {e}. Purging.")
            path.unlink(missing_ok=True)
            return {}

    def get_app_index(self) -> dict[str, int]:
        if not self._app_index:

            def transform(raw: list) -> dict:
                result: dict[str, int] = {}
                name_map: dict[str, str] = {}
                for a in raw:
                    if not (a.get("name") and a.get("appid")):
                        continue
                    key = str(a["name"]).lower()
                    result[key] = int(a["appid"])
                    name_map[key] = str(a["name"])

                self._app_name_map = name_map
                return result

            self._app_index = self._load_index(
                self.app_list_path,
                self.APP_LIST_URL,
                "App",
                transform,
            )
        return self._app_index

    def get_app_name_map(self) -> dict[str, str]:
        """Return a mapping of lowercase name → original cased name."""
        if not self._app_name_map:
            self.get_app_index()
        return self._app_name_map

    def get_dlc_index(self) -> dict[int, str]:
        if not self._dlc_index:
            self._dlc_index = self._load_index(
                self.dlc_index_path,
                self.DLC_LIST_URL,
                "DLC",
                lambda raw: {int(d["appid"]): str(d["name"]) for d in raw if d.get("appid") and d.get("name")},
            )
        return self._dlc_index
