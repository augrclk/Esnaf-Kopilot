from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScraperConfig:
    timeout_seconds: float = 20.0
    retry_count: int = 2
    retry_backoff_seconds: float = 0.7
    rate_limit_seconds: float = 0.5
    use_curl_fallback: bool = True
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )


@dataclass(frozen=True, slots=True)
class ProductImage:
    platform: str
    product_url: str
    product_id: str | None
    image_url: str
    image_id: str
    position: int
    source: str
    file_path: str | None = None


@dataclass(frozen=True, slots=True)
class ScrapeImageResult:
    platform: str
    product_url: str
    product_id: str | None
    output_dir: str
    image_dir: str
    manifest_file_path: str
    image_count: int
    images: list[ProductImage]
    status: str
    error_message: str | None


class EcommerceImageScraperError(Exception):
    """Base exception for image scraper errors."""


class UnsupportedPlatformError(EcommerceImageScraperError):
    """Raised when a URL does not belong to a supported platform."""


class ImageParseError(EcommerceImageScraperError):
    """Raised when product images cannot be parsed."""


class ScraperHttpError(EcommerceImageScraperError):
    """Raised when an HTTP request fails."""


class FileWriteError(EcommerceImageScraperError):
    """Raised when output files cannot be written."""
