"""
Test Commerce — geliştirici testleri için sahte e-ticaret mağazası.

Gerçek bir pazaryeri API'si gibi davranır:
  GET  /api/test-commerce/products
  GET  /api/test-commerce/products/{id}
  PUT  /api/test-commerce/products/{id}   ← iyileştirme deploy edilince buraya gelir

İn-memory state: sunucu yeniden başlayınca sıfırlanır.
"""
from __future__ import annotations
import copy

_CATALOG: list[dict] = [
    {
        "id": "tc-001",
        "title": "Ergonomik Ofis Koltuğu Bel Destekli 360° Döner Bilgisayar Sandalyesi",
        "description": "Uzun çalışma saatlerinde sırt ve bel sağlığınızı koruyan ergonomik ofis koltuğu. Yükseklik ayarlı kolçaklar ve lümber desteği ile tam konfor sağlar. %100 nefes alabilen mesh kumaş yapısı sırt terlemesini önler.",
        "price": 2499.90,
        "category": "Mobilya > Sandalye > Ofis Sandalyesi",
        "brand": "ErgoPro",
        "rating": 4.2,
        "review_count": 328,
        "images": [
            "https://picsum.photos/seed/ergochr1/800/800",
            "https://picsum.photos/seed/ergochr2/800/800",
        ],
        "reviews": [
            {"rating": 5, "text": "Çok rahat, bel ağrılarım geçti. Kesinlikle tavsiye ederim."},
            {"rating": 4, "text": "Montajı biraz uğraştırdı ama ürün kaliteli. Mesh kumaş gerçekten nefes aldırıyor."},
            {"rating": 3, "text": "Kolçaklar biraz sert, ama genel olarak memnunum."},
            {"rating": 5, "text": "Ofiste saatler geçiyor, bel ağrısı hiç olmadı."},
            {"rating": 2, "text": "Beklediğimden daha küçük geldi, büyük beden için uygun değil."},
            {"rating": 4, "text": "Fiyat performans açısından iyi bir tercih."},
        ],
    },
    {
        "id": "tc-002",
        "title": "Akıllı Spor Bilekliği Adım Sayar Kalp Ritmi Uyku Takibi IP67",
        "description": "Günlük aktivitelerinizi takip eden akıllı spor bilekliği. Adım sayar, kalp atış hızı monitörü, uyku analizi ve spor modları ile sağlıklı yaşam yolculuğunuzda yanınızda. 10 gün pil ömrü.",
        "price": 899.00,
        "category": "Elektronik > Giyilebilir Teknoloji > Akıllı Bileklik",
        "brand": "FitBand",
        "rating": 4.5,
        "review_count": 1247,
        "images": [
            "https://picsum.photos/seed/fitband1/800/800",
            "https://picsum.photos/seed/fitband2/800/800",
        ],
        "reviews": [
            {"rating": 5, "text": "Batarya ömrü mükemmel, 10 gün gidiyor. Ekran net görünüyor."},
            {"rating": 5, "text": "Kalp ritmi ölçümü çok doğru, doktor ölçümüyle karşılaştırdım neredeyse aynı."},
            {"rating": 4, "text": "Uygulama Türkçe değil ama adapte olmak kolay."},
            {"rating": 3, "text": "GPS özelliği yok, bu konuda biraz hayal kırıklığı yaşadım."},
            {"rating": 5, "text": "Spor yaparken bile hiç rahatsız etmiyor, hafif ve şık."},
            {"rating": 4, "text": "Su geçirmezlik testi yaptım, sorun yok."},
        ],
    },
    {
        "id": "tc-003",
        "title": "Kablosuz Bluetooth Kulaklık 40 Saat Pil Aktif Gürültü Engelleme",
        "description": "Kristal netliğinde ses kalitesi sunan over-ear Bluetooth kulaklık. Aktif gürültü engelleme teknolojisi ile konsantrasyonunuzu artırın. 40 saate kadar kesintisiz müzik dinleyin. Hızlı şarj: 10 dakikada 3 saat.",
        "price": 1299.00,
        "category": "Elektronik > Ses Sistemleri > Kulaklık",
        "brand": "SoundMax",
        "rating": 4.3,
        "review_count": 856,
        "images": [
            "https://picsum.photos/seed/headph1/800/800",
            "https://picsum.photos/seed/headph2/800/800",
        ],
        "reviews": [
            {"rating": 5, "text": "Ses kalitesi inanılmaz, bas sesi çok dolu."},
            {"rating": 4, "text": "Gürültü engelleme gerçekten işe yarıyor, metroda bile rahat dinliyorum."},
            {"rating": 3, "text": "Uzun kullanımda kulak sıkıştırıyor, 2 saatten fazla takmak rahatsız edici."},
            {"rating": 5, "text": "Pil ömrü reklamdan bile iyi çıktı, çok memnunum."},
            {"rating": 4, "text": "Kılıfı şık ve dayanıklı görünüyor."},
        ],
    },
    {
        "id": "tc-004",
        "title": "El Yapımı Seramik Kahve Fincanı Seti 6'lı Türk Kahvesi Takımı",
        "description": "Geleneksel Türk motiflerinden ilham alan el yapımı seramik kahve fincanı seti. Kurşun ve kadmiyum içermez. Bulaşık makinesinde yıkanabilir. Özel hediye kutusunda sunulur.",
        "price": 349.90,
        "category": "Ev & Yaşam > Mutfak > Kahve & Çay Ekipmanları",
        "brand": "ÇiniCraft",
        "rating": 4.7,
        "review_count": 2341,
        "images": [
            "https://picsum.photos/seed/ceramic1/800/800",
            "https://picsum.photos/seed/ceramic2/800/800",
        ],
        "reviews": [
            {"rating": 5, "text": "Düğün hediyesi olarak aldım, herkes çok beğendi. Kutu gerçekten özel."},
            {"rating": 5, "text": "Motifler çok güzel, fotoğrafta daha iyi görünüyor bile."},
            {"rating": 4, "text": "Bir tanesi hafif çatlak geldi ama müşteri hizmetleri hemen yenisini gönderdi."},
            {"rating": 5, "text": "Bulaşık makinesinde hiç solmadı, 3 aydır kullanıyorum."},
            {"rating": 5, "text": "Anne günü hediyesi olarak aldım, çok sevindi."},
            {"rating": 4, "text": "Ağırlık iyi, sağlam hissettiriyor."},
        ],
    },
    {
        "id": "tc-005",
        "title": "Organik Zeytinyağlı Doğal El Sabunu Seti 5'li Hediye Paketi",
        "description": "Ege zeytinlerinden elde edilen saf zeytinyağı ile üretilen %100 doğal el sabunu. Parabensiz, SLS içermez. Hassas ciltler için uygundur. Lavanta, gül, nane, çay ağacı ve bal kokuları.",
        "price": 189.90,
        "category": "Kişisel Bakım > Sabun & Duş Jeli > El Sabunu",
        "brand": "EgeNatura",
        "rating": 4.8,
        "review_count": 4521,
        "images": [
            "https://picsum.photos/seed/soap001/800/800",
            "https://picsum.photos/seed/soap002/800/800",
        ],
        "reviews": [
            {"rating": 5, "text": "Koku harika, elleri kurutmuyor. Hediye olarak da çok şık."},
            {"rating": 5, "text": "Kimyasal içermediği için çocuklarım için de kullanıyorum."},
            {"rating": 4, "text": "Lavanta kokulu en iyisi, diğerleri biraz hafif kalıyor."},
            {"rating": 5, "text": "Dermatoloğum önerdi, gerçekten fark yarattı."},
            {"rating": 5, "text": "Her ay tekrar sipariş veriyorum, vazgeçemedim."},
            {"rating": 3, "text": "Beklenenden daha küçük, gramaj biraz az geldi."},
        ],
    },
    {
        "id": "tc-006",
        "title": "Masaüstü Kablosuz Şarj Standı 3'ü 1 Arada iPhone Samsung Uyumlu",
        "description": "Telefon, akıllı saat ve kulaklığınızı aynı anda şarj eden kablosuz şarj standı. 15W hızlı şarj destekli. Anti-kayma tabanı ile masanızda güvenle durur. LED gösterge ile şarj durumunu takip edin.",
        "price": 649.00,
        "category": "Elektronik > Şarj Cihazları > Kablosuz Şarj",
        "brand": "ChargeHub",
        "rating": 4.1,
        "review_count": 673,
        "images": [
            "https://picsum.photos/seed/charger1/800/800",
            "https://picsum.photos/seed/charger2/800/800",
        ],
        "reviews": [
            {"rating": 5, "text": "3 cihazı aynı anda şarj ediyor, masa çok temiz kaldı."},
            {"rating": 4, "text": "Hızlı şarj gerçekten hızlı, 1 saatte %80 doldu."},
            {"rating": 3, "text": "Samsung uyumluluğu bazen sorunlu, bağlantı kesiyor."},
            {"rating": 4, "text": "Tasarımı çok şık, masaya çok yakışıyor."},
            {"rating": 2, "text": "Beklediğim kadar iyi değildi, ısınma problemi var."},
        ],
    },
]

# in-memory state — sunucu restart'ta sıfırlanır
_state: dict[str, dict] = {p["id"]: copy.deepcopy(p) for p in _CATALOG}


def get_products() -> list[dict]:
    """Tüm ürünleri döner (reviews hariç, liste görünümü için)."""
    result = []
    for p in _state.values():
        summary = {k: v for k, v in p.items() if k != "reviews"}
        summary["review_count"] = len(p.get("reviews") or [])
        result.append(summary)
    return result


def get_product(product_id: str) -> dict | None:
    return copy.deepcopy(_state.get(product_id))


def update_product(product_id: str, title: str | None = None, description: str | None = None) -> dict | None:
    if product_id not in _state:
        return None
    if title:
        _state[product_id]["title"] = title
    if description:
        _state[product_id]["description"] = description
    return copy.deepcopy(_state[product_id])
