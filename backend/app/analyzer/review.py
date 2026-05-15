"""
Yorum Analiz Servisi — Müşteri geri bildirimlerinden içgörü çıkarma.

Görev: Çekilen yorumları analiz ederek beğenilen noktaları,
sorunlu noktaları ve belirsiz kalan soruları tespit et.
"""

from __future__ import annotations

from app.analyzer.gemini_client import GeminiClient
from app.models import Product, Review


_REVIEW_ANALYSIS_SYSTEM = """
Sen bir müşteri deneyimi analistisin. Sana bir e-ticaret ürününün kullanıcı yorumları verilecek.
Bu yorumları analiz ederek satıcıya pratik ve dürüst içgörüler sun.

KURALI ASLA ÇIĞNEME:
- Sadece yorumlarda gerçekten yazana dayan. Uydurma.
- "Genel olarak iyi" gibi belirsiz ifade kullanma. Somut al.
- Yorumlarda hiç bahsedilmemişse o konuya giriş yapma.

ÇIKTI FORMATI — sadece JSON ver:
{
  "avg_rating": <float, yorumların ortalama puanı>,
  "total_reviews": <int, analiz edilen yorum sayısı>,
  "positives": [
    {"title": "<kısa başlık>", "detail": "<müşterilerin tam olarak ne söylediği, varsa örnek alıntı>"}
  ],
  "negatives": [
    {"title": "<kısa başlık>", "detail": "<müşterilerin tam olarak ne söylediği, varsa örnek alıntı>"}
  ],
  "unanswered_questions": [
    "<yorumlarda belirsiz kalan veya tekrar eden ama cevaplanmamış müşteri sorusu>"
  ],
  "sentiment_summary": "<2-3 cümle: genel müşteri duygu durumu ve en kritik mesaj>"
}
"""


class ReviewAnalyzer:
    """
    Ürün yorumlarını analiz edip müşteri içgörüsü sunan servis.
    """

    def __init__(self, client: GeminiClient) -> None:
        self._client = client

    def analyze(self, product: Product, reviews: list[Review]) -> dict:
        """
        Yorumları analiz eder. Dict döner (JSON schema yukarıda).

        Args:
            product: Ürün bilgisi (context için kullanılır)
            reviews: Tüm müşteri yorumları

        Returns:
            Yorum analizi dict — positives, negatives, unanswered_questions, summary
        """
        if not reviews:
            return {
                "avg_rating": 0.0,
                "total_reviews": 0,
                "positives": [],
                "negatives": [],
                "unanswered_questions": [],
                "sentiment_summary": "Analiz edilecek yorum bulunamadı."
            }

        user_prompt = self._build_prompt(product, reviews)
        raw = self._client.analyze_text(_REVIEW_ANALYSIS_SYSTEM.strip(), user_prompt)
        return raw

    def _build_prompt(self, product: Product, reviews: list[Review]) -> str:
        ratings = [r.rating for r in reviews if r.rating is not None]
        avg = sum(ratings) / len(ratings) if ratings else 0.0

        # En fazla 60 yorumu sample al (API token limiti)
        sample = reviews[:60]
        lines = []
        for i, r in enumerate(sample, 1):
            rating_str = f"{r.rating}/5" if r.rating else "?"
            lines.append(f"{i}. [{rating_str}] {r.text}")

        reviews_text = "\n".join(lines)

        return f"""
Ürün: {product.title}
Ortalama Puan: {avg:.1f}/5 ({len(reviews)} yorum)

KULLANICI YORUMLARI:
{reviews_text}

Yorumları analiz et ve JSON formatında yanıt ver.
""".strip()
