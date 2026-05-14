from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

from ecommerce_scraper.html_parsing import (
    extract_h1_text,
    extract_meta_content,
    extract_next_data,
    extract_product_id_from_url,
    extract_text_by_attrs,
    extract_visible_text_by_class,
    find_first_key,
    find_values_by_keys,
    first_json_ld_product,
    first_non_empty,
    normalize_text,
    parse_html_reviews,
    parse_json_reviews,
)
from ecommerce_scraper.http_client import HttpClient
from ecommerce_scraper.types import Product, ProductParseError, Review, ScraperConfig

DESCRIPTION_SCRIPT = """
() => {
  const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim();
  const clean = (value) => {
    let text = normalize(value);
    text = text.replace(/^Ürün Açıklaması\\s*/i, "").trim();
    return text;
  };

  const directSelectors = [
    "#rich-content-wrapper",
    '[data-testid="product-description-content"]',
    "#product-content-wrapper",
    ".content-description-content",
    ".product-content-wrapper__text",
  ];
  for (const selector of directSelectors) {
    const element = document.querySelector(selector);
    const text = clean(element?.innerText);
    if (text) return text;
  }

  const headingCandidates = Array.from(
    document.querySelectorAll("h1,h2,h3,h4,h5,span,div,p,strong")
  );
  const heading = headingCandidates.find((element) => {
    return normalize(element.innerText).toLocaleLowerCase("tr-TR") ===
      "ürün açıklaması";
  });
  if (!heading) return null;

  const containers = [
    heading.parentElement,
    heading.parentElement?.parentElement,
    heading.parentElement?.parentElement?.parentElement,
    heading.closest("section"),
    heading.closest("div"),
  ].filter(Boolean);

  for (const container of containers) {
    const text = clean(container.innerText);
    if (text && text.toLocaleLowerCase("tr-TR") !== "ürün açıklaması") {
      return text;
    }
  }

  let sibling = heading.nextElementSibling;
  const parts = [];
  while (sibling && parts.length < 8) {
    const text = clean(sibling.innerText);
    if (text) parts.push(text);
    sibling = sibling.nextElementSibling;
  }
  return clean(parts.join(" "));
}
"""


class TrendyolAdapter:
    platform = "trendyol"

    def __init__(self, client: HttpClient, config: ScraperConfig) -> None:
        self.client = client
        self.config = config

    @staticmethod
    def can_handle(url: str) -> bool:
        return "trendyol.com" in url.lower()

    def extract_product(self, url: str) -> Product:
        html_text = self.client.get(url).text
        product = self.parse_product_html(url, html_text)
        if product.description:
            return product

        api_description = self._extract_description_from_detail_endpoints(product)
        if api_description:
            return _product_with_description(product, api_description)

        rendered_description = self._extract_description_from_rendered_page(product.url)
        if rendered_description:
            return _product_with_description(product, rendered_description)

        return product

    def extract_reviews(self, url: str, product: Product) -> list[Review]:
        endpoint_reviews = self._extract_reviews_from_endpoints(product)
        if endpoint_reviews:
            return endpoint_reviews

        reviews_url = _reviews_page_url(url)
        reviews_html = self.client.get(reviews_url).text
        reviews = self.parse_visible_reviews_html(
            reviews_url,
            product,
            reviews_html,
            page_number=1,
        )
        if reviews:
            return reviews

        html_text = self.client.get(url).text
        return self.parse_visible_reviews_html(url, product, html_text, page_number=1)

    def parse_product_html(self, url: str, html_text: str) -> Product:
        json_ld_product = first_json_ld_product(html_text)
        next_data = extract_next_data(html_text)

        title = first_non_empty(
            json_ld_product.get("name"),
            _next_data_value(next_data, {"name", "title", "productName"}),
            extract_meta_content(html_text, {"og:title", "twitter:title"}),
            *_title_candidates(html_text),
        )
        description = first_non_empty(
            *_description_candidates(html_text),
            *_structured_description_candidates(next_data),
            *_script_description_candidates(html_text),
            _safe_fallback_description(json_ld_product.get("description")),
            _safe_fallback_description(_meta_description(html_text)),
        )

        if not title:
            raise ProductParseError("Trendyol ürün başlığı bulunamadı.")

        return Product(
            platform=self.platform,
            url=url,
            product_id=extract_product_id_from_url(url),
            title=title,
            description=description or "",
        )

    def parse_visible_reviews_html(
        self,
        url: str,
        product: Product,
        html_text: str,
        page_number: int | None,
    ) -> list[Review]:
        return parse_html_reviews(
            html_text,
            platform=self.platform,
            product=product,
            source_url=url,
            page_number=page_number,
            collected_at=self.now_iso(),
            block_class_terms=("comment", "review"),
            text_classes=(
                "comment-text",
                "review-text",
                "commentText",
                "reviewText",
            ),
            title_classes=("review-title", "summary"),
            user_classes=("user-name", "username", "member"),
            variant_classes=("variant", "attribute"),
        )

    def _extract_description_from_detail_endpoints(
        self,
        product: Product,
    ) -> str | None:
        if not product.product_id:
            return None

        endpoint_urls = [
            *_product_description_stream_endpoint_candidates(product),
            *_product_detail_endpoint_candidates(product),
        ]
        for endpoint_url in endpoint_urls:
            try:
                payload = self.client.get_json(endpoint_url)
            except Exception:
                continue

            description = first_non_empty(
                *_trendyol_product_description_stream_candidates(payload),
                *_trendyol_api_description_candidates(payload),
                *_structured_description_candidates(payload),
            )
            if description:
                return description
        return None

    def _extract_description_from_rendered_page(self, url: str) -> str | None:
        if not self.config.use_rendered_html_fallback:
            return None

        text = get_rendered_product_description(
            url,
            timeout_seconds=self.config.rendered_html_timeout_seconds,
        )
        return _safe_fallback_description(text)

    def _extract_reviews_from_endpoints(self, product: Product) -> list[Review]:
        if not product.product_id:
            return []

        reviews: list[Review] = []
        for page_number in range(1, self.config.max_review_pages + 1):
            page_reviews = self._extract_review_page(product, page_number)
            if not page_reviews:
                break
            reviews.extend(page_reviews)
        return reviews

    def _extract_review_page(self, product: Product, page_number: int) -> list[Review]:
        product_id = product.product_id or ""
        endpoint_candidates = _review_endpoint_candidates(
            product_id,
            product.url,
            page_number,
        )
        for endpoint_url in endpoint_candidates:
            try:
                payload = self.client.get_json(endpoint_url)
            except Exception:
                continue

            reviews = self._parse_reviews_json(
                payload,
                product,
                page_number,
                endpoint_url,
            )
            if reviews:
                return reviews
        return []

    def _parse_reviews_json(
        self,
        payload: Any,
        product: Product,
        page_number: int,
        source_url: str,
    ) -> list[Review]:
        return parse_json_reviews(
            payload,
            platform=self.platform,
            product=product,
            page_number=page_number,
            source_url=source_url,
            collected_at=self.now_iso(),
            date_keys=(
                "commentDate",
                "reviewDate",
                "date",
                "createdDate",
                "created_at",
            ),
            user_keys=(
                "userFullName",
                "user_full_name",
                "userName",
                "nickname",
                "memberName",
            ),
        )

    @staticmethod
    def now_iso() -> str:
        return datetime.now(UTC).isoformat()


def _title_candidates(html_text: str) -> list[str | None]:
    return [
        *extract_visible_text_by_class(
            html_text,
            ("pr-new-br", "product-title", "product-name"),
        ),
        extract_h1_text(html_text),
    ]


def _product_with_description(product: Product, description: str) -> Product:
    return Product(
        platform=product.platform,
        url=product.url,
        product_id=product.product_id,
        title=product.title,
        description=description,
    )


def _description_candidates(html_text: str) -> list[str]:
    return [
        _product_description_content(html_text),
        *extract_visible_text_by_class(
            html_text,
            (
                "content-description-content",
                "product-content-wrapper__text",
                "product-description",
            ),
        ),
    ]


def _product_description_content(html_text: str) -> str | None:
    return first_non_empty(
        _rich_content_wrapper_text(html_text),
        extract_text_by_attrs(html_text, {"id": "rich-content-wrapper"}),
        extract_text_by_attrs(
            html_text,
            {"data-testid": "product-description-content"},
        ),
        extract_text_by_attrs(html_text, {"id": "product-content-wrapper"}),
    )


def _rich_content_wrapper_text(html_text: str) -> str | None:
    for html_variant in _html_variants(html_text):
        for inner_html in (
            _extract_element_inner_html_by_id(html_variant, "rich-content-wrapper"),
            _extract_rich_content_by_marker(html_variant),
        ):
            text = _clean_rich_content_text(normalize_text(inner_html))
            if text:
                return text
    return None


def _html_variants(html_text: str) -> list[str]:
    unescaped_html = html.unescape(html_text)
    js_unescaped_html = _unescape_javascript_html(unescaped_html)
    deeply_unescaped_html = _deep_unescape_javascript_html(unescaped_html)
    return [html_text, unescaped_html, js_unescaped_html, deeply_unescaped_html]


def _unescape_javascript_html(value: str) -> str:
    replacements = {
        "\\u003C": "<",
        "\\u003c": "<",
        "\\u003E": ">",
        "\\u003e": ">",
        "\\u0022": '"',
        "\\u0027": "'",
        '\\"': '"',
        "\\'": "'",
        "\\/": "/",
    }
    result = value
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result


def _deep_unescape_javascript_html(value: str) -> str:
    result = value
    for _ in range(3):
        next_result = _unescape_javascript_html(result)
        next_result = next_result.replace("\\\\", "\\")
        if next_result == result:
            break
        result = next_result
    return result


def _extract_element_inner_html_by_id(html_text: str, element_id: str) -> str | None:
    html_text = _normalize_attribute_quotes(html_text, element_id)
    start_match = re.search(
        rf"<(?P<tag>[a-z0-9]+)\b[^>]*\bid\s*=\s*"
        rf"(?:[\"']{re.escape(element_id)}[\"']|{re.escape(element_id)})"
        r"[^>]*>",
        html_text,
        flags=re.IGNORECASE,
    )
    if not start_match:
        return None

    tag = start_match.group("tag")
    content_start = start_match.end()
    tag_pattern = re.compile(
        rf"</?{re.escape(tag)}\b[^>]*>",
        flags=re.IGNORECASE,
    )
    depth = 1
    for match in tag_pattern.finditer(html_text, content_start):
        if match.group(0).startswith("</"):
            depth -= 1
        else:
            depth += 1
        if depth == 0:
            return html_text[content_start : match.start()]
    return html_text[content_start:]


def _extract_rich_content_by_marker(html_text: str) -> str | None:
    marker_index = html_text.find("rich-content-wrapper")
    if marker_index == -1:
        return None

    start_index = html_text.rfind("<div", 0, marker_index)
    if start_index == -1:
        return None

    fragment = html_text[start_index:]
    inner_html = _extract_element_inner_html_by_id(fragment, "rich-content-wrapper")
    if inner_html:
        return inner_html

    end_index = _first_following_section_index(fragment)
    return fragment[:end_index] if end_index else fragment


def _first_following_section_index(fragment: str) -> int | None:
    candidates = [
        fragment.find('id="reviews"'),
        fragment.find("id='reviews'"),
        fragment.find("comments-summary"),
        fragment.find("product-attributes"),
        fragment.find("Öne Çıkan Özellikler"),
        fragment.find("Ürün Özellikleri"),
    ]
    positive_candidates = [candidate for candidate in candidates if candidate > 0]
    return min(positive_candidates) if positive_candidates else None


def _clean_rich_content_text(text: str) -> str:
    text = text.replace("\\", "")
    text = re.sub(r'";?$', "", text).strip()
    return normalize_text(text)


def _normalize_attribute_quotes(value: str, element_id: str) -> str:
    return value.replace(
        f'id=\\"{element_id}\\"',
        f'id="{element_id}"',
    ).replace(
        f"id=\\'{element_id}\\'",
        f"id='{element_id}'",
    )


def _structured_description_candidates(data: dict[str, Any] | None) -> list[str]:
    if not data:
        return []

    candidates: list[str] = []
    values = find_values_by_keys(
        data,
        {
            "productDescription",
            "productDescriptionContent",
            "productContent",
            "contentDescription",
            "contentDescriptions",
            "description",
            "htmlContentData",
            "initialDescriptionHTML",
            "webProductDescription",
        },
    )
    for value in values:
        text = _description_value_to_text(value)
        if text and _looks_like_product_description(text):
            candidates.append(text)
    return candidates


def _trendyol_api_description_candidates(data: Any) -> list[str]:
    candidates: list[str] = []
    for descriptions in find_values_by_keys(data, {"descriptions"}):
        candidates.extend(_descriptions_node_to_texts(descriptions))
    return [text for text in candidates if _looks_like_product_description(text)]


def _trendyol_product_description_stream_candidates(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return []

    candidates: list[str] = []
    main = data.get("main")
    if isinstance(main, str):
        candidates.extend(_description_candidates(main))
        candidates.extend(_script_description_candidates(main))

    return [text for text in candidates if _looks_like_product_description(text)]


def _descriptions_node_to_texts(value: Any) -> list[str]:
    if isinstance(value, dict):
        content_descriptions = value.get("content_descriptions")
        if content_descriptions is None:
            content_descriptions = value.get("contentDescriptions")
        if isinstance(content_descriptions, list):
            return _description_items_to_texts(content_descriptions)
        return _description_items_to_texts(list(value.values()))

    if isinstance(value, list):
        return _description_items_to_texts(value)

    text = _description_value_to_text(value)
    return [text] if text else []


def _description_items_to_texts(items: list[Any]) -> list[str]:
    texts: list[str] = []
    for item in items:
        if isinstance(item, dict):
            if _skip_description_item(item):
                continue
            text = first_non_empty(item.get("description"), item.get("text"))
        else:
            text = _description_value_to_text(item)
        if text:
            texts.append(text)
    return texts


def _skip_description_item(item: dict[str, Any]) -> bool:
    item_type = normalize_text(item.get("type")).casefold()
    if item_type in {"legal", "merchant_info", "cargo", "campaign"}:
        return True

    priority = item.get("priority")
    if isinstance(priority, int) and priority >= 1000:
        return True

    text = first_non_empty(item.get("description"), item.get("text")) or ""
    lowered = text.casefold()
    skip_markers = (
        "trendyol tarafından gönderilecektir",
        "siparişleri trendyol iptal etme hakkını",
        "bir ürün, birden fazla satıcı",
        "kampanya fiyatından",
    )
    return any(marker in lowered for marker in skip_markers)


def _script_description_candidates(html_text: str) -> list[str]:
    candidates: list[str] = []
    for payload in _json_objects_from_scripts(html_text):
        candidates.extend(_structured_description_candidates(payload))
    return candidates


def _json_objects_from_scripts(html_text: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    scripts = re.findall(
        r"<script\b[^>]*>(.*?)</script>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for script in scripts:
        script_text = html.unescape(script)
        if "description" not in script_text and "Description" not in script_text:
            continue
        objects.extend(_balanced_json_objects(script_text))
    return objects


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


def _description_value_to_text(value: Any) -> str | None:
    if isinstance(value, str):
        return normalize_text(value)
    if isinstance(value, list):
        parts = [_description_value_to_text(item) for item in value]
        return normalize_text(" ".join(part for part in parts if part))
    if isinstance(value, dict):
        parts = [_description_value_to_text(item) for item in value.values()]
        return normalize_text(" ".join(part for part in parts if part))
    return None


def _product_detail_endpoint_candidates(product: Product) -> list[str]:
    product_id = product.product_id or ""
    merchant_id = _merchant_id_from_url(product.url)
    merchant_query = f"&merchantId={merchant_id}" if merchant_id else ""
    common_query = (
        f"{merchant_query}&storefrontId=1&culture=tr-TR"
        "&linearVariants=true&isLegalRequirementConfirmed=false"
    )
    return [
        (
            "https://apigw.trendyol.com/"
            f"discovery-web-productgw-service/api/productDetail/{product_id}"
            f"?{common_query.lstrip('&')}"
        ),
        (
            "https://apigw.trendyol.com/"
            f"discovery-web-productgw-service/api/productGroup/{product_id}"
            f"?{common_query.lstrip('&')}"
        ),
        (
            "https://apigw.trendyol.com/"
            "discovery-storefront-web-productgw-service/api/productDetail/"
            f"{product_id}?{common_query.lstrip('&')}"
        ),
        (
            "https://apigw.trendyol.com/"
            "discovery-storefront-web-productgw-service/api/productGroup/"
            f"{product_id}?{common_query.lstrip('&')}"
        ),
        (
            "https://public-mdc.trendyol.com/"
            f"discovery-web-productgw-service/api/productDetail/{product_id}"
            f"?{common_query.lstrip('&')}"
        ),
        (
            "https://public-mdc.trendyol.com/"
            f"discovery-web-productgw-service/api/productGroup/{product_id}"
            f"?{common_query.lstrip('&')}"
        ),
    ]


def _product_description_stream_endpoint_candidates(product: Product) -> list[str]:
    parsed_url = urlparse(product.url)
    if not parsed_url.path:
        return []

    query_items = [
        ("__renderMode", "stream"),
        *parse_qsl(parsed_url.query, keep_blank_values=True),
        ("isMobile", "false"),
        ("storefrontId", "1"),
        ("channelId", "1"),
        ("language", "tr"),
        ("countryCode", "TR"),
        ("type", "product-description"),
    ]
    query = urlencode(query_items)
    return [
        (
            "https://apigw.trendyol.com/"
            "discovery-storefront-trproductgw-service/product-description"
            f"{parsed_url.path}?{query}"
        ),
    ]


def _safe_fallback_description(value: Any) -> str | None:
    text = normalize_text(value)
    if not text or _looks_like_seo_description(text):
        return None
    return text


def _looks_like_product_description(text: str) -> bool:
    return bool(text) and not _looks_like_seo_description(text)


def _looks_like_seo_description(text: str) -> bool:
    lowered = text.casefold()
    seo_markers = (
        "yorumlarını inceleyin",
        "trendyol'a özel",
        "indirimli fiyata satın alın",
        "satın alın",
    )
    return any(marker in lowered for marker in seo_markers)


def _review_endpoint_candidates(
    product_id: str,
    product_url: str,
    page_number: int,
) -> list[str]:
    page_index = page_number - 1
    page_size = 30
    urls = [
        (
            "https://apigw.trendyol.com/"
            "discovery-storefront-trproductgw-service/api/review-read/"
            f"product-reviews/detailed?contentId={product_id}&page={page_index}"
            f"&pageSize={page_size}&order=DESC&orderBy=Score&channelId=1"
        ),
        (
            "https://public-mdc.trendyol.com/"
            "discovery-storefront-trproductgw-service/api/review-read/"
            f"product-reviews/detailed?contentId={product_id}&page={page_index}"
            f"&pageSize={page_size}&order=DESC&orderBy=Score&channelId=1"
        ),
        (
            "https://public-sdc.trendyol.com/"
            "discovery-storefront-trproductgw-service/api/review-read/"
            f"product-reviews/detailed?contentId={product_id}&page={page_index}"
            f"&pageSize={page_size}&order=DESC&orderBy=Score&channelId=1"
        ),
        (
            "https://public-mdc.trendyol.com/"
            "discovery-web-websfxproductreviews-santral/"
            f"product-reviews-detailed?contentId={product_id}&page={page_index}"
            f"&size={page_size}&culture=tr-TR&storefrontId=1&channelId=1"
        ),
        (
            "https://public-mdc.trendyol.com/"
            "discovery-web-websfxproductreviews-santral/"
            f"product-reviews-detailed?productId={product_id}&page={page_index}"
            f"&size={page_size}&culture=tr-TR&storefrontId=1&channelId=1"
        ),
        (
            "https://public-mdc.trendyol.com/discovery-web-socialgw-service/api/review/"
            f"{product_id}?page={page_index}&size={page_size}"
        ),
    ]

    merchant_id = _merchant_id_from_url(product_url)
    if merchant_id:
        urls.insert(
            1,
            (
                "https://apigw.trendyol.com/"
                "discovery-web-websfxsocialreviewrating-santral/"
                "product-reviews-detailed?"
                f"sellerId={merchant_id}&contentId={product_id}"
                f"&page={page_index}&pageSize={page_size}"
                "&culture=tr-TR&channelId=1&storefrontId=1"
            ),
        )

    return urls


def _merchant_id_from_url(product_url: str) -> str | None:
    query = parse_qs(urlparse(product_url).query)
    values = query.get("merchantId")
    return values[0] if values else None


def _reviews_page_url(product_url: str) -> str:
    parsed_url = urlparse(product_url)
    path = parsed_url.path.rstrip("/")
    if not path.endswith("/yorumlar"):
        path = f"{path}/yorumlar"
    return urlunparse(parsed_url._replace(path=path))


def get_rendered_product_description(url: str, timeout_seconds: float) -> str | None:
    try:
        from playwright.sync_api import Error, TimeoutError, sync_playwright
    except ImportError:
        return None

    timeout_ms = int(timeout_seconds * 1000)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(locale="tr-TR")
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                text = _evaluate_description(page)
                if text:
                    return text

                for position in (800, 1600, 2400, 3200, 4500, 6000):
                    page.evaluate("y => window.scrollTo(0, y)", position)
                    page.wait_for_timeout(900)
                    text = _evaluate_description(page)
                    if text:
                        return text

                try:
                    page.wait_for_load_state("networkidle", timeout=3000)
                except TimeoutError:
                    pass
                return _evaluate_description(page)
            except (Error, TimeoutError):
                return _evaluate_description(page)
            finally:
                browser.close()
    except Exception:
        return None


def _evaluate_description(page: object) -> str | None:
    try:
        text = page.evaluate(DESCRIPTION_SCRIPT)
    except Exception:
        return None
    return text.strip() if isinstance(text, str) and text.strip() else None


def _next_data_value(data: dict[str, Any] | None, keys: set[str]) -> Any:
    return find_first_key(data, keys) if data else None


def _meta_description(html_text: str) -> str | None:
    return extract_meta_content(
        html_text,
        {"description", "og:description", "twitter:description"},
    )
