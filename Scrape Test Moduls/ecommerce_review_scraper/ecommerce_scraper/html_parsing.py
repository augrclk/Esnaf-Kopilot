from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from ecommerce_scraper.types import Product, Review


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def first_non_empty(*values: Any) -> str | None:
    for value in values:
        text = normalize_text(value)
        if text:
            return text
    return None


def extract_meta_content(html_text: str, names: Iterable[str]) -> str | None:
    name_set = {name.lower() for name in names}
    for tag in re.findall(r"<meta\b[^>]*>", html_text, flags=re.IGNORECASE):
        attrs = _parse_attrs(tag)
        attr_name = (attrs.get("name") or attrs.get("property") or "").lower()
        if attr_name in name_set and attrs.get("content"):
            return normalize_text(attrs["content"])
    return None


def extract_json_ld_products(html_text: str) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    pattern = re.compile(
        r"<script\b[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(html_text):
        raw_json = html.unescape(match.group(1)).strip()
        if not raw_json:
            continue
        for item in _json_items(raw_json):
            products.extend(_find_product_nodes(item))
    return products


def extract_next_data(html_text: str) -> dict[str, Any] | None:
    match = re.search(
        r"<script\b[^>]*id=[\"']__NEXT_DATA__[\"'][^>]*>(.*?)</script>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    try:
        data = json.loads(html.unescape(match.group(1)).strip())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def find_first_key(data: Any, keys: set[str]) -> Any:
    if isinstance(data, dict):
        for key, value in data.items():
            if key in keys and value not in (None, ""):
                return value
        for value in data.values():
            nested = find_first_key(value, keys)
            if nested not in (None, ""):
                return nested
    elif isinstance(data, list):
        for item in data:
            nested = find_first_key(item, keys)
            if nested not in (None, ""):
                return nested
    return None


def find_values_by_keys(data: Any, keys: set[str]) -> list[Any]:
    values: list[Any] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key in keys and value not in (None, ""):
                values.append(value)
            values.extend(find_values_by_keys(value, keys))
    elif isinstance(data, list):
        for item in data:
            values.extend(find_values_by_keys(item, keys))
    return values


def find_all_review_like_dicts(data: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(data, dict):
        keys = {key.lower() for key in data}
        text_keys = {
            "comment",
            "reviewtext",
            "review_text",
            "commenttext",
            "text",
            "content",
        }
        id_or_rating_keys = {
            "rate",
            "rating",
            "star",
            "score",
            "reviewid",
            "id",
            "commentid",
        }
        if keys & text_keys:
            if keys & id_or_rating_keys:
                found.append(data)
        for value in data.values():
            found.extend(find_all_review_like_dicts(value))
    elif isinstance(data, list):
        for item in data:
            found.extend(find_all_review_like_dicts(item))
    return found


def parse_rating(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:[.,]\d+)?", str(value))
    if not match:
        return None
    return float(match.group(0).replace(",", "."))


def parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def extract_product_id_from_url(url: str) -> str | None:
    path = urlparse(url).path
    for pattern in (
        r"-p-(\d+)",
        r"/p-(\d+)",
        r"productId=(\d+)",
    ):
        match = re.search(pattern, url, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    slug = path.rstrip("/").split("/")[-1]
    return slug or None


def extract_visible_text_by_class(
    html_text: str,
    class_keywords: Iterable[str],
) -> list[str]:
    values: list[str] = []
    for keyword in class_keywords:
        pattern = re.compile(
            rf"<(?P<tag>[a-z0-9]+)\b[^>]*class=[\"'][^\"']*"
            rf"{re.escape(keyword)}[^\"']*[\"'][^>]*>"
            r"(?P<body>.*?)</(?P=tag)>",
            re.IGNORECASE | re.DOTALL,
        )
        values.extend(
            normalize_text(match.group("body")) for match in pattern.finditer(html_text)
        )
    return [value for value in values if value]


def extract_text_by_attrs(
    html_text: str,
    attr_filters: dict[str, str],
) -> str | None:
    parser = _ElementTextParser(attr_filters)
    parser.feed(html_text)
    return normalize_text(parser.text) or None


def _parse_attrs(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    pattern = re.compile(r"([\w:-]+)\s*=\s*([\"'])(.*?)\2", re.DOTALL)
    for key, _, value in pattern.findall(tag):
        attrs[key.lower()] = html.unescape(value)
    return attrs


class _ElementTextParser(HTMLParser):
    def __init__(self, attr_filters: dict[str, str]) -> None:
        super().__init__(convert_charrefs=True)
        self._attr_filters = {key.lower(): value for key, value in attr_filters.items()}
        self._depth = 0
        self._capturing = False
        self._parts: list[str] = []

    @property
    def text(self) -> str:
        return " ".join(self._parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if self._capturing:
            if tag_name in {"br", "hr", "img", "input", "meta", "link"}:
                self._parts.append(" ")
                return
            self._depth += 1
            if tag_name in {"p", "div", "li"}:
                self._parts.append(" ")
            return

        attr_map = {key.lower(): value or "" for key, value in attrs}
        if _attrs_match(attr_map, self._attr_filters):
            self._capturing = True
            self._depth = 1

    def handle_endtag(self, tag: str) -> None:
        if not self._capturing:
            return
        if tag.lower() in {"p", "div", "li"}:
            self._parts.append(" ")
        self._depth -= 1
        if self._depth <= 0:
            self._capturing = False

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._parts.append(data)


def _attrs_match(attrs: dict[str, str], attr_filters: dict[str, str]) -> bool:
    for key, expected_value in attr_filters.items():
        actual_value = attrs.get(key)
        if actual_value is None:
            return False
        if key == "class":
            classes = actual_value.split()
            if expected_value not in classes:
                return False
        elif actual_value != expected_value:
            return False
    return True


def _json_items(raw_json: str) -> list[Any]:
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else [data]


def _find_product_nodes(data: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if isinstance(data, dict):
        node_type = data.get("@type")
        node_types = node_type if isinstance(node_type, list) else [node_type]
        if any(str(item).lower() == "product" for item in node_types):
            nodes.append(data)
        graph = data.get("@graph")
        if graph:
            nodes.extend(_find_product_nodes(graph))
    elif isinstance(data, list):
        for item in data:
            nodes.extend(_find_product_nodes(item))
    return nodes


def first_json_ld_product(html_text: str) -> dict[str, Any]:
    products = extract_json_ld_products(html_text)
    return products[0] if products else {}


def extract_h1_text(html_text: str, pattern: str | None = None) -> str | None:
    h1_pattern = pattern or r"<h1\b[^>]*>(.*?)</h1>"
    match = re.search(h1_pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
    return normalize_text(match.group(1)) if match else None


def parse_json_reviews(
    payload: Any,
    *,
    platform: str,
    product: Product,
    page_number: int,
    source_url: str,
    collected_at: str,
    user_keys: tuple[str, ...],
    date_keys: tuple[str, ...],
) -> list[Review]:
    reviews: list[Review] = []
    for item in find_all_review_like_dicts(payload):
        review_text = first_non_empty(
            _json_first(
                item,
                "comment",
                "commentText",
                "reviewText",
                "review_text",
                "text",
                "content",
            )
        )
        if not review_text:
            continue

        reviews.append(
            Review(
                platform=platform,
                product_url=product.url,
                product_id=product.product_id,
                review_id=_json_first(item, "reviewId", "review_id", "commentId", "id"),
                rating=parse_rating(
                    _json_first(item, "rate", "rating", "star", "score")
                ),
                review_title=first_non_empty(_json_first(item, "title", "summary")),
                review_text=review_text,
                review_date=first_non_empty(_json_first(item, *date_keys)),
                user_name=first_non_empty(_json_first(item, *user_keys)),
                variant=first_non_empty(
                    _json_first(item, "variant", "productAttributes", "attributes")
                ),
                helpful_count=parse_int(_helpful_count(item)),
                page_number=page_number,
                source_url=source_url,
                collected_at=collected_at,
            )
        )
    return reviews


def parse_html_reviews(
    html_text: str,
    *,
    platform: str,
    product: Product,
    source_url: str,
    page_number: int | None,
    collected_at: str,
    block_class_terms: Iterable[str],
    text_classes: Iterable[str],
    title_classes: Iterable[str],
    user_classes: Iterable[str],
    variant_classes: Iterable[str],
) -> list[Review]:
    reviews: list[Review] = []
    for index, block in enumerate(
        _extract_review_blocks(html_text, block_class_terms),
        start=1,
    ):
        review_text = first_non_empty(*_text_by_classes(block, text_classes))
        if not review_text:
            continue

        reviews.append(
            Review(
                platform=platform,
                product_url=product.url,
                product_id=product.product_id,
                review_id=_extract_review_id(block) or f"html-{page_number}-{index}",
                rating=_extract_rating_from_html(block),
                review_title=first_non_empty(*_text_by_classes(block, title_classes)),
                review_text=review_text,
                review_date=_extract_date_from_html(block),
                user_name=first_non_empty(*_text_by_classes(block, user_classes)),
                variant=first_non_empty(*_text_by_classes(block, variant_classes)),
                helpful_count=_extract_helpful_count(block),
                page_number=page_number,
                source_url=source_url,
                collected_at=collected_at,
            )
        )
    return reviews


def _json_first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    return None


def _helpful_count(item: dict[str, Any]) -> Any:
    return _json_first(
        item,
        "helpfulCount",
        "likeCount",
        "likes_count",
        "thumbsUpCount",
    )


def _extract_review_blocks(html_text: str, class_terms: Iterable[str]) -> list[str]:
    class_pattern = "|".join(re.escape(term) for term in class_terms)
    patterns = [
        rf"<div\b[^>]*class=[\"'][^\"']*(?:{class_pattern})[^\"']*[\"'][^>]*>.*?</div>",
        rf"<li\b[^>]*class=[\"'][^\"']*(?:{class_pattern})[^\"']*[\"'][^>]*>.*?</li>",
    ]
    blocks: list[str] = []
    for pattern in patterns:
        blocks.extend(re.findall(pattern, html_text, flags=re.IGNORECASE | re.DOTALL))
    return blocks


def _text_by_classes(html_text: str, class_keywords: Iterable[str]) -> list[str]:
    return extract_visible_text_by_class(html_text, class_keywords)


def _extract_review_id(html_text: str) -> str | None:
    match = re.search(
        r"(?:data-review-id|data-comment-id|id)=[\"']([^\"']+)[\"']",
        html_text,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else None


def _extract_rating_from_html(html_text: str) -> float | None:
    match = re.search(
        r"(?:rating|rate|score)[^0-9]{0,20}(\d+(?:[.,]\d+)?)",
        html_text,
        flags=re.IGNORECASE,
    )
    return parse_rating(match.group(1)) if match else None


def _extract_date_from_html(html_text: str) -> str | None:
    match = re.search(r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b", html_text)
    return match.group(1) if match else None


def _extract_helpful_count(html_text: str) -> int | None:
    match = re.search(
        r"(?:faydal[ıi]|helpful|like)[^0-9]{0,30}(\d+)",
        html_text,
        flags=re.IGNORECASE,
    )
    return parse_int(match.group(1)) if match else None
