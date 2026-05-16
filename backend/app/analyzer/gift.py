"""
Hediye Öneri Servisi — Müşteri memnuniyetini artıran düşük maliyetli jest önerileri.

Araştırma temelli:
- Hediye satın alma memnuniyetini artırır (faydalı + kaliteli algılandığında)
- Beklenmeyen küçük hediyeler daha güçlü etki yapar (sürpriz etkisi)
- Koşulsuz jestler minnettarlık → tekrar satın alma → sadakat zinciri kurar
- Satıcının "özeni" müşteride güven ve bağlılık oluşturur

Kural: Hediye maliyeti düşük olmalı — satıcı marjını yememeli.
"""

from __future__ import annotations

import logging

from app.analyzer.gemini_client import GeminiClient
from app.models import Product

log = logging.getLogger(__name__)


_GIFT_SYSTEM_PROMPT = """
Sen deneyimli bir e-ticaret müşteri deneyimi uzmanısın.
Sana bir ürün ve müşteri yorum analizi verilecek.
Görevin: satıcıya DÜŞÜK MALİYETLİ ama YÜKSEK ETKİLİ hediye/jest önerileri sunmak.

TEMEL PRENSİPLER:
1. Hediye ÜRÜNLE ALAKALI olmalı. Rastgele değil, ürünü tamamlayan bir şey.
2. Maliyet çok düşük olmalı: birim başı 1-10₺ arası. Max 15₺.
3. Hediyenin SOMUT faydası olmalı. "Güzel görünsün" değil, "müşterinin işine yarasın".
4. Yorum verisi varsa, müşterilerin yaşadığı sorunları ÇÖZEN hediye öner.
5. Sürpriz etkisi önemli — açıklamada "hediye var" yazmamak daha etkili olabilir.
6. Basit ama özenli: teşekkür kartı, kullanım kılavuzu, küçük aksesuar.
7. Toplu tedarik maliyetini düşün: 100 adet sipariş edilirse birim fiyat düşer.

YASAKLAR:
- Ürünün kendisiyle rekabet eden hediye önerme (ör: krem yanında başka marka krem)
- Satıcının tedarik edemeyeceği, karmaşık hediye önerme
- Maliyet tahmini yaparken abartı yapma, gerçekçi ol
- "İndirim kuponu" veya "ücretsiz kargo" gibi fiyat bazlı jestler önerme
  (bunlar hediye değil, promosyon)

STRATEJİ TİPLERİ:
A) SORUN ÇÖZÜCÜ HEDİYE: Müşteri yorumlarında tekrar eden bir sorunu hafifletir.
   Ör: "Beden dar" şikayeti → beden tablosu kartı + değişim süreci bilgilendirmesi
B) KULLANIM KOLAYLAŞTIRICI: Ürünün doğru/verimli kullanımını sağlar.
   Ör: Cilt kremi → küçük spatula + uygulama rehberi kartı
C) TAMAMLAYICI AKSESUAR: Ürünle birlikte kullanılan küçük parça.
   Ör: Ayakkabı → temizlik mendili, yedek bağcık
D) KİŞİSEL DOKUNUŞ: Müşteride "özel hissettiren" jest.
   Ör: El yazısı teşekkür kartı, ürüne özel kullanım ipuçları kartı
E) KORUYUCU/SAKLAMA: Ürünün ömrünü uzatan hediye.
   Ör: Takı → kadife kese, gözlük → temizleme bezi

ÇIKTI FORMATI — sadece JSON:
{
  "category_detected": "<tespit edilen ürün kategorisi>",
  "gift_strategy": "<hangi strateji tipi/tipleri bu ürüne uygun ve neden — 1-2 cümle>",
  "suggestions": [
    {
      "gift": "<hediye adı>",
      "type": "<A|B|C|D|E>",
      "why": "<neden bu hediye — yorum verisine dayanan somut gerekçe>",
      "estimated_cost": "<birim maliyet tahmini, ör: 2-4₺>",
      "bulk_note": "<toplu alımda maliyet notu, ör: 100 adet alınırsa ~1.5₺/adet>",
      "review_trigger": "<bu öneriyi tetikleyen yorum bulgusu, yoksa 'genel kategori önerisi'>",
      "impact": "<LOW|MEDIUM|HIGH — müşteri memnuniyetine beklenen etki>"
    }
  ],
  "packaging_tips": [
    "<paketleme ile ilgili düşük maliyetli öneri — ör: kraft kağıdı, sticker, bant rengi>"
  ],
  "disclosure_strategy": "<sürpriz mi yap, açıklamada yaz mı? Hangisi bu ürün için daha etkili ve neden>"
}

KURALLAR:
- 3-5 hediye önerisi ver
- En az 1 tanesi "sorun çözücü" (A tipi) olmalı — yorum verisi varsa
- Toplam maliyet tahmini gerçekçi olmalı (Türkiye pazarı fiyatları)
- Paketleme önerileri de düşük maliyetli olmalı (satıcılar genelde küçük işletme)
- Her önerinin somut, uygulanabilir olması şart
"""


class GiftAdvisor:
    """
    Ürüne özel düşük maliyetli hediye ve jest önerileri üreten servis.

    Kullanım:
        advisor = GiftAdvisor(GeminiClient())
        suggestions = advisor.suggest(product, review_analysis)
    """

    def __init__(self, client: GeminiClient) -> None:
        self._client = client

    def suggest(
        self,
        product: Product,
        review_analysis: dict | None = None,
    ) -> dict:
        """
        Ürün ve yorum analizine dayanarak hediye önerileri üretir.

        Args:
            product: Ürün bilgisi
            review_analysis: ReviewAnalyzer çıktısı (opsiyonel)

        Returns:
            Hediye önerileri dict — suggestions, packaging_tips, disclosure_strategy
        """
        user_prompt = self._build_prompt(product, review_analysis)
        raw = self._client.analyze_text(_GIFT_SYSTEM_PROMPT.strip(), user_prompt)
        return raw

    def _build_prompt(self, product: Product, ra: dict | None) -> str:
        lines = [
            f"ÜRÜN: {product.title}",
            f"AÇIKLAMA: {(product.description or '')[:500]}",
        ]

        if ra and ra.get("total_reviews", 0) > 0:
            lines.append(f"\nORTALAMA PUAN: {ra.get('avg_rating', 0):.1f}/5 ({ra.get('total_reviews', 0)} yorum)")
            lines.append(f"GÜVEN SEVİYESİ: {ra.get('confidence', 'LOW')}")

            negatives = ra.get("negatives", [])
            if negatives:
                lines.append("\nMÜŞTERİ ŞİKAYETLERİ:")
                for n in negatives[:5]:
                    sev = n.get("severity", "")
                    lines.append(f"  - [{sev}] {n.get('title', '')}: {n.get('detail', '')}")

            positives = ra.get("positives", [])
            if positives:
                lines.append("\nBEĞENİLEN NOKTALAR:")
                for p in positives[:5]:
                    lines.append(f"  - {p.get('title', '')}: {p.get('detail', '')}")

            questions = ra.get("unanswered_questions", [])
            if questions:
                lines.append("\nCEVAPLANMAMIŞ SORULAR:")
                for q in questions[:5]:
                    lines.append(f"  - {q}")

            drivers = ra.get("purchase_drivers", [])
            if drivers:
                lines.append(f"\nSATIN ALMA FAKTÖRLERİ: {', '.join(drivers[:5])}")

            content_sugg = ra.get("content_suggestions", [])
            if content_sugg:
                lines.append("\nİÇERİK ÖNERİLERİ:")
                for s in content_sugg[:3]:
                    lines.append(f"  - {s}")
        else:
            lines.append("\n(Yorum verisi yok — genel kategori bilgisine göre öner)")

        lines.append("\nJSON formatında yanıt ver.")
        return "\n".join(lines)
