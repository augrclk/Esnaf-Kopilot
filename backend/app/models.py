"""
Uygulama genelinde kullanılan veri modelleri.

Üç katman vardır:
  1. Scraper çıktıları  — Trendyol'dan ham veri
  2. Analiz sonuçları  — Gemini API çıktıları
  3. Hata tipleri      — Özel exception sınıfları
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# 1. Scraper Çıktıları
# ---------------------------------------------------------------------------


@dataclass
class Product:
    """Ürün başlık ve açıklama bilgisi."""

    url: str
    product_id: str | None
    title: str
    description: str


@dataclass
class Review:
    """Tek bir kullanıcı yorumu."""

    review_id: str | None
    rating: float | None
    title: str | None
    text: str
    date: str | None
    user: str | None
    variant: str | None
    helpful_count: int | None


@dataclass
class ProductImage:
    """Ürüne ait tek bir görsel."""

    url: str
    image_id: str
    position: int
    local_path: str | None = None  # İndirildikten sonra dolar


@dataclass
class ScrapedProduct:
    """Trendyol'dan çekilen ham verinin tamamı."""

    product: Product
    reviews: list[Review]
    images: list[ProductImage]


# ---------------------------------------------------------------------------
# 2. Analiz Sonuçları
# ---------------------------------------------------------------------------


@dataclass
class CategoryScore:
    """Tek bir puanlama kategorisinin sonucu."""

    name: str
    score: int
    max_score: int
    notes: list[str] = field(default_factory=list)


@dataclass
class ScoreResult:
    """SEO + AEO puan raporu."""

    total_score: int
    max_score: int = 100
    categories: list[CategoryScore] = field(default_factory=list)
    summary: str = ""


@dataclass
class ContentResult:
    """Gemini tarafından üretilmiş başlık ve açıklama."""

    new_title: str
    new_description: str
    suggested_keywords: list[str] = field(default_factory=list)
    faq: list[dict[str, str]] = field(default_factory=list)
    notes: str = ""


@dataclass
class ImageEditPrompt:
    """Tek bir görsel için üretilmiş düzenleme promptu."""

    concept_name: str   # örn: "Profesyonel Beyaz Fon"
    prompt: str


@dataclass
class ImageEditTask:
    """Yapay zekanın kendi belirlediği kaynak görsel üzerinden oluşturacağı görev."""

    source_image: ProductImage
    concept_name: str
    prompt: str


@dataclass
class ImageAnalysis:
    """Tek bir görselin analiz sonucu ve düzenleme promptları."""

    image: ProductImage
    image_type: str          # "ANA_GORSEL" | "DIGER_GORSEL"
    score: int
    max_score: int
    issues: dict             # Tespit edilen sorunlar (aydınlatma, netlik vb.)
    has_text: bool
    edit_prompts: list[ImageEditPrompt] = field(default_factory=list)
    edit_tasks: list[ImageEditTask] = field(default_factory=list)


@dataclass
class GeneratedImage:
    """Gemini Image API ile üretilmiş iyileştirilmiş görsel."""

    original_image: ProductImage
    concept_name: str
    local_path: str


@dataclass
class AnalysisResult:
    """Pipeline'ın tam çıktısı."""

    scraped: ScrapedProduct
    score: ScoreResult
    content: ContentResult
    image_analyses: list[ImageAnalysis] = field(default_factory=list)
    generated_images: list[GeneratedImage] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 3. Hata Tipleri
# ---------------------------------------------------------------------------


class EsnafKopilotError(Exception):
    """Tüm uygulama hatalarının ana sınıfı."""


class UnsupportedPlatformError(EsnafKopilotError):
    """Desteklenmeyen platform URL'si girildiğinde."""


class ProductNotFoundError(EsnafKopilotError):
    """Ürün sayfası ayrıştırılamadığında."""


class ScraperHttpError(EsnafKopilotError):
    """HTTP isteği başarısız olduğunda."""


class GeminiError(EsnafKopilotError):
    """Gemini API çağrısı başarısız olduğunda."""
