from __future__ import annotations

import logging
import pathlib
import platform
import threading
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from steamlayer_core._version import __version__
from steamlayer_core.domain.exceptions import NetworkError

log = logging.getLogger("steamlayer.http_client")

# 64KB
_DEFAULT_CHUNK_SIZE = 64 * 1024

_DEFAULT_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

# (Connect Timeout, Read Timeout)
_DEFAULT_TIMEOUT: tuple[float, float] = (5.0, 10.0)
_DOWNLOAD_TIMEOUT: tuple[float, float] = (10.0, 60.0)


class HTTPClient:
    _DEFAULT_HEADERS = {
        "User-Agent": (f"steamlayer/{__version__} (Python {platform.python_version()}; {platform.system()})")
    }

    def __init__(
        self,
        *,
        retries: int = 3,
        backoff_factor: float = 1.0,
        retry_statuses: frozenset[int] = _DEFAULT_RETRY_STATUSES,
        rate_limit: float = 0.5,
    ) -> None:
        self._rate_limit = rate_limit
        self._last_request_at: float = 0.0
        self._lock = threading.Lock()

        retry = Retry(
            total=retries,
            backoff_factor=backoff_factor,
            status_forcelist=retry_statuses,
            allowed_methods={"GET"},
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)

        self._session = requests.Session()
        self._session.headers.update(self._DEFAULT_HEADERS)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def __enter__(self) -> HTTPClient:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    def _wait_for_rate_limit(self) -> None:
        with self._lock:
            now = time.monotonic()
            gap = self._rate_limit - (now - self._last_request_at)
            if gap > 0:
                log.debug(f"Rate limiter: sleeping {gap:.3f}s")
                time.sleep(gap)
            self._last_request_at = time.monotonic()

    def _log_response(self, response: requests.Response) -> None:
        elapsed = response.elapsed.total_seconds() if response.elapsed else 0.0
        log.debug(f"{response.request.method} {response.url} -> {response.status_code} ({elapsed:.3f}s)")

    def get(
        self,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
        timeout: tuple[float, float] = _DEFAULT_TIMEOUT,
        **kwargs: Any,
    ) -> requests.Response:
        self._wait_for_rate_limit()
        try:
            response = self._session.get(url, params=params, headers=headers, timeout=timeout)
            self._log_response(response)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as e:
            raise NetworkError(
                str(e), status_code=e.response.status_code if e.response is not None else None
            ) from e
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e)) from e

    def download(
        self,
        url: str,
        dest: pathlib.Path,
        *,
        params: dict | None = None,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        timeout: tuple[float, float] = _DOWNLOAD_TIMEOUT,
        **kwargs: Any,
    ) -> None:
        self._wait_for_rate_limit()
        tmp = dest.with_suffix(".tmp")
        try:
            with self._session.get(url, params=params, timeout=timeout, stream=True) as response:
                self._log_response(response)
                response.raise_for_status()
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(tmp, "wb") as f:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        f.write(chunk)

            tmp.replace(dest)
            log.debug(f"Downloaded {url} -> {dest}")

        except requests.exceptions.HTTPError as e:
            raise NetworkError(
                str(e), status_code=e.response.status_code if e.response is not None else None
            ) from e
        except requests.exceptions.RequestException as e:
            raise NetworkError(str(e)) from e
        finally:
            tmp.unlink(missing_ok=True)
