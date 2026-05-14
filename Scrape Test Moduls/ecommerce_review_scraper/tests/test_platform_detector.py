import pytest

from ecommerce_scraper.main import _detect_platform
from ecommerce_scraper.types import UnsupportedPlatformError


def test_detects_trendyol() -> None:
    assert _detect_platform("https://www.trendyol.com/marka/urun-p-123") == "trendyol"


def test_rejects_unsupported_platform() -> None:
    with pytest.raises(UnsupportedPlatformError):
        _detect_platform("https://www.amazon.com.tr/product")
