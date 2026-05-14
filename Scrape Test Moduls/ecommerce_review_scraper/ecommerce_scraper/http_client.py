from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ecommerce_scraper.types import ScraperConfig, ScraperHttpError


@dataclass(frozen=True, slots=True)
class HttpResponse:
    url: str
    status_code: int
    text: str
    headers: dict[str, str]


class HttpClient:
    def __init__(self, config: ScraperConfig) -> None:
        self._config = config
        self._last_request_at = 0.0

    def get(self, url: str, params: dict[str, Any] | None = None) -> HttpResponse:
        target_url = self._build_url(url, params)
        return self._request("GET", target_url)

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        response = self.get(url, params=params)
        try:
            return json.loads(response.text)
        except json.JSONDecodeError as exc:
            message = f"JSON yanıtı ayrıştırılamadı: {response.url}"
            raise ScraperHttpError(message) from exc

    def _request(self, method: str, url: str) -> HttpResponse:
        last_error: Exception | None = None
        for attempt in range(self._config.retry_count + 1):
            self._wait_for_rate_limit()
            request = Request(
                url=url,
                method=method,
                headers={
                    "User-Agent": self._config.user_agent,
                    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.7,en;q=0.6",
                },
            )

            try:
                with urlopen(request, timeout=self._config.timeout_seconds) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    body = response.read().decode(charset, errors="replace")
                    return HttpResponse(
                        url=response.geturl(),
                        status_code=response.status,
                        text=body,
                        headers=dict(response.headers.items()),
                    )
            except HTTPError as exc:
                last_error = exc
                if exc.code < 500 or attempt >= self._config.retry_count:
                    raise ScraperHttpError(f"HTTP hata kodu {exc.code}: {url}") from exc
            except URLError as exc:
                last_error = exc
                if attempt >= self._config.retry_count:
                    message = f"HTTP isteği başarısız oldu: {url}"
                    raise ScraperHttpError(message) from exc

            time.sleep(self._config.retry_backoff_seconds * (attempt + 1))

        raise ScraperHttpError(f"HTTP isteği başarısız oldu: {url}") from last_error

    def _wait_for_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait_seconds = self._config.rate_limit_seconds - elapsed
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        self._last_request_at = time.monotonic()

    @staticmethod
    def _build_url(url: str, params: dict[str, Any] | None) -> str:
        if not params:
            return url
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}{urlencode(params, doseq=True)}"
