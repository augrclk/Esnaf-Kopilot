from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse


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


def extract_meta_contents(html_text: str, names: Iterable[str]) -> list[str]:
    name_set = {name.lower() for name in names}
    values: list[str] = []
    for tag in re.findall(r"<meta\b[^>]*>", html_text, flags=re.IGNORECASE):
        attrs = parse_attrs(tag)
        attr_name = (attrs.get("name") or attrs.get("property") or "").lower()
        content = attrs.get("content")
        if attr_name in name_set and content:
            values.append(html.unescape(content).strip())
    return values


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


def first_json_ld_product(html_text: str) -> dict[str, Any]:
    products = extract_json_ld_products(html_text)
    return products[0] if products else {}


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


def extract_h1_text(html_text: str) -> str | None:
    match = re.search(r"<h1\b[^>]*>(.*?)</h1>", html_text, re.IGNORECASE | re.DOTALL)
    return normalize_text(match.group(1)) if match else None


def extract_img_urls(html_text: str) -> list[str]:
    urls: list[str] = []
    for tag in re.findall(r"<img\b[^>]*>", html_text, flags=re.IGNORECASE):
        attrs = parse_attrs(tag)
        for attr_name in ("src", "data-src", "data-original", "data-ll-src"):
            value = attrs.get(attr_name)
            if value:
                urls.append(value)
        srcset = attrs.get("srcset") or attrs.get("data-srcset")
        if srcset:
            urls.extend(_srcset_urls(srcset))
    return urls


def extract_script_json_objects(html_text: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    scripts = re.findall(
        r"<script\b[^>]*>(.*?)</script>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for script in scripts:
        script_text = _unescape_javascript_html(html.unescape(script))
        if "image" not in script_text.lower() and "cdn.dsmcdn.com" not in script_text:
            continue
        objects.extend(_balanced_json_objects(script_text))
    return objects


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


def flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for nested in value.values():
            strings.extend(flatten_strings(nested))
        return strings
    if isinstance(value, list):
        strings = []
        for nested in value:
            strings.extend(flatten_strings(nested))
        return strings
    return []


def parse_attrs(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    pattern = re.compile(r"([\w:-]+)\s*=\s*([\"'])(.*?)\2", re.DOTALL)
    for key, _, value in pattern.findall(tag):
        attrs[key.lower()] = html.unescape(value)
    return attrs


def _srcset_urls(srcset: str) -> list[str]:
    urls: list[str] = []
    for candidate in srcset.split(","):
        url = candidate.strip().split(" ", 1)[0]
        if url:
            urls.append(url)
    return urls


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


def _unescape_javascript_html(value: str) -> str:
    replacements = {
        "\\u003C": "<",
        "\\u003c": "<",
        "\\u003E": ">",
        "\\u003e": ">",
        "\\u0022": '"',
        "\\u0027": "'",
        '\\"': '"',
        "\\/": "/",
    }
    result = value
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result


def _balanced_json_objects(text: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for start_index, char in enumerate(text):
        if char != "{":
            continue

        raw_json = _balanced_json_at(text, start_index)
        if not raw_json:
            continue

        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            objects.append(payload)
    return objects


def _balanced_json_at(text: str, start_index: int) -> str | None:
    depth = 0
    in_string = False
    escape = False
    for index in range(start_index, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start_index : index + 1]
    return None
