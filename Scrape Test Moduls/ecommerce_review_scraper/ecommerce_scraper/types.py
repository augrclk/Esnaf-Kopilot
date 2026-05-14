from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScraperConfig:
    timeout_seconds: float = 20.0
    retry_count: int = 2
    retry_backoff_seconds: float = 0.7
    rate_limit_seconds: float = 0.8
    max_review_pages: int = 50
    use_rendered_html_fallback: bool = True
    rendered_html_timeout_seconds: float = 15.0
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )


@dataclass(frozen=True, slots=True)
class Product:
    platform: str
    url: str
    product_id: str | None
    title: str
    description: str


@dataclass(frozen=True, slots=True)
class Review:
    platform: str
    product_url: str
    product_id: str | None
    review_id: str | None
    rating: float | None
    review_title: str | None
    review_text: str
    review_date: str | None
    user_name: str | None
    variant: str | None
    helpful_count: int | None
    page_number: int | None
    source_url: str | None
    collected_at: str


@dataclass(frozen=True, slots=True)
class ScrapeFileResult:
    platform: str
    product_url: str
    product_id: str | None
    output_dir: str
    product_file_path: str
    reviews_file_path: str
    review_count: int
    status: str
    error_message: str | None


class EcommerceScraperError(Exception):
    """Base exception for scraper errors."""


class UnsupportedPlatformError(EcommerceScraperError):
    """Raised when a URL does not belong to a supported platform."""


class ProductParseError(EcommerceScraperError):
    """Raised when a product page cannot be parsed."""


class ScraperHttpError(EcommerceScraperError):
    """Raised when an HTTP request fails."""


class FileWriteError(EcommerceScraperError):
    """Raised when output files cannot be written."""
