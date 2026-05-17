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
1. Hediye ÜRÜNLE DOĞRUDAN ALAKALI olmalı. "Bu ürünü alan kişi ne işe yarar?" sorusunu sor.
2. Tamamlayıcı aksesuar önceliklidir — müşteri zaten o ürünü aldıysa yanında ne olsa işe yarar?
3. Hediyenin SOMUT faydası olmalı: müşterinin işini kolaylaştırmalı, ürünün ömrünü uzatmalı, veya sorunu çözmeli.
4. Yorum verisi varsa, tekrar eden sorunları ÇÖZEN hediye öner.
5. Sürpriz etkisi önemli — beklenmeyen küçük dokunuşlar güçlü bağ kurar.
6. Satıcının kolayca tedarik edebileceği ürünler öner.

YASAKLAR:
- Ürünle rekabet eden hediye önerme (ör: çanta yanına başka marka çanta)
- Ürünle alakasız genel hediyeler (ör: her ürüne "teşekkür kartı" önermek tek başına yetmez)
- FİYAT YAZMA. Fiyat tahmini yapma, araştırmadan fiyat verme. estimated_cost alanını boş bırak veya "—" yaz.
- "İndirim kuponu" veya "ücretsiz kargo" gibi fiyat bazlı jestler önerme.

KATEGORİ BAZLI TAMAMLAYICI AKSESUAR ÖRNEKLERİ (ilham al, bunlarla sınırlı kalma):
Gözlük → lens temizleme spreyi, mikrofiber bez, gözlük kutusu, gözlük bezi
Ayakkabı → ayakkabı temizleme mendili, yedek bağcık, koku giderici kese, ayakkabı torbası
Çanta → çanta içi organizer, deri bakım bezi, toz torbası, metal ayak koruyucu pedleri
Takı → kadife kese, takı temizleme bezi, küçük mücevher kutusu
Cilt kremi/kozmetik → mini spatula, uygulama rehberi kartı, küçük temizleme bezi
Saç ürünü → saç maskesi numunesi, uygulama tarağı, saç bandı
Mutfak aleti → tarif kartı, temizlik bezi, kullanım kılavuzu kitapçığı
Kahve makinesi → küçük temizleme fırçası, ölçüm kaşığı, kahve numunesi
Spor ekipmanı → deri bakım bezi, küçük bez çanta, temizlik mendili
Elektronik → ekran temizleme bezi, koruyucu kese, küçük temizleme fırçası
Bebek ürünü → organik temizlik mendili, ürün kullanım kartı, küçük hediye paketi

STRATEJİ TİPLERİ (öncelik sırasıyla):
C) TAMAMLAYICI AKSESUAR (ÖNCELİKLİ): Ürünle birlikte kullanılan, işe yarayan küçük parça. En az 2 öneri bu tipten olmalı.
B) KULLANIM KOLAYLAŞTIRICI: Ürünün doğru/verimli kullanımını sağlar.
A) SORUN ÇÖZÜCÜ: Yorumlarda tekrar eden sorunu hafifletir — yorum verisi varsa mutlaka ekle.
D) KİŞİSEL DOKUNUŞ: Müşteride "özel hissettiren" jest. Tek başına önerilmez, diğerleriyle desteklenir.
E) KORUYUCU/SAKLAMA: Ürünün ömrünü uzatan hediye (kese, kutu, koruyucu bez).

ÇIKTI FORMATI — sadece JSON:
{
  "category_detected": "<tespit edilen ürün kategorisi>",
  "gift_strategy": "<tamamlayıcı strateji gerekçesi — bu ürünü alan müşteri ne işe yarar? — 1-2 cümle>",
  "suggestions": [
    {
      "gift": "<hediye adı>",
      "type": "<A|B|C|D|E>",
      "why": "<neden bu hediye — ürünle bağlantısı ve somut faydası>",
      "estimated_cost": "—",
      "review_trigger": "<bu öneriyi tetikleyen yorum bulgusu, yoksa 'kategori tamamlayıcı'>",
      "impact": "<LOW|MEDIUM|HIGH — müşteri memnuniyetine beklenen etki>"
    }
  ],
  "packaging_tips": [
    "<paketleme ile ilgili düşük maliyetli öneri>"
  ],
  "disclosure_strategy": "<sürpriz mi yap, açıklamada yaz mı? Hangisi bu ürün için daha etkili ve neden>"
}

KURALLAR:
- 3-5 hediye önerisi ver
- En az 2 tanesi C tipi (tamamlayıcı aksesuar) olmalı
- Yorum verisi varsa en az 1 tanesi A tipi (sorun çözücü) olmalı
- estimated_cost alanı her zaman "—" olarak bırak
- Paketleme önerileri düşük maliyetli ve uygulanabilir olmalı
- Her öneri bu ürüne özel olmalı — genel kategori klişeleriyle yetinme
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
