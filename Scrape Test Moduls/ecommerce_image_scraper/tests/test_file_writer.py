import json
from pathlib import Path

from ecommerce_image_scraper.main import (
    clear_output_files,
    download_images,
    write_manifest,
)
from ecommerce_image_scraper.types import ProductImage


def test_download_images_uses_expected_names_and_manifest(tmp_path: Path) -> None:
    images = [
        _image(1, "https://cdn.dsmcdn.com/ty1/product/one.jpeg"),
        _image(2, "https://cdn.dsmcdn.com/ty1/product/two.webp"),
    ]
    client = _FakeClient()

    downloaded = download_images(images, tmp_path / "images", client)  # type: ignore[arg-type]
    manifest_path = write_manifest(downloaded, tmp_path)

    assert (tmp_path / "images" / "image_01.jpg").read_bytes() == b"image-bytes"
    assert (tmp_path / "images" / "image_02.webp").read_bytes() == b"image-bytes"

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["image_count"] == 2
    assert payload["images"][0]["file_path"].endswith("image_01.jpg")


def test_clear_output_files_removes_previous_scrape_files(tmp_path: Path) -> None:
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    (image_dir / "image_01.jpg").write_bytes(b"old")
    (tmp_path / "manifest.json").write_text("old", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("keep", encoding="utf-8")

    clear_output_files(tmp_path)

    assert not image_dir.exists()
    assert not (tmp_path / "manifest.json").exists()
    assert (tmp_path / "notes.txt").exists()


def _image(position: int, image_url: str) -> ProductImage:
    return ProductImage(
        platform="trendyol",
        product_url="https://www.trendyol.com/x/y-p-123",
        product_id="123",
        image_url=image_url,
        image_id=f"id-{position}",
        position=position,
        source="test",
    )


class _FakeClient:
    def get_bytes(self, url: str) -> bytes:
        return b"image-bytes"
