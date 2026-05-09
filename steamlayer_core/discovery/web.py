from __future__ import annotations

import logging

from steamlayer_core.http_client import NetworkError
from steamlayer_core.protocols import HTTPClientProtocol

log = logging.getLogger("steamlayer.discovery.web")


class SteamWebClient:
    _STORE_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
    _APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"

    def __init__(self, http: HTTPClientProtocol) -> None:
        self._http = http

    def search_store(self, term: str) -> dict:
        log.info(f"Searching Steam for: '{term}'...")
        try:
            return self._http.get(
                self._STORE_SEARCH_URL,
                params={"term": term, "l": "english", "cc": "US"},
            ).json()  # type: ignore[no-any-return]
        except NetworkError as e:
            log.warning(f"Store search failed: {e}")
            return {}

    def get_app_details(self, appid: int) -> dict:
        try:
            return self._http.get(
                self._APP_DETAILS_URL,
                params={"appids": appid, "filters": "basic"},
            ).json()  # type: ignore[no-any-return]
        except NetworkError as e:
            log.warning(f"App details fetch failed for {appid}: {e}")
            return {}
