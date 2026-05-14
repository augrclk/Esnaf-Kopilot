"""
İçerik analiz servisi — SEO/AEO puanlama ve yeni içerik üretimi.
"""

from __future__ import annotations

from app.analyzer.gemini_client import GeminiClient
from app.analyzer.prompts import build_content_prompt, build_scoring_prompt
from app.models import (
    CategoryScore,
    ContentResult,
    Product,
    Review,
    ScoreResult,
)


class ContentAnalyzer:
    """
    Ürün içeriğini analiz eden ve yeni içerik üreten servis.

    Kullanım:
        analyzer = ContentAnalyzer(GeminiClient())
        score = analyzer.score(product, reviews)
        content = analyzer.generate(product, reviews, score.total_score)
    """

    def __init__(self, client: GeminiClient) -> None:
        self._client = client

    def score(self, product: Product, reviews: list[Review]) -> ScoreResult:
        """
        Ürünü SEO ve AEO kriterlerine göre puanlar.

        Args:
            product: Başlık ve açıklama bilgisi
            reviews: Kullanıcı yorumları

        Returns:
            ScoreResult: Toplam puan ve kategori bazlı kırılım
        """
        system_prompt, user_prompt = build_scoring_prompt(product, reviews)
        raw = self._client.analyze_text(system_prompt, user_prompt)
        return _parse_score_result(raw)

    def generate(
        self,
        product: Product,
        reviews: list[Review],
        current_score: int,
    ) -> ContentResult:
        """
        Optimize edilmiş başlık, açıklama, SSS ve anahtar kelimeler üretir.

        Args:
            product: Mevcut ürün bilgisi
            reviews: Kullanıcı yorumları
            current_score: score() metodundan gelen mevcut puan

        Returns:
            ContentResult: Yeni başlık, açıklama, SSS, anahtar kelimeler
        """
        system_prompt, user_prompt = build_content_prompt(product, reviews, current_score)
        raw = self._client.analyze_text(system_prompt, user_prompt)
        return _parse_content_result(raw)


# ---------------------------------------------------------------------------
# Parse fonksiyonları
# ---------------------------------------------------------------------------


def _parse_score_result(raw: dict) -> ScoreResult:
    """Gemini'nin JSON yanıtını ScoreResult modeline dönüştürür."""
    categories: list[CategoryScore] = []

    for cat in raw.get("categories", []):
        categories.append(CategoryScore(
            name=str(cat.get("name", "")),
            score=int(cat.get("score", 0)),
            max_score=int(cat.get("max_score", 0)),
            notes=list(cat.get("notes", [])),
        ))

    total = raw.get("total_score")
    if total is None:
        total = sum(c.score for c in categories)

    return ScoreResult(
        total_score=int(total),
        max_score=100,
        categories=categories,
        summary=str(raw.get("summary", "")),
    )


def _parse_content_result(raw: dict) -> ContentResult:
    """Gemini'nin JSON yanıtını ContentResult modeline dönüştürür."""
    faq: list[dict[str, str]] = []
    for item in raw.get("faq", []):
        if isinstance(item, dict):
            faq.append({
                "question": str(item.get("question", "")),
                "answer": str(item.get("answer", "")),
            })

    keywords_raw = raw.get("suggested_keywords", {})
    keywords: list[str] = []
    if isinstance(keywords_raw, dict):
        ana = keywords_raw.get("ana", "")
        if ana:
            keywords.append(ana)
        keywords.extend(keywords_raw.get("destekleyici", []))
        keywords.extend(keywords_raw.get("firsat", []))
    elif isinstance(keywords_raw, list):
        keywords = [str(k) for k in keywords_raw]

    return ContentResult(
        new_title=str(raw.get("new_title", "")),
        new_description=str(raw.get("new_description", "")),
        faq=faq,
        suggested_keywords=keywords,
        notes=str(raw.get("notes", "")),
    )
