from __future__ import annotations

import json
import logging
import pathlib
import time

from steamlayer_core.constants import DEFAULT_CACHE_TTL
from steamlayer_core.protocols import AppIndexRepositoryProtocol, SteamWebClientProtocol

log = logging.getLogger("steamlayer.discovery.dlc")


class DLCService:
    """
    Fetches and caches DLC metadata for a Steam AppID.

    Resolution order
    ----------------
    1. **Cache** — if a fresh cache file exists at ``cache_path``, return it
       immediately without touching the network.
    2. **Network** — query the Steam Web API for the app's DLC list, resolve
       names via the local index, then fall back to individual API calls for
       any DLC absent from the index.
    3. **Empty fallback** — returned when the cache is cold and
       ``allow_network=False``, or when the API returns no usable data.

    All configuration is supplied at construction time so ``fetch()`` is a
    pure "give me the DLCs for this AppID" call with no hidden parameters.

    Parameters
    ----------
    repo:
        Provides the local DLC name index.
    web:
        Steam Web API client used for live lookups.
    cache_path:
        Path to a single JSON cache file for this service instance.
        Pass ``None`` to disable caching entirely.
    allow_network:
        Set to ``False`` to prevent any outbound HTTP calls.
    ttl_seconds:
        Maximum age of the cache file before it is considered stale.
        defaults to ``DEFAULT_CACHE_TTL``.
    """

    def __init__(
        self,
        repo: AppIndexRepositoryProtocol,
        web: SteamWebClientProtocol,
        *,
        cache_path: pathlib.Path | None = None,
        allow_network: bool = True,
        ttl_seconds: int = DEFAULT_CACHE_TTL,
    ) -> None:
        self.repo = repo
        self.web = web
        self._cache_path = cache_path
        self._allow_network = allow_network
        self._ttl_seconds = ttl_seconds

    def _read_cache(self) -> dict[str | int, str]:
        if self._cache_path is None or not self._cache_path.exists():
            return {}

        try:
            data = json.loads(self._cache_path.read_text(encoding="utf-8"))
            fetched_at = data.get("fetched_at", 0)
            if (time.time() - fetched_at) > self._ttl_seconds:
                log.info("Found expired cache, skipping.")
                return {}

            dlcs = data.get("dlcs", {})
            if isinstance(dlcs, dict):
                return {int(k): str(v) for k, v in dlcs.items()}

        except Exception:
            return {}
        return {}

    def _write_cache(self, dlcs: dict[int | str, str]) -> None:
        if self._cache_path is None:
            return

        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "fetched_at": int(time.time()),
                "dlcs": {str(k): v for k, v in dlcs.items()},
            }
            self._cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            log.warning("Something went wrong while writing cache, skipping.")
            self._cache_path.unlink(missing_ok=True)

    def fetch(self, appid: int, *, force_refresh: bool = False) -> tuple[dict[str | int, str], bool]:
        """
        Return DLC metadata for *appid*.

        DLCs that cannot be resolved by name receive a synthetic
        ``"DLC {appid}"`` placeholder so the caller always gets a complete
        mapping rather than a partial one.

        Parameters
        ----------
        appid : int
            The primary Steam AppID to query.
        force_refresh : bool, optional
            If True, skips the local cache lookup and performs a fresh
            network-based resolution. Defaults to False.

        Returns
        -------
        tuple[dict[str | int, str], bool]
            A tuple of ``(dlcs, from_cache)``:
            - ``dlcs``: A dictionary mapping DLC AppID to its resolved name.
            - ``from_cache``: True if the results were loaded from the local
              vault, False if they were fetched from the network.

        Notes
        -----
        Resolved network results are automatically persisted to the local cache
        to speed up subsequent calls and allow for offline patching.
        """
        log.info(f"Fetching DLC metadata for AppID {appid}...")

        if not force_refresh:
            cached = self._read_cache()
            if cached:
                log.info(f"Cache hit — loaded {len(cached)} DLC(s).")
                return cached, True
        else:
            log.info("Force refresh requested — skipping cache lookup.")

        if not self._allow_network:
            log.info("Network disabled; skipping DLC hydration.")
            return {}, False

        log.info("Cache miss — fetching DLC(s) from Steam API...")
        try:
            response = self.web.get_app_details(appid)
            app_entry: dict = response.get(str(appid), {})

            if not app_entry.get("success"):
                return {}, False

            raw_dlc_list = app_entry["data"].get("dlc", [])
            if not raw_dlc_list:
                return {}, False

            local_index = self.repo.get_dlc_index()
            resolved_dlcs: dict[str | int, str] = {}
            unresolved_ids: list[int] = []

            for raw_id in raw_dlc_list:
                dlc_id = int(raw_id)
                name = local_index.get(dlc_id)
                if name:
                    resolved_dlcs[dlc_id] = name
                else:
                    unresolved_ids.append(dlc_id)

            if unresolved_ids:
                log.info(f"Found {len(unresolved_ids)} missing DLCs: {unresolved_ids}")

            for target_id in unresolved_ids:
                try:
                    log.info(f"Fetching missing DLC {target_id} individually.")
                    dlc_response = self.web.get_app_details(target_id)
                    dlc_details = dlc_response.get(str(target_id), {}).get("data", {})

                    resolved_name = dlc_details.get("name")
                    if resolved_name:
                        log.info(f"Resolved missing DLC: {target_id} -> '{resolved_name}'")
                        resolved_dlcs[target_id] = resolved_name
                    else:
                        log.warning(f"DLC {target_id} returned no name, using fallback.")
                        resolved_dlcs[target_id] = f"DLC {target_id}"

                except Exception as error:
                    log.warning(f"Failed to fetch DLC {target_id}: {error}")
                    resolved_dlcs[target_id] = f"DLC {target_id}"

            self._write_cache(resolved_dlcs)
            return resolved_dlcs, False

        except Exception as error:
            log.warning(f"DLC hydration failed: {error}")
            return {}, False
