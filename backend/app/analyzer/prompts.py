"""
Gemini prompt şablonları.

Her fonksiyon belirli bir görev için system + user prompt çifti döner.
Prompt içerikleri Skor-kriter.txt ve Cıktı-Formati.txt dosyalarına dayanır.
"""

from __future__ import annotations

from app.models import Product, Review, ScrapedProduct

# ---------------------------------------------------------------------------
# SEO / AEO Puanlama Promptu
# ---------------------------------------------------------------------------

import os
from pathlib import Path

# Proje ana dizinine (Esnaf-Kopilot) ulaşmak için path ayarı
# backend/app/analyzer/prompts.py -> backend -> Esnaf-Kopilot
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

_SCORING_JSON_INSTRUCTION = """

----------------------------------------------------
ÇOK ÖNEMLİ: ÇIKTI FORMATI
Yukarıdaki kurallara göre analizi yap, ancak frontend uygulamasının çalışabilmesi için 
çıkıntıyı SADECE AŞAĞIDAKİ JSON FORMATINDA (başka hiçbir metin olmadan) ver:
{
  "total_score": <0-100 arası tam sayı>,
  "categories": [
    {
      "name": "<kriter adı, örn: A1.1 Ana Ürün Terimi>",
      "score": <verilen puan>,
      "max_score": <maksimum puan>,
      "notes": ["<sağlandı/sağlanmadı ve kanıt>"]
    }
  ],
  "summary": "<puan kırılan kriterlerin kısa özeti>"
}
"""

_CONTENT_JSON_INSTRUCTION = """

----------------------------------------------------
ÇOK ÖNEMLİ: ÇIKTI FORMATI
Yukarıdaki kurallara göre yeni içerikleri üret, ancak frontend uygulamasının çalışabilmesi için 
çıkıntıyı SADECE AŞAĞIDAKİ JSON FORMATINDA (başka hiçbir metin olmadan) ver:
{
  "new_title": "<yeni başlık>",
  "new_description": "<yeni açıklama>",
  "faq": [
    {"question": "<soru>", "answer": "<cevap>"}
  ],
  "suggested_keywords": {
    "ana": "<en güçlü ana keyword>",
    "destekleyici": ["<long tail keyword>", "<soru fırsatı>"],
    "firsat": ["<fırsat keyword>"]
  },
  "notes": "<yapılan iyileştirmelerin kısa özeti>"
}
"""

def _read_file_safe(filename: str) -> str:
    path = BASE_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"({filename} bulunamadı, varsayılan SEO/AEO kurallarını uygula)"

def build_scoring_prompt(product: Product, reviews: list[Review]) -> tuple[str, str]:
    scoring_rules = _read_file_safe("Skor-kriter.txt")
    system_prompt = f"Sen bir e-ticaret uzmanısın.\n\n{scoring_rules}\n{_SCORING_JSON_INSTRUCTION}"
    
    review_sample = _format_reviews(reviews, max_count=30)
    user_prompt = f"""
Aşağıdaki Trendyol ürününü puanla:

MEVCUT BAŞLIK:
{product.title}

MEVCUT AÇIKLAMA:
{product.description or "(Açıklama bulunamadı)"}

KULLANICI YORUMLARI ({len(reviews)} yorumdan ilk 30 tanesi):
{review_sample}

Sadece JSON formatında yanıt ver.
"""
    return system_prompt.strip(), user_prompt.strip()

def build_content_prompt(
    product: Product,
    reviews: list[Review],
    current_score: int,
) -> tuple[str, str]:
    content_rules = _read_file_safe("Cıktı-Formati.txt")
    system_prompt = f"Sen bir e-ticaret içerik uzmanısın.\n\n{content_rules}\n{_CONTENT_JSON_INSTRUCTION}"

    review_sample = _format_reviews(reviews, max_count=40)
    review_insights = _extract_review_insights(reviews)

    user_prompt = f"""
Aşağıdaki ürün için optimize edilmiş içerik üret:

MEVCUT BAŞLIK:
{product.title}

MEVCUT AÇIKLAMA:
{product.description or "(Açıklama bulunamadı)"}

MEVCUT PUAN: {current_score}/100

YORUM İÇGÖRÜLERİ:
{review_insights}

KULLANICI YORUMLARI ({len(reviews)} yorumdan seçilmiş {min(40, len(reviews))} tanesi):
{review_sample}

Sadece JSON formatında yanıt ver.
"""
    return system_prompt.strip(), user_prompt.strip()


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------


def _format_reviews(reviews: list[Review], max_count: int) -> str:
    """Yorumları prompt için okunabilir formata dönüştürür."""
    if not reviews:
        return "(Yorum bulunamadı)"

    lines: list[str] = []
    for i, r in enumerate(reviews[:max_count], 1):
        rating = f"{r.rating}/5" if r.rating else "?"
        lines.append(f"{i}. [{rating}] {r.text}")

    return "\n".join(lines)


def _extract_review_insights(reviews: list[Review]) -> str:
    """Yorumlardan pozitif/negatif örüntüleri özetler."""
    if not reviews:
        return "(Yorum yok)"

    ratings = [r.rating for r in reviews if r.rating is not None]
    avg = sum(ratings) / len(ratings) if ratings else 0

    positive = [r.text for r in reviews if (r.rating or 0) >= 4][:10]
    negative = [r.text for r in reviews if (r.rating or 0) <= 2][:5]

    lines = [f"Ortalama puan: {avg:.1f}/5 ({len(reviews)} yorum)"]

    if positive:
        lines.append("\nSık tekrar eden OLUMLU noktalar (ham yorumlar):")
        for p in positive:
            lines.append(f"  - {p[:120]}")

    if negative:
        lines.append("\nSık tekrar eden OLUMSUZ noktalar (ham yorumlar):")
        for n in negative:
            lines.append(f"  - {n[:120]}")

    return "\n".join(lines)
