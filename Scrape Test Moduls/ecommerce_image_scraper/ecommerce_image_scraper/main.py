from __future__ import annotations

import json
import shutil
from dataclasses import asdict, replace
from pathlib import Path
from urllib.parse import urlparse

from ecommerce_image_scraper.html_parsing import extract_product_id_from_url
from ecommerce_image_scraper.http_client import HttpClient
from ecommerce_image_scraper.trendyol import TrendyolAdapter
from ecommerce_image_scraper.types import (
    FileWriteError,
    ProductImage,
    ScrapeImageResult,
    ScraperConfig,
    UnsupportedPlatformError,
)


def scrape_product_images_to_files(
    url: str,
    output_dir: str | Path,
    config: ScraperConfig | None = None,
) -> ScrapeImageResult:
    scraper_config = config or ScraperConfig()
    platform = _detect_platform(url)
    product_id = extract_product_id_from_url(url)
    output_path = ensure_output_dir(output_dir)
    image_dir = output_path / "images"
    manifest_path = output_path / "manifest.json"
    clear_output_files(output_path)

    adapter = TrendyolAdapter(HttpClient(scraper_config), scraper_config)

    try:
        images = adapter.extract_images(url)
        downloaded_images = download_images(images, image_dir, adapter.client)
        manifest_path = write_manifest(downloaded_images, output_path)

        return ScrapeImageResult(
            platform=platform,
            product_url=url,
            product_id=product_id,
            output_dir=str(output_path),
            image_dir=str(image_dir),
            manifest_file_path=str(manifest_path),
            image_count=len(downloaded_images),
            images=downloaded_images,
            status="success",
            error_message=None,
        )
    except Exception as exc:
        return ScrapeImageResult(
            platform=platform,
            product_url=url,
            product_id=product_id,
            output_dir=str(output_path),
            image_dir=str(image_dir) if image_dir.exists() else "",
            manifest_file_path=str(manifest_path) if manifest_path.exists() else "",
            image_count=0,
            images=[],
            status="failed",
            error_message=str(exc),
        )


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
    path = Path(output_dir)
    manifest_path = path / "manifest.json"
    image_dir = path / "images"
    try:
        manifest_path.unlink(missing_ok=True)
        if image_dir.exists():
            shutil.rmtree(image_dir)
    except OSError as exc:
        raise FileWriteError(f"Eski output dosyaları temizlenemedi: {path}") from exc


def download_images(
    images: list[ProductImage],
    image_dir: str | Path,
    client: HttpClient,
) -> list[ProductImage]:
    image_path = Path(image_dir)
    try:
        image_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FileWriteError(f"Görsel klasörü oluşturulamadı: {image_path}") from exc

    downloaded: list[ProductImage] = []
    for image in images:
        extension = _image_extension(image.image_url)
        file_path = image_path / f"image_{image.position:02d}{extension}"
        try:
            file_path.write_bytes(client.get_bytes(image.image_url))
        except OSError as exc:
            raise FileWriteError(f"Görsel dosyası yazılamadı: {file_path}") from exc
        downloaded.append(replace(image, file_path=str(file_path)))
    return downloaded


def write_manifest(images: list[ProductImage], output_dir: str | Path) -> Path:
    path = Path(output_dir) / "manifest.json"
    payload = {
        "image_count": len(images),
        "images": [asdict(image) for image in images],
    }
    try:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        raise FileWriteError(f"Manifest dosyası yazılamadı: {path}") from exc
    return path


def _image_extension(image_url: str) -> str:
    suffix = Path(urlparse(image_url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"
