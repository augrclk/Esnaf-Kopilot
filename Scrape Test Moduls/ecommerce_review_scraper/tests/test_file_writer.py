import csv
from pathlib import Path

from ecommerce_scraper.main import (
    clear_output_files,
    deduplicate_reviews,
    write_product_file,
    write_reviews_csv,
)
from ecommerce_scraper.types import Product, Review


def test_write_product_file_uses_expected_format(tmp_path: Path) -> None:
    product = Product(
        platform="trendyol",
        url="https://www.trendyol.com/x/y-p-123",
        product_id="123",
        title="Türkçe Başlık",
        description="Ürün açıklaması",
    )

    path = write_product_file(product, tmp_path)

    assert (
        path.read_text(encoding="utf-8")
        == "Başlık:\nTürkçe Başlık\n\nAçıklama:\nÜrün açıklaması\n"
    )


def test_write_reviews_csv_uses_utf8_bom_and_deduplicates(tmp_path: Path) -> None:
    reviews = [
        _review(review_id="same-id", text="İlk yorum"),
        _review(review_id="same-id", text="İlk yorum tekrar"),
        _review(review_id=None, text="Aynı metin"),
        _review(review_id=None, text="Aynı metin"),
    ]

    path = write_reviews_csv(reviews, tmp_path)

    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    assert len(rows) == 2
    assert list(rows[0].keys()) == [
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


def test_deduplicate_reviews_uses_fallback_hash_when_id_missing() -> None:
    reviews = [
        _review(review_id=None, text="Tekrarlı yorum"),
        _review(review_id=None, text="Tekrarlı yorum"),
        _review(review_id=None, text="Farklı yorum"),
    ]

    unique = deduplicate_reviews(reviews)

    assert [review.review_text for review in unique] == [
        "Tekrarlı yorum",
        "Farklı yorum",
    ]


def test_clear_output_files_removes_previous_scrape_files(tmp_path: Path) -> None:
    product_file = tmp_path / "urun.txt"
    reviews_file = tmp_path / "yorumlar.csv"
    unrelated_file = tmp_path / "notes.txt"
    product_file.write_text("old product", encoding="utf-8")
    reviews_file.write_text("old reviews", encoding="utf-8")
    unrelated_file.write_text("keep", encoding="utf-8")

    clear_output_files(tmp_path)

    assert not product_file.exists()
    assert not reviews_file.exists()
    assert unrelated_file.exists()


def _review(review_id: str | None, text: str) -> Review:
    return Review(
        platform="trendyol",
        product_url="https://www.trendyol.com/x/y-p-123",
        product_id="123",
        review_id=review_id,
        rating=5.0,
        review_title=None,
        review_text=text,
        review_date="12.04.2026",
        user_name="Ayşe",
        variant=None,
        helpful_count=None,
        page_number=1,
        source_url="https://www.trendyol.com/x/y-p-123",
        collected_at="2026-05-12T10:00:00+00:00",
    )
