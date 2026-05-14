"""
HTTP istemci — Trendyol'a istek gönderme.

Özellikler:
  - Rate limiting: İstekler arası minimum bekleme süresi
  - Retry: Sunucu hataları (5xx) için otomatik tekrar deneme
  - curl fallback: urllib başarısız olursa curl ile deneme
  - Hem text (HTML/JSON) hem binary (görsel) indirme
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.models import ScraperHttpError

# Trendyol'da bot tespitinden kaçınmak için tarayıcı gibi davranıyoruz
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

_DEFAULT_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/json,image/*;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.7,en;q=0.6",
}


@dataclass
class HttpResponse:
    """Ham HTTP yanıtı."""

    url: str
    status_code: int
    body: bytes
    headers: dict[str, str]

    @property
    def text(self) -> str:
        """Body'yi UTF-8 string olarak döner."""
        content_type = self.headers.get("Content-Type", "")
        charset = "utf-8"
        if "charset=" in content_type:
            charset = content_type.split("charset=", 1)[1].split(";")[0].strip()
        return self.body.decode(charset or "utf-8", errors="replace")


class HttpClient:
    """
    Rate-limited, retry destekli HTTP istemci.

    Args:
        timeout: İstek zaman aşımı (saniye)
        rate_limit: İstekler arası minimum bekleme (saniye)
        retry_count: 5xx hatasında tekrar deneme sayısı
    """

    def __init__(
        self,
        timeout: float = 20.0,
        rate_limit: float = 0.8,
        retry_count: int = 2,
    ) -> None:
        self._timeout = timeout
        self._rate_limit = rate_limit
        self._retry_count = retry_count
        self._last_request_at: float = 0.0

    def get(self, url: str, params: dict[str, Any] | None = None) -> HttpResponse:
        """GET isteği gönderir, HttpResponse döner."""
        target_url = _append_params(url, params)
        return self._request(target_url)

    def get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        """GET isteği gönderir, response body'yi string olarak döner."""
        return self.get(url, params).text

    def get_bytes(self, url: str) -> bytes:
        """GET isteği gönderir, response body'yi bytes olarak döner (görsel indirme)."""
        return self.get(url).body

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """GET isteği gönderir, JSON parse eder."""
        import json

        text = self.get_text(url, params)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ScraperHttpError(f"JSON parse hatası: {url}") from exc

    # ------------------------------------------------------------------
    # Dahili metodlar
    # ------------------------------------------------------------------

    def _request(self, url: str) -> HttpResponse:
        """Rate limiting ve retry ile HTTP GET yapar."""
        last_error: Exception | None = None

        for attempt in range(self._retry_count + 1):
            self._wait_for_rate_limit()

            try:
                return self._urllib_get(url)
            except ScraperHttpError as exc:
                # 4xx hataları retry'a gerek yok — direkt fırlat
                if "HTTP 4" in str(exc):
                    raise
                last_error = exc
            except Exception as exc:
                last_error = exc

            # Son denemede curl fallback dene
            if attempt == self._retry_count:
                try:
                    return self._curl_get(url)
                except ScraperHttpError:
                    pass

            time.sleep(0.7 * (attempt + 1))

        raise ScraperHttpError(f"İstek başarısız oldu: {url}") from last_error

    def _urllib_get(self, url: str) -> HttpResponse:
        request = Request(url=url, method="GET", headers=_DEFAULT_HEADERS)
        try:
            with urlopen(request, timeout=self._timeout) as response:
                return HttpResponse(
                    url=response.geturl(),
                    status_code=response.status,
                    body=response.read(),
                    headers=dict(response.headers.items()),
                )
        except HTTPError as exc:
            raise ScraperHttpError(f"HTTP {exc.code}: {url}") from exc
        except URLError as exc:
            raise ScraperHttpError(f"Bağlantı hatası: {url}") from exc

    def _curl_get(self, url: str) -> HttpResponse:
        """urllib başarısız olursa curl ile dener."""
        result = subprocess.run(
            [
                "curl", "-L", "--silent", "--fail",
                "--max-time", str(self._timeout),
                "-A", _USER_AGENT,
                "-H", "Accept: text/html,application/json,image/*;q=0.9,*/*;q=0.8",
                "-H", "Accept-Language: tr-TR,tr;q=0.9,en-US;q=0.7,en;q=0.6",
                url,
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            error = result.stderr.decode("utf-8", errors="replace").strip()
            raise ScraperHttpError(f"curl hatası [{error}]: {url}")

        return HttpResponse(url=url, status_code=200, body=result.stdout, headers={})

    def _wait_for_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = self._rate_limit - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()


def _append_params(url: str, params: dict[str, Any] | None) -> str:
    if not params:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params, doseq=True)}"
