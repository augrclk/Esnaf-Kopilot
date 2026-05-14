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

_SCORING_SYSTEM = """
Sen bir e-ticaret ürün listeleme uzmanısın. Trendyol gibi Türk pazaryerlerinde
SEO ve AEO (AI Motoru Optimizasyonu) konusunda derinlemesine bilgi sahibisin.

Sana bir ürünün mevcut başlığını, açıklamasını ve kullanıcı yorumlarını vereceğim.
Aşağıdaki kriterlere göre ürünü puanla ve sonuçları JSON formatında ver.

PUANLAMA KRİTERLERİ:

SEO / Pazaryeri Arama Uyumu — 50 puan toplam:

1. Başlık Kalitesi — 12 puan
   - Ana ürün terimi başlıkta açık ve başa yakın mı?
   - Marka, model, materyal, ölçü gibi ayırt edici bilgi var mı?
   - Başlık okunabilir mi? Keyword stuffing veya yanıltıcı ifade var mı?

2. Açıklama Kalitesi — 12 puan
   - Açıklama ürünü net anlatıyor mu, ilk cümleler yeterli mi?
   - 150-200 kelime düzeyinde yeterli detay var mı?
   - Fayda odaklı, doğal, okunabilir anlatım var mı?

3. Anahtar Kelime ve Arama Niyeti Uyumu — 10 puan
   - Ana anahtar kelime doğal kullanılmış mı?
   - Long-tail arama ifadeleri var mı?
   - Kullanıcının arama niyetine cevap veriyor mu?

4. Ürün Özellikleri / Attribute Tamlığı — 10 puan
   - Materyal, renk, ölçü, kapasite, kullanım alanı belirtilmiş mi?
   - Teknik özellikler net yazılmış mı?

5. Kategori, Marka ve Varyant Tutarlılığı — 6 puan
   - Ürün adı, marka ve kategori tutarlı mı?
   - Başlık ve açıklama aynı ürünü anlatıyor mu?

AEO / AI Okunabilirlik — 50 puan toplam:

6. Cevap-Öncelikli Ürün Tanımı — 10 puan
   - İlk 1-2 cümle ürünü net tanımlıyor mu?
   - AI sistemlerinin doğrudan cevap olarak çekebileceği cümleler var mı?

7. Yapılandırılmış Bilgi Düzeni — 10 puan
   - Bilgiler düzenli, taranabilir, madde madde mi?
   - Teknik bilgiler ve faydalar ayrılmış mı?

8. SSS / Soru-Cevap Uygunluğu — 8 puan
   - Gerçek kullanıcı sorularına cevap var mı?
   - Yorumlarda tekrar eden sorunlar karşılanmış mı?

9. Yorumlardan Gelen İçgörülerin Kullanımı — 10 puan
   - Yorumlardaki olumlu/olumsuz noktalar tespit edilmiş mi?
   - Tekil yorumlardan kesin genelleme yapılmış mı?

10. Varlık Tutarlılığı — 7 puan
    - Ürün adı, marka, kategori terimleri tutarlı mı?

11. Doğrulanabilirlik ve Uydurma Riskinin Düşüklüğü — 5 puan
    - Metindeki iddialar verilen bilgilerle destekleniyor mu?
    - Verilmeyen bilgiler iddia edilmiş mi?

ÇIKTI FORMATI (kesinlikle bu JSON yapısını kullan):
{
  "total_score": <0-100 arası tam sayı>,
  "categories": [
    {
      "name": "<kriter adı>",
      "score": <verilen puan>,
      "max_score": <maksimum puan>,
      "notes": ["<kısa gözlem>", ...]
    }
  ],
  "summary": "<genel değerlendirme, 2-3 cümle>"
}
"""


def build_scoring_prompt(product: Product, reviews: list[Review]) -> tuple[str, str]:
    """
    SEO/AEO puanlama için system ve user prompt döner.

    Returns:
        (system_prompt, user_prompt) çifti
    """
    review_sample = _format_reviews(reviews, max_count=30)

    user_prompt = f"""
Aşağıdaki Trendyol ürününü puanla:

MEVCUT BAŞLIK:
{product.title}

MEVCUT AÇIKLAMA:
{product.description or "(Açıklama bulunamadı)"}

KULLANICI YORUMLARI ({len(reviews)} yorumdan ilk 30 tanesi):
{review_sample}

Puanlama kriterlerine göre değerlendir ve JSON formatında yanıt ver.
"""
    return _SCORING_SYSTEM.strip(), user_prompt.strip()


# ---------------------------------------------------------------------------
# İçerik Üretim Promptu
# ---------------------------------------------------------------------------

_CONTENT_SYSTEM = """
Sen bir e-ticaret içerik uzmanısın. Trendyol gibi Türk pazaryerlerinde
SEO ve AEO odaklı ürün başlığı ve açıklaması yazıyorsun.

Sana ürün bilgisi, mevcut puan raporu ve kullanıcı yorumları verilecek.
Bu bilgilere dayanarak optimize edilmiş başlık, açıklama, SSS ve anahtar kelimeler üret.

KURALI ASLA ÇIĞNEME:
- Yalnızca verilen bilgilere dayan. Verilmeyen özellik, sertifika, garanti uydurmak yasak.
- Ürün gerçekte ne ise onu yaz. Abartılı, yanıltıcı ifade kullanma.
- Açıklama Türkçe olmalı, doğal ve okunabilir olmalı.

YENİ BAŞLIK KURALLARI:
- Orijinal başlıktaki marka etiketini (örn. Trendyol'un otomatik eklediği en baştaki marka adı) TAMAMEN YOK SAY.
- Yeni başlık doğrudan Ana Ürün Terimi (Örn: "Hindistan Cevizi Yağı") ile başlamalı.
- Marka adını başlığın en başına değil, başlığın içine doğal bir şekilde veya en sona ekle.
- Ürün tipi + ayırt edici özellik + ölçü/miktar (varsa) içermeli.
- 70-100 karakter arası olmalı.
- Keyword stuffing yok.

YENİ AÇIKLAMA KURALLARI:
- İlk 2 cümle: Ürünü net tanımla (AI'ın doğrudan çekebileceği format)
- Sonra madde madde özellikler (• işareti ile)
- Kullanım senaryoları
- Kapanış: Hedef kitleye yönelik, harekete geçirici
- 150-200 kelime

SSS KURALLARI:
- Yorumlardan gerçek soruları çıkar
- 5 soru-cevap
- Her cevap direkt ve kısa

ÇIKTI FORMATI (kesinlikle bu JSON yapısını kullan):
{
  "new_title": "<yeni başlık>",
  "new_description": "<yeni açıklama>",
  "faq": [
    {"question": "<soru>", "answer": "<cevap>"}
  ],
  "suggested_keywords": {
    "ana": "<en güçlü long-tail keyword>",
    "destekleyici": ["<keyword 2>", "<keyword 3>"],
    "firsat": ["<az kullanılan fırsat keyword>", "<keyword 5>"]
  },
  "notes": "<içerik yazarının kısa notu — neden bu başlık/açıklama>"
}
"""


def build_content_prompt(
    product: Product,
    reviews: list[Review],
    current_score: int,
) -> tuple[str, str]:
    """
    Yeni başlık ve açıklama üretimi için system ve user prompt döner.

    Returns:
        (system_prompt, user_prompt) çifti
    """
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

Yeni başlık, açıklama, SSS ve anahtar kelimeler üret. JSON formatında yanıt ver.
"""
    return _CONTENT_SYSTEM.strip(), user_prompt.strip()


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
