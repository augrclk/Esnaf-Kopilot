"""
Trendyol scraper — ürün başlığı, açıklama, yorumlar ve görseller.

Çalışma mantığı:
  Her veri tipi için birden fazla kaynak denenir (fallback zinciri).
  İlk başarılı kaynak kullanılır, diğerleri atlanır.

  Ürün başlık/açıklama kaynakları (öncelik sırasıyla):
    1. JSON-LD structured data       — en güvenilir
    2. __NEXT_DATA__ (Next.js)       — genellikle tam veri var
    3. Trendyol API endpoint'leri    — HTML'de bulunamayınca
    4. Sayfadaki HTML elementleri    — son çare
    5. Playwright rendered HTML      — JS ile yüklenen içerik (opsiyonel)

  Yorum kaynakları:
    1. Trendyol review API'leri      — sayfalı, tam veri
    2. HTML yorumlar sayfası         — fallback

  Görsel kaynakları:
    1. JSON-LD image alanı           — en güvenilir
    2. og:image meta tag'leri        — çoğu zaman ana görsel
    3. __NEXT_DATA__ image key'leri  — ürün galerisini içerir
    4. Script JSON'larında image key'leri
    5. CDN URL regex (cdn.dsmcdn.com) — en geniş ağ
"""

from __future__ import annotations

import hashlib
import html as html_lib
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from app.models import (
    Product,
    ProductImage,
    ProductNotFoundError,
    Review,
    ScrapedProduct,
)
from app.scraper.html_parsing import (
    clean_text,
    extract_all_meta,
    extract_h1,
    extract_img_urls,
    extract_json_ld_product,
    extract_meta,
    extract_next_data,
    extract_product_id,
    extract_script_json_objects,
    extract_text_by_class,
    find_all_values,
    find_value,
    first_non_empty,
    flatten_to_strings,
)
from app.scraper.http_client import HttpClient

# Trendyol görsellerinin CDN adresi
_CDN_HOST = "cdn.dsmcdn.com"

# __NEXT_DATA__ ve script JSON'larında görsel URL içeren key'ler
_IMAGE_KEYS = {
    "image", "images", "imageUrl", "imageUrls", "imageURL",
    "imageList", "imageUrlList", "productImages", "productImage",
    "originalImageUrl", "originalImage",
}


class TrendyolScraper:
    """
    Trendyol ürün sayfasından veri çeken ana sınıf.

    Kullanım:
        scraper = TrendyolScraper(HttpClient())
        result = scraper.scrape("https://www.trendyol.com/...")
    """

    def __init__(self, client: HttpClient) -> None:
        self._client = client

    @staticmethod
    def supports(url: str) -> bool:
        """Bu scraper'ın verilen URL'yi işleyip işleyemeyeceğini döner."""
        return "trendyol.com" in url.lower()

    def scrape(self, url: str, max_review_pages: int = 50) -> ScrapedProduct:
        """
        Verilen Trendyol URL'inden tüm ürün verilerini çeker.

        Returns:
            ScrapedProduct: Ürün, yorumlar ve görsel listesini içerir.

        Raises:
            ProductNotFoundError: Ürün başlığı bulunamadığında.
            ScraperHttpError: Sayfa yüklenemediğinde.
        """
        page_html = self._client.get_text(url)

        product = self._extract_product(url, page_html)
        reviews = self._extract_reviews(product, max_review_pages)
        images = self._extract_images(url, page_html)

        return ScrapedProduct(product=product, reviews=reviews, images=images)

    def download_images(
        self, images: list[ProductImage], output_dir: str | Path
    ) -> list[ProductImage]:
        """
        Görsel URL listesini indirir, local_path dolu ProductImage listesi döner.
        """
        save_dir = Path(output_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

        downloaded: list[ProductImage] = []
        for image in images:
            ext = _image_extension(image.url)
            file_path = save_dir / f"image_{image.position:02d}{ext}"
            try:
                file_path.write_bytes(self._client.get_bytes(image.url))
                downloaded.append(_replace_path(image, str(file_path)))
            except Exception:
                # Tek bir görselin indirilememesi tüm işlemi durdurmasın
                downloaded.append(image)

        return downloaded

    # ------------------------------------------------------------------
    # Ürün başlık + açıklama
    # ------------------------------------------------------------------

    def _extract_product(self, url: str, page_html: str) -> Product:
        product_id = extract_product_id(url)

        title = self._find_title(page_html)
        if not title:
            raise ProductNotFoundError(f"Ürün başlığı bulunamadı: {url}")

        description = (
            self._find_description_in_html(page_html)
            or self._find_description_via_api(product_id, url)
            or self._find_description_via_playwright(url)
            or ""
        )

        return Product(url=url, product_id=product_id, title=title, description=description)

    def _find_title(self, page_html: str) -> str | None:
        json_ld = extract_json_ld_product(page_html)
        next_data = extract_next_data(page_html)

        return first_non_empty(
            json_ld.get("name"),
            find_value(next_data, "name") if next_data else None,
            find_value(next_data, "productName") if next_data else None,
            extract_meta(page_html, {"og:title"}),
            extract_text_by_class(page_html, "pr-new-br"),
            extract_text_by_class(page_html, "product-name"),
            extract_h1(page_html),
        )

    def _find_description_in_html(self, page_html: str) -> str | None:
        """HTML içindeki açıklama elementlerini tarar."""
        next_data = extract_next_data(page_html)

        candidates = [
            extract_text_by_class(page_html, "content-description-content"),
            extract_text_by_class(page_html, "product-content-wrapper__text"),
            _extract_rich_content(page_html),
        ]
        if next_data:
            for key in ("productDescription", "description", "contentDescription"):
                value = find_value(next_data, key)
                if value:
                    candidates.append(clean_text(value))

        return next(
            (c for c in candidates if c and _is_real_description(c)),
            None,
        )

    def _find_description_via_api(
        self, product_id: str | None, product_url: str
    ) -> str | None:
        """Trendyol'un dahili API endpoint'lerinden açıklama çekmeyi dener."""
        if not product_id:
            return None

        for api_url in _product_api_urls(product_id, product_url):
            try:
                data = self._client.get_json(api_url)
                for key in ("productDescription", "description", "htmlContentData"):
                    value = find_value(data, key)
                    if value:
                        text = clean_text(value)
                        if _is_real_description(text):
                            return text
            except Exception:
                continue

        return None

    def _find_description_via_playwright(self, url: str) -> str | None:
        """Son çare: Playwright ile sayfayı render ederek açıklamayı çeker."""
        try:
            from app.scraper.playwright_helper import get_rendered_description
            return get_rendered_description(url)
        except ImportError:
            return None

    # ------------------------------------------------------------------
    # Yorumlar
    # ------------------------------------------------------------------

    def _extract_reviews(self, product: Product, max_pages: int) -> list[Review]:
        if not product.product_id:
            return []

        reviews: list[Review] = []
        for page in range(1, max_pages + 1):
            page_reviews = self._fetch_review_page(product, page)
            if not page_reviews:
                break
            reviews.extend(page_reviews)

        return _deduplicate_reviews(reviews)

    def _fetch_review_page(self, product: Product, page: int) -> list[Review]:
        """Tek bir yorum sayfasını API'den çeker."""
        for api_url in _review_api_urls(product.product_id or "", product.url, page):
            try:
                data = self._client.get_json(api_url)
                reviews = _parse_reviews_from_json(data, product)
                if reviews:
                    return reviews
            except Exception:
                continue
        return []

    # ------------------------------------------------------------------
    # Görseller
    # ------------------------------------------------------------------

    def _extract_images(self, url: str, page_html: str) -> list[ProductImage]:
        """Sayfadan tüm ürün görsellerini toplar, deduplikasyon yapar."""
        raw_urls: list[str] = []

        # Kaynak 1: JSON-LD
        json_ld = extract_json_ld_product(page_html)
        raw_urls.extend(flatten_to_strings(json_ld.get("image")))

        # Kaynak 2: og:image meta tag'leri
        raw_urls.extend(extract_all_meta(page_html, {"og:image", "og:image:secure_url"}))

        # Kaynak 3: __NEXT_DATA__
        next_data = extract_next_data(page_html)
        if next_data:
            for node in find_all_values(next_data, _IMAGE_KEYS):
                raw_urls.extend(flatten_to_strings(node))

        # Kaynak 4: Script JSON'ları
        for obj in extract_script_json_objects(page_html, "cdn.dsmcdn.com"):
            for node in find_all_values(obj, _IMAGE_KEYS):
                raw_urls.extend(flatten_to_strings(node))

        # Kaynak 5: CDN URL regex — sayfanın ham metninde doğrudan tarama
        raw_urls.extend(_find_cdn_urls(page_html))

        # Normalize et, filtrele, sırala
        product_id = extract_product_id(url)
        seen: set[str] = set()
        images: list[ProductImage] = []

        for position, raw in enumerate(raw_urls, start=1):
            clean_url = _normalize_image_url(raw, base_url=url)
            if not clean_url or not _is_product_image(clean_url):
                continue
            if clean_url in seen:
                continue
            seen.add(clean_url)
            images.append(
                ProductImage(
                    url=clean_url,
                    image_id=_image_hash(clean_url),
                    position=len(images) + 1,
                )
            )

        return images


# ---------------------------------------------------------------------------
# Yorum parsing
# ---------------------------------------------------------------------------


def _parse_reviews_from_json(data: dict, product: Product) -> list[Review]:
    """API yanıtından yorum listesi çıkarır."""
    reviews: list[Review] = []

    # Trendyol API'si farklı formatlarda veri dönebilir
    # Yorum benzeri dict'leri bul: text + rating key'i olan objeler
    candidates = _find_review_like_dicts(data)

    for item in candidates:
        text = first_non_empty(
            item.get("comment"),
            item.get("commentText"),
            item.get("reviewText"),
            item.get("text"),
        )
        if not text:
            continue

        reviews.append(Review(
            review_id=str(item.get("id") or item.get("commentId") or item.get("reviewId") or ""),
            rating=_to_float(item.get("rate") or item.get("rating") or item.get("score")),
            title=first_non_empty(item.get("title"), item.get("summary")),
            text=text,
            date=first_non_empty(
                item.get("commentDate"),
                item.get("reviewDate"),
                item.get("createdDate"),
            ),
            user=first_non_empty(
                item.get("userFullName"),
                item.get("userName"),
                item.get("nickname"),
            ),
            variant=first_non_empty(
                item.get("variant"),
                item.get("productAttributes"),
            ),
            helpful_count=_to_int(item.get("helpfulCount") or item.get("likeCount")),
        ))

    return reviews


def _find_review_like_dicts(data: object) -> list[dict]:
    """
    Nested veri içinde yorum benzeri dict'leri bulur.
    Kriter: text/comment key'i VE rating/id key'i olan dict.
    """
    found: list[dict] = []
    if isinstance(data, dict):
        keys = {k.lower() for k in data}
        has_text = keys & {"comment", "commenttext", "reviewtext", "text"}
        has_rating = keys & {"rate", "rating", "score", "id", "commentid"}
        if has_text and has_rating:
            found.append(data)
        for v in data.values():
            found.extend(_find_review_like_dicts(v))
    elif isinstance(data, list):
        for item in data:
            found.extend(_find_review_like_dicts(item))
    return found


def _deduplicate_reviews(reviews: list[Review]) -> list[Review]:
    seen: set[str] = set()
    unique: list[Review] = []
    for review in reviews:
        key = review.review_id or f"{review.text[:50]}|{review.rating}"
        if key not in seen:
            seen.add(key)
            unique.append(review)
    return unique


# ---------------------------------------------------------------------------
# API URL üreticileri
# ---------------------------------------------------------------------------


def _product_api_urls(product_id: str, product_url: str) -> list[str]:
    """Ürün açıklaması için denenecek API URL'lerini döner."""
    merchant_id = _merchant_id(product_url)
    query = f"storefrontId=1&culture=tr-TR"
    if merchant_id:
        query = f"merchantId={merchant_id}&{query}"

    return [
        f"https://apigw.trendyol.com/discovery-web-productgw-service/api/productDetail/{product_id}?{query}",
        f"https://apigw.trendyol.com/discovery-web-productgw-service/api/productGroup/{product_id}?{query}",
        f"https://public-mdc.trendyol.com/discovery-web-productgw-service/api/productDetail/{product_id}?{query}",
    ]


def _review_api_urls(product_id: str, product_url: str, page: int) -> list[str]:
    """Yorum sayfası için denenecek API URL'lerini döner."""
    page_index = page - 1
    size = 30
    merchant_id = _merchant_id(product_url)

    urls = [
        (
            f"https://apigw.trendyol.com/discovery-storefront-trproductgw-service/"
            f"api/review-read/product-reviews/detailed"
            f"?contentId={product_id}&page={page_index}&pageSize={size}"
            f"&order=DESC&orderBy=Score&channelId=1"
        ),
        (
            f"https://public-mdc.trendyol.com/discovery-storefront-trproductgw-service/"
            f"api/review-read/product-reviews/detailed"
            f"?contentId={product_id}&page={page_index}&pageSize={size}"
            f"&order=DESC&orderBy=Score&channelId=1"
        ),
        (
            f"https://public-mdc.trendyol.com/discovery-web-websfxproductreviews-santral/"
            f"product-reviews-detailed"
            f"?contentId={product_id}&page={page_index}&size={size}"
            f"&culture=tr-TR&storefrontId=1&channelId=1"
        ),
    ]

    if merchant_id:
        urls.insert(0,
            f"https://apigw.trendyol.com/discovery-web-websfxsocialreviewrating-santral/"
            f"product-reviews-detailed"
            f"?sellerId={merchant_id}&contentId={product_id}"
            f"&page={page_index}&pageSize={size}&culture=tr-TR&channelId=1"
        )

    return urls


# ---------------------------------------------------------------------------
# Görsel yardımcıları
# ---------------------------------------------------------------------------


def _normalize_image_url(raw: str, base_url: str) -> str | None:
    """Ham URL'yi temizler, normalize eder. Geçersizse None döner."""
    if not raw:
        return None
    url = html_lib.unescape(str(raw)).strip().split(" ")[0]
    if url.startswith("//"):
        url = f"https:{url}"
    elif url.startswith("/"):
        parsed_base = urlparse(base_url)
        url = f"{parsed_base.scheme}://{parsed_base.netloc}{url}"

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None

    # Trendyol resize parametrelerini kaldır (/mnresize/200/200/)
    clean_path = re.sub(r"/mnresize/\d+/\d+/", "/", parsed.path)
    return urlunparse(("https", parsed.netloc.lower(), clean_path, "", "", ""))


def _is_product_image(url: str) -> bool:
    """URL'nin ürün görseli olup olmadığını kontrol eder."""
    lowered = url.lower()

    # Sadece CDN'den gelenleri kabul et
    if _CDN_HOST not in lowered:
        return False

    # Resim formatı olmalı
    if not re.search(r"\.(jpe?g|png|webp)($|\?)", lowered):
        return False

    # Logo, icon gibi site görselleri hariç
    blocked = ("logo", "sprite", "icon", "badge", "payment", "placeholder")
    if any(b in lowered for b in blocked):
        return False

    # Ürün path'leri
    return any(
        marker in lowered
        for marker in ("/product/media/images/", "/prod/", "_org_zoom.")
    )


def _find_cdn_urls(html_text: str) -> list[str]:
    """Sayfa HTML'inde geçen cdn.dsmcdn.com URL'lerini regex ile bulur."""
    return re.findall(
        rf'https?://{re.escape(_CDN_HOST)}/[^\s"\'<>\\)]+',
        html_lib.unescape(html_text),
        flags=re.IGNORECASE,
    )


def _image_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _image_extension(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    return ".jpg" if suffix in (".jpg", ".jpeg") else suffix if suffix in (".png", ".webp") else ".jpg"


def _replace_path(image: ProductImage, path: str) -> ProductImage:
    return ProductImage(
        url=image.url,
        image_id=image.image_id,
        position=image.position,
        local_path=path,
    )


# ---------------------------------------------------------------------------
# Açıklama yardımcıları
# ---------------------------------------------------------------------------


def _extract_rich_content(page_html: str) -> str | None:
    """id=rich-content-wrapper elementinin metin içeriğini çıkarır."""
    match = re.search(
        r'id=["\']?rich-content-wrapper["\']?',
        page_html,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    # Elementin başlangıcını bul
    start = page_html.rfind("<div", 0, match.start())
    if start == -1:
        return None

    # Derinlik sayacı ile kapanış tag'ini bul
    depth = 0
    i = start
    while i < len(page_html):
        if page_html[i:i+4].lower() == "<div":
            depth += 1
        elif page_html[i:i+5].lower() == "</div":
            depth -= 1
            if depth == 0:
                content = page_html[start : i + 6]
                return clean_text(content) or None
        i += 1

    return None


def _is_real_description(text: str) -> bool:
    """Metnin gerçek bir ürün açıklaması olup olmadığını kontrol eder."""
    if len(text) < 30:
        return False
    # SEO bait metinlerini ele
    seo_markers = (
        "yorumlarını inceleyin",
        "indirimli fiyata satın",
        "trendyol'a özel",
    )
    return not any(m in text.lower() for m in seo_markers)


# ---------------------------------------------------------------------------
# URL yardımcıları
# ---------------------------------------------------------------------------


def _merchant_id(product_url: str) -> str | None:
    query = parse_qs(urlparse(product_url).query)
    values = query.get("merchantId")
    return values[0] if values else None


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return None


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
