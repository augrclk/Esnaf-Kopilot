from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import urljoin, urlparse, urlunparse

from ecommerce_image_scraper.html_parsing import (
    extract_h1_text,
    extract_img_urls,
    extract_meta_contents,
    extract_next_data,
    extract_product_id_from_url,
    extract_script_json_objects,
    find_values_by_keys,
    first_json_ld_product,
    first_non_empty,
    flatten_strings,
)
from ecommerce_image_scraper.http_client import HttpClient
from ecommerce_image_scraper.types import ImageParseError, ProductImage, ScraperConfig

IMAGE_KEYS = {
    "image",
    "images",
    "imageUrl",
    "imageUrls",
    "imageURL",
    "imageList",
    "imageUrlList",
    "productImages",
    "productImage",
    "originalImageUrl",
    "originalImage",
    "thumbnail",
    "thumbnailUrl",
}


class TrendyolAdapter:
    platform = "trendyol"

    def __init__(self, client: HttpClient, config: ScraperConfig) -> None:
        self.client = client
        self.config = config

    @staticmethod
    def can_handle(url: str) -> bool:
        return "trendyol.com" in url.lower()

    def extract_images(self, url: str) -> list[ProductImage]:
        html_text = self.client.get(url).text
        return self.parse_product_images(url, html_text)

    def parse_product_images(self, url: str, html_text: str) -> list[ProductImage]:
        candidates: list[tuple[str, str]] = []
        candidates.extend(_json_ld_image_candidates(html_text))
        candidates.extend(_meta_image_candidates(html_text))
        candidates.extend(_next_data_image_candidates(html_text))
        candidates.extend(_script_image_candidates(html_text))
        candidates.extend(("html", value) for value in extract_img_urls(html_text))

        image_urls = deduplicate_urls(
            normalized_url
            for source, value in candidates
            if (normalized_url := normalize_image_url(value, base_url=url))
            and _looks_like_product_image(normalized_url, source)
        )
        if not image_urls:
            raise ImageParseError("Trendyol ürün görselleri bulunamadı.")

        source_by_url: dict[str, str] = {}
        for source, value in candidates:
            normalized_url = normalize_image_url(value, base_url=url)
            if not normalized_url:
                continue
            if not _looks_like_product_image(normalized_url, source):
                continue
            if normalized_url not in source_by_url:
                source_by_url[normalized_url] = source
        product_id = extract_product_id_from_url(url)
        return [
            ProductImage(
                platform=self.platform,
                product_url=url,
                product_id=product_id,
                image_url=image_url,
                image_id=_image_id(image_url),
                position=index,
                source=source_by_url.get(image_url, "unknown"),
            )
            for index, image_url in enumerate(image_urls, start=1)
        ]

    def parse_product_title(self, html_text: str) -> str | None:
        json_ld_product = first_json_ld_product(html_text)
        return first_non_empty(json_ld_product.get("name"), extract_h1_text(html_text))


def deduplicate_urls(urls: list[str | None]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(url)
    return unique


def normalize_image_url(value: str | None, base_url: str) -> str | None:
    if not value:
        return None
    url = html.unescape(str(value)).strip()
    if not url:
        return None
    url = url.split(" ", 1)[0]
    if url.startswith("//"):
        url = f"https:{url}"
    elif url.startswith("/"):
        url = urljoin(base_url, url)
    parsed = urlparse(url)
    if not parsed.scheme:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None

    path = _remove_trendyol_resize_path(parsed.path)
    return urlunparse(("https", parsed.netloc.lower(), path, "", "", ""))


def _json_ld_image_candidates(html_text: str) -> list[tuple[str, str]]:
    product = first_json_ld_product(html_text)
    return [("json_ld", value) for value in flatten_strings(product.get("image"))]


def _meta_image_candidates(html_text: str) -> list[tuple[str, str]]:
    values = extract_meta_contents(
        html_text,
        {"og:image", "og:image:secure_url", "twitter:image"},
    )
    return [("meta", value) for value in values]


def _next_data_image_candidates(html_text: str) -> list[tuple[str, str]]:
    next_data = extract_next_data(html_text)
    if not next_data:
        return []
    return [
        ("next_data", value)
        for node in find_values_by_keys(next_data, IMAGE_KEYS)
        for value in flatten_strings(node)
    ]


def _script_image_candidates(html_text: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for payload in extract_script_json_objects(html_text):
        for node in find_values_by_keys(payload, IMAGE_KEYS):
            candidates.extend(("script_json", value) for value in flatten_strings(node))
    candidates.extend(
        ("script_text", value) for value in _cdn_urls_from_text(html_text)
    )
    return candidates


def _cdn_urls_from_text(text: str) -> list[str]:
    pattern = re.compile(
        r"https?://cdn\.dsmcdn\.com/[^\s\"'<>\\)]+",
        flags=re.IGNORECASE,
    )
    return [match.group(0) for match in pattern.finditer(html.unescape(text))]


def _looks_like_product_image(value: str, source: str) -> bool:
    lowered = html.unescape(str(value)).lower()
    parsed = urlparse(lowered)
    if parsed.netloc != "cdn.dsmcdn.com":
        return False
    normalized_path = _remove_trendyol_resize_path(parsed.path)
    if not re.search(r"\.(?:jpe?g|png|webp)(?:[?#]|$)", lowered):
        return False
    blocked_terms = (
        "logo",
        "sprite",
        "icon",
        "badge",
        "payment",
        "social",
        "placeholder",
    )
    if any(term in lowered for term in blocked_terms):
        return False
    if source in {"json_ld", "meta"}:
        return True
    return _has_product_image_path(normalized_path)


def _has_product_image_path(path: str) -> bool:
    return any(
        marker in path
        for marker in (
            "/product/media/images/",
            "/prod/",
            "_org_zoom.",
        )
    )


def _remove_trendyol_resize_path(path: str) -> str:
    return re.sub(r"/mnresize/\d+/\d+/", "/", path)


def _image_id(image_url: str) -> str:
    return hashlib.sha256(image_url.encode("utf-8")).hexdigest()[:16]
