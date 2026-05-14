from __future__ import annotations

import csv
import hashlib
from dataclasses import asdict
from pathlib import Path

from ecommerce_scraper.html_parsing import extract_product_id_from_url
from ecommerce_scraper.http_client import HttpClient
from ecommerce_scraper.trendyol import TrendyolAdapter
from ecommerce_scraper.types import (
    FileWriteError,
    Product,
    Review,
    ScrapeFileResult,
    ScraperConfig,
    UnsupportedPlatformError,
)

REVIEW_COLUMNS = [
    "platform",
    "product_url",
    "product_id",
    "review_id",
    "rating",
    "review_title",
    "review_text",
    "review_date",
    "user_name",
    "variant",
    "helpful_count",
    "page_number",
    "source_url",
    "collected_at",
]


def scrape_product_to_files(
    url: str,
    output_dir: str | Path,
    config: ScraperConfig | None = None,
) -> ScrapeFileResult:
    scraper_config = config or ScraperConfig()
    output_path = ensure_output_dir(output_dir)
    clear_output_files(output_path)
    platform = _detect_platform(url)
    adapter = TrendyolAdapter(HttpClient(scraper_config), scraper_config)

    product_file_path = output_path / "urun.txt"
    reviews_file_path = output_path / "yorumlar.csv"
    product_id = extract_product_id_from_url(url)

    try:
        product = adapter.extract_product(url)
        product_id = product.product_id
        reviews = deduplicate_reviews(adapter.extract_reviews(url, product))

        product_file_path = write_product_file(product, output_path)
        reviews_file_path = write_reviews_csv(reviews, output_path)

        return ScrapeFileResult(
            platform=product.platform,
            product_url=product.url,
            product_id=product.product_id,
            output_dir=str(output_path),
            product_file_path=str(product_file_path),
            reviews_file_path=str(reviews_file_path),
            review_count=len(reviews),
            status="success",
            error_message=None,
        )
    except Exception as exc:
        return ScrapeFileResult(
            platform=platform,
            product_url=url,
            product_id=product_id,
            output_dir=str(output_path),
            product_file_path=_existing_path(product_file_path),
            reviews_file_path=_existing_path(reviews_file_path),
            review_count=0,
            status="failed",
            error_message=str(exc),
        )


def _existing_path(path: Path) -> str:
    return str(path) if path.exists() else ""


def _detect_platform(url: str) -> str:
    if TrendyolAdapter.can_handle(url):
        return TrendyolAdapter.platform
    raise UnsupportedPlatformError(f"Desteklenmeyen platform: {url}")


def ensure_output_dir(output_dir: str | Path) -> Path:
    path = Path(output_dir)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FileWriteError(f"Output klasörü oluşturulamadı: {path}") from exc
    return path


def clear_output_files(output_dir: str | Path) -> None:
    for file_name in ("urun.txt", "yorumlar.csv"):
        path = Path(output_dir) / file_name
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise FileWriteError(f"Eski output dosyası temizlenemedi: {path}") from exc


def write_product_file(product: Product, output_dir: str | Path) -> Path:
    path = Path(output_dir) / "urun.txt"
    content = f"Başlık:\n{product.title}\n\nAçıklama:\n{product.description}\n"
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise FileWriteError(f"Ürün dosyası yazılamadı: {path}") from exc
    return path


def write_reviews_csv(reviews: list[Review], output_dir: str | Path) -> Path:
    path = Path(output_dir) / "yorumlar.csv"
    unique_reviews = deduplicate_reviews(reviews)
    try:
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=REVIEW_COLUMNS)
            writer.writeheader()
            for review in unique_reviews:
                row = asdict(review)
                writer.writerow({column: row.get(column) for column in REVIEW_COLUMNS})
    except OSError as exc:
        raise FileWriteError(f"Yorum CSV dosyası yazılamadı: {path}") from exc
    return path


def deduplicate_reviews(reviews: list[Review]) -> list[Review]:
    seen: set[str] = set()
    unique: list[Review] = []
    for review in reviews:
        key = review.review_id or _fallback_review_hash(review)
        if key in seen:
            continue
        seen.add(key)
        unique.append(review)
    return unique


def _fallback_review_hash(review: Review) -> str:
    raw_key = "|".join(
        [
            str(review.rating or ""),
            review.review_text,
            review.review_date or "",
            review.user_name or "",
        ]
    )
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
