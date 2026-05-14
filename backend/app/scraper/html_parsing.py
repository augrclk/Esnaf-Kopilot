"""
HTML / JSON parsing yardımcıları.

Bu modül saf fonksiyonlardan oluşur — hiçbir state tutmaz.
Her fonksiyon tek bir görevi yapar ve bağımsız test edilebilir.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Metin temizleme
# ---------------------------------------------------------------------------


def clean_text(value: Any) -> str:
    """HTML tag'lerini temizler, whitespace'i düzenler, string döner."""
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)   # HTML taglerini kaldır
    text = re.sub(r"\s+", " ", text)        # Birden fazla boşluğu teke indir
    return text.strip()


def first_non_empty(*values: Any) -> str | None:
    """Verilen değerler arasından ilk boş olmayanı döner."""
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return None


# ---------------------------------------------------------------------------
# URL yardımcıları
# ---------------------------------------------------------------------------


def extract_product_id(url: str) -> str | None:
    """Trendyol URL'inden ürün ID'sini çıkarır. Örn: -p-962087817 → '962087817'"""
    for pattern in (r"-p-(\d+)", r"/p-(\d+)", r"productId=(\d+)"):
        match = re.search(pattern, url, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    # Son çare: URL'nin son segmentini al
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    return slug or None


# ---------------------------------------------------------------------------
# Meta tag parsing
# ---------------------------------------------------------------------------


def extract_meta(html_text: str, names: set[str]) -> str | None:
    """
    <meta> taglerinden belirtilen property/name'e ait content değerini döner.
    Örn: names={"og:title"} → og:title meta tag'inin content'ini döner.
    """
    lowered_names = {n.lower() for n in names}
    for tag in re.findall(r"<meta\b[^>]*>", html_text, flags=re.IGNORECASE):
        attrs = _parse_tag_attrs(tag)
        attr_name = (attrs.get("name") or attrs.get("property") or "").lower()
        if attr_name in lowered_names and attrs.get("content"):
            return clean_text(attrs["content"])
    return None


def extract_all_meta(html_text: str, names: set[str]) -> list[str]:
    """extract_meta'nın çok değer dönen versiyonu."""
    lowered_names = {n.lower() for n in names}
    results: list[str] = []
    for tag in re.findall(r"<meta\b[^>]*>", html_text, flags=re.IGNORECASE):
        attrs = _parse_tag_attrs(tag)
        attr_name = (attrs.get("name") or attrs.get("property") or "").lower()
        if attr_name in lowered_names and attrs.get("content"):
            results.append(html.unescape(attrs["content"]).strip())
    return results


# ---------------------------------------------------------------------------
# JSON-LD parsing
# ---------------------------------------------------------------------------


def extract_json_ld_product(html_text: str) -> dict[str, Any]:
    """
    Sayfadaki application/ld+json script'lerinden @type=Product olan ilk objeyi döner.
    Bulunamazsa boş dict döner.
    """
    pattern = re.compile(
        r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(html_text):
        raw = html.unescape(match.group(1)).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        product = _find_product_node(data if isinstance(data, list) else [data])
        if product:
            return product
    return {}


# ---------------------------------------------------------------------------
# __NEXT_DATA__ parsing
# ---------------------------------------------------------------------------


def extract_next_data(html_text: str) -> dict[str, Any] | None:
    """Next.js'in __NEXT_DATA__ script tag'inden JSON verisini çıkarır."""
    match = re.search(
        r'<script\b[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    try:
        data = json.loads(html.unescape(match.group(1)).strip())
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# JSON içinde key arama
# ---------------------------------------------------------------------------


def find_value(data: Any, key: str) -> Any:
    """Nested dict/list içinde verilen key'i bulur, ilk değeri döner."""
    if isinstance(data, dict):
        if key in data and data[key] not in (None, ""):
            return data[key]
        for v in data.values():
            result = find_value(v, key)
            if result is not None:
                return result
    elif isinstance(data, list):
        for item in data:
            result = find_value(item, key)
            if result is not None:
                return result
    return None


def find_all_values(data: Any, keys: set[str]) -> list[Any]:
    """Nested dict/list içinde verilen key'lere ait tüm değerleri döner."""
    results: list[Any] = []
    if isinstance(data, dict):
        for k, v in data.items():
            if k in keys and v not in (None, ""):
                results.append(v)
            results.extend(find_all_values(v, keys))
    elif isinstance(data, list):
        for item in data:
            results.extend(find_all_values(item, keys))
    return results


# ---------------------------------------------------------------------------
# Görsel URL yardımcıları
# ---------------------------------------------------------------------------


def extract_img_urls(html_text: str) -> list[str]:
    """HTML içindeki <img> tag'lerinden src/data-src URL'lerini çeker."""
    urls: list[str] = []
    for tag in re.findall(r"<img\b[^>]*>", html_text, flags=re.IGNORECASE):
        attrs = _parse_tag_attrs(tag)
        for attr in ("src", "data-src", "data-original"):
            if attrs.get(attr):
                urls.append(attrs[attr])
        srcset = attrs.get("srcset") or attrs.get("data-srcset")
        if srcset:
            urls.extend(u.strip().split(" ")[0] for u in srcset.split(",") if u.strip())
    return [u for u in urls if u]


def flatten_to_strings(value: Any) -> list[str]:
    """Nested dict/list/string yapısını düz string listesine dönüştürür."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(flatten_to_strings(item))
        return result
    if isinstance(value, dict):
        result = []
        for v in value.values():
            result.extend(flatten_to_strings(v))
        return result
    return []


# ---------------------------------------------------------------------------
# Script JSON parsing
# ---------------------------------------------------------------------------


def extract_script_json_objects(html_text: str, keyword: str) -> list[dict[str, Any]]:
    """
    <script> tag'leri içinde keyword geçen JSON objelerini çıkarır.
    Keyword filtresi gereksiz parse işlemini önler.
    """
    objects: list[dict[str, Any]] = []
    scripts = re.findall(
        r"<script\b[^>]*>(.*?)</script>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for script in scripts:
        unescaped = _unescape_js(html.unescape(script))
        if keyword.lower() not in unescaped.lower():
            continue
        objects.extend(_parse_json_objects_from_text(unescaped))
    return objects


# ---------------------------------------------------------------------------
# H1 parsing
# ---------------------------------------------------------------------------


def extract_h1(html_text: str) -> str | None:
    """Sayfadaki ilk <h1> tag'inin metin içeriğini döner."""
    match = re.search(r"<h1\b[^>]*>(.*?)</h1>", html_text, flags=re.IGNORECASE | re.DOTALL)
    return clean_text(match.group(1)) if match else None


def extract_text_by_class(html_text: str, class_name: str) -> str | None:
    """Belirtilen CSS class'ına sahip ilk elementin metin içeriğini döner."""
    pattern = re.compile(
        rf'<(?P<tag>[a-z0-9]+)\b[^>]*class=["\'][^"\']*{re.escape(class_name)}[^"\']*["\'][^>]*>'
        r"(?P<body>.*?)</(?P=tag)>",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(html_text)
    return clean_text(match.group("body")) if match else None


# ---------------------------------------------------------------------------
# Dahili yardımcılar
# ---------------------------------------------------------------------------


def _parse_tag_attrs(tag: str) -> dict[str, str]:
    """HTML tag'inden attribute dict'i çıkarır."""
    attrs: dict[str, str] = {}
    for key, _, value in re.findall(r'([\w:-]+)\s*=\s*(["\'])(.*?)\2', tag, re.DOTALL):
        attrs[key.lower()] = html.unescape(value)
    return attrs


def _find_product_node(items: list[Any]) -> dict[str, Any] | None:
    """JSON-LD item listesinde @type=Product olan objeyi bulur."""
    for item in items:
        if not isinstance(item, dict):
            continue
        node_type = item.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if any(str(t).lower() == "product" for t in types):
            return item
        # @graph içinde de ara
        if "@graph" in item:
            found = _find_product_node(
                item["@graph"] if isinstance(item["@graph"], list) else [item["@graph"]]
            )
            if found:
                return found
    return None


def _unescape_js(text: str) -> str:
    """JavaScript unicode escape'lerini çözer (\u003c → <)."""
    replacements = {
        "\\u003C": "<", "\\u003c": "<",
        "\\u003E": ">", "\\u003e": ">",
        "\\u0022": '"', "\\u0027": "'",
        '\\"': '"', "\\/": "/",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _parse_json_objects_from_text(text: str) -> list[dict[str, Any]]:
    """Metin içindeki tüm geçerli JSON objelerini parse eder."""
    objects: list[dict[str, Any]] = []
    depth = 0
    in_string = False
    escape = False
    start = -1

    for i, char in enumerate(text):
        if in_string:
            escape = char == "\\" and not escape
            if char == '"' and not escape:
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = i
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start != -1:
                try:
                    obj = json.loads(text[start : i + 1])
                    if isinstance(obj, dict):
                        objects.append(obj)
                except json.JSONDecodeError:
                    pass

    return objects
