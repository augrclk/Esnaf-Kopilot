"""
Test Commerce — geliştirici testleri için sahte e-ticaret mağazası.

Gerçek bir pazaryeri API'si gibi davranır:
  GET  /api/test-commerce/products
  GET  /api/test-commerce/products/{id}
  PUT  /api/test-commerce/products/{id}   ← iyileştirme deploy edilince buraya gelir

İn-memory state: sunucu yeniden başlayınca sıfırlanır.
Görseller /outputs/tc_images/ üzerinden servis edilir.
"""
from __future__ import annotations
import copy

_IMG = "/outputs/tc_images"

_CATALOG: list[dict] = [
    {
        "id": "tc-001",
        "title": "FARGIN Mango Hand Cream 75 ml – Mango Aromalı Nemlendirici El Kremi",
        "description": (
            "Elleri gün boyu nemlendirmeye yardımcı olan hafif ve hızlı emilen bir el kremidir. "
            "Ferah mango aroması ile hoş bir koku bırakır ve yağlı bir his oluşturmaz. "
            "Düzenli kullanımda ellerin daha yumuşak, pürüzsüz ve bakımlı görünmesine destek olur. "
            "Günlük kullanıma uygun formülü sayesinde ihtiyaç oldukça uygulanabilir. "
            "Çanta boy tasarımı ile her yerde kolayca taşınabilir ve kullanımı pratiktir."
        ),
        "price": 89.90,
        "category": "Kişisel Bakım > El & Ayak Bakımı > El Kremi",
        "brand": "FARGIN",
        "rating": 4.3,
        "review_count": 214,
        "images": [
            f"{_IMG}/tc001_1.png",
        ],
        "reviews": [
            {"rating": 5, "text": "Koku çok güzel, elleri yumuşatıyor. Kış aylarında vazgeçilmezim oldu."},
            {"rating": 4, "text": "Küçük boy çantaya çok uygun. Yağlı his bırakmıyor ama nemlendirme birkaç saat sonra azalıyor."},
            {"rating": 2, "text": "Kargo 6 günde geldi, kutu ezilmiş halde teslim edildi. Ürün sağlam ama kargo rezalet."},
            {"rating": 5, "text": "Günde birkaç kez kullanıyorum, elleri kurutmuyor. Mango kokusu hafif ve rahatsız etmiyor."},
            {"rating": 3, "text": "Koku biraz hafif, daha yoğun olmasını tercih ederdim. Nemlendirme iddia edildiği kadar uzun sürmüyor."},
            {"rating": 1, "text": "Ürünün miadı yaklaşmış, son 2 ay kalmış. Bunu belirtmeden satmak doğru değil."},
            {"rating": 4, "text": "Fiyatına göre gayet iyi bir el kremi. İkinci siparişimi verdim."},
            {"rating": 5, "text": "Annem için aldım bayıldı, şimdi 3 tane daha sipariş ettim."},
        ],
    },
    {
        "id": "tc-002",
        "title": "Escabel Avokadolu Soft El Yüz Ve Vücut Kremi 250 ml",
        "description": (
            "Avokado yağı, cildi derinlemesine nemlendirir ve yumuşatır. Kuru ve çatlamış eller için ideal bir çözümdür. "
            "İçerdiği E Vitamini ve çeşitli antioksidanlar sayesinde cildi besler ve cilt bariyerini güçlendirir. "
            "Anti-aging etkisiyle cildin yaşlanma belirtilerini azaltmaya yardımcı olur. "
            "Avokado yağı cilt hücrelerinin yenilenmesini destekler. "
            "Düzenli kullanımda cildin yumuşak ve pürüzsüz kalmasını sağlar. "
            "Kuru ve hassas ciltler için etkili bir bakım ürünüdür."
        ),
        "price": 129.00,
        "category": "Kişisel Bakım > Vücut Bakımı > Vücut Kremi",
        "brand": "Escabel",
        "rating": 4.5,
        "review_count": 387,
        "images": [
            f"{_IMG}/tc002_1.png",
        ],
        "reviews": [
            {"rating": 5, "text": "Avokadolu kremler arasında en iyisi. Cilt gerçekten yumuşuyor, 3. kutumu kullanıyorum."},
            {"rating": 5, "text": "250 ml boyutuyla uzun süre gidiyor, fiyat performans süper."},
            {"rating": 4, "text": "Koku biraz yoğun ama kalıcı değil. Yüze sürdüğümde biraz ağır geldi, vücut için mükemmel."},
            {"rating": 2, "text": "Kargo sırasında kapak açılmış, kremin yarısı kutuya akmış. Satıcıya yazdım 3 gündür cevap yok."},
            {"rating": 5, "text": "Kışın çatlamış ellerime ilaç gibi geldi. Gece sürdüğümde sabah ellerin ipek gibi."},
            {"rating": 3, "text": "İçerikte paraben yazıyor, doğal ürün diye aldım ama tam doğal değilmiş. Açıklama yanıltıcı."},
            {"rating": 4, "text": "Eşim de kullanmaya başladı, erkekler için de gayet uygun."},
            {"rating": 1, "text": "Ürün fotoğraftakinden çok farklı geldi. Rengi ve kıvamı farklı, sahte olabilir."},
            {"rating": 5, "text": "Dermatolojistim önerdi, hassas cildime uygun tek krem bu oldu."},
        ],
    },
    {
        "id": "tc-003",
        "title": "H2O Humidifier Taşınabilir Ultrasonik Hava Nemlendirici Buhar Makinesi ve Aroma Difüzörü",
        "description": (
            "Taşınabilir tasarımı sayesinde evde, ofiste veya seyahatlerde kolayca taşınabilir ve her yerde rahatlıkla kullanılabilir. "
            "Ultrasonik teknolojisi ile havaya nem verirken aynı zamanda hoş kokuların yayılmasını sağlar, "
            "böylece hem nemlendirici hem de aroma difüzörü olarak işlev görür. "
            "Uzun süreli kullanım için idealdir. "
            "Düşük enerji tüketimiyle ekonomik bir seçenek sunar ve enerji tasarrufu sağlar. "
            "Not: Yanında koku gelmemektedir."
        ),
        "price": 249.90,
        "category": "Ev & Yaşam > Hava Nemlendirici > Ultrasonik Nemlendirici",
        "brand": "H2O",
        "rating": 4.1,
        "review_count": 562,
        "images": [
            f"{_IMG}/tc003_1.png",
            f"{_IMG}/tc003_2.png",
            f"{_IMG}/tc003_3.png",
        ],
        "reviews": [
            {"rating": 5, "text": "Ofisimde kullanıyorum, ses yok denecek kadar sessiz. Çalışma arkadaşlarım fark bile etmiyor."},
            {"rating": 4, "text": "Aroma difüzörü kısmı harika, koku yayılımı çok iyi. Lavanta yağıyla denedim süper."},
            {"rating": 2, "text": "Su deposu çok küçük, 3-4 saatte bitiyor. Gece boyunca kullanmak isteyenler için yetersiz."},
            {"rating": 4, "text": "Tasarımı çok şık, masaya yakışıyor. USB ile çalışması büyük avantaj."},
            {"rating": 1, "text": "2 hafta sonra buhar çıkışı durdu. İade ettim ama kargo ücretini ben ödedim, 45 TL gitti."},
            {"rating": 5, "text": "Kışın evdeki kuruluğa gerçekten çözüm oldu. Bebeğin odasında kullanıyoruz."},
            {"rating": 3, "text": "Yanında koku gelmediğini ürün açıklamasında göremedim. Ayrı almak zorunda kaldım."},
            {"rating": 2, "text": "Kargoda hasar görmüş, kutu ezik geldi. Ürün çalışıyor ama çizikler var üzerinde."},
            {"rating": 4, "text": "İkinci kez aldım, ilki 8 ay sorunsuz çalıştı. Fiyatına göre iyi."},
            {"rating": 1, "text": "Açıklamada 'uzun süreli kullanım' yazıyor ama 4 saat bile dayanmıyor. Yanıltıcı bilgi."},
        ],
    },
    {
        "id": "tc-004",
        "title": "Tala Hindistan Cevizi Yağı %100 Saf ve Doğal Soğuk Sıkım 150 ml",
        "description": (
            "Tala Hindistan Cevizi Yağı, doğallığı ve saflığıyla cildinize, saçınıza ve vücudunuza eşsiz bir bakım sunar. "
            "%100 saf ve soğuk sıkım yöntemiyle elde edilen bu yağ, cildinizi nemlendirir, saçlarınıza parlaklık katar "
            "ve sağlıklı bir görünüm kazandırır. "
            "Doğal antioksidanlarla dolu yapısı sayesinde besleyici, yatıştırıcı ve onarıcı etkisiyle "
            "her kullanımda kendinizi tazelenmiş hissedersiniz. "
            "Tamamen doğal, katkısız ve saf formülüyle hem cildiniz hem de saçınız için güvenle kullanabilirsiniz. "
            "Kuru ciltler ve yıpranmış saçlar için derinlemesine nemlendirme sağlar. "
            "Güzellik rutininizin yanı sıra mutfakta da sağlıklı bir alternatif olarak kullanabilirsiniz."
        ),
        "price": 179.00,
        "category": "Kişisel Bakım > Saç Bakımı > Saç & Cilt Yağı",
        "brand": "Tala",
        "rating": 4.6,
        "review_count": 1089,
        "images": [
            f"{_IMG}/tc004_1.png",
            f"{_IMG}/tc004_2.png",
        ],
        "reviews": [
            {"rating": 5, "text": "Saçlarımda muhteşem fark yarattı, parlaklık inanılmaz. Kuru uçlar için birebir."},
            {"rating": 5, "text": "Soğuk sıkım olduğu için kalitesi gerçekten yüksek. Kokusu hafif ve doğal."},
            {"rating": 4, "text": "Cilt nemlendiricisi olarak kullanıyorum, çok memnunum ama kıvamı soğukta katılaşıyor."},
            {"rating": 2, "text": "Şişe 150 ml yazıyor ama tartınca 130 ml civarı çıktı. Eksik gelmiş gibi."},
            {"rating": 5, "text": "Hem mutfakta hem bakımda kullanıyorum, çok yönlü ürün. Hindistan cevizi kokusu harika."},
            {"rating": 3, "text": "Şişenin kapağı biraz sıkı, açmak uğraştırıyor. Kapak tasarımı geliştirilmeli."},
            {"rating": 1, "text": "Kargo 9 gün sürdü, takip numarası güncellenmiyordu. Satıcıya ulaşamadım."},
            {"rating": 5, "text": "Anneme aldım, o da sipariş verdi artık. Kesinlikle tavsiye ederim."},
            {"rating": 4, "text": "Doğal ve saf olduğunu test ettirdim, gerçekten katıksız. Güvenilir marka."},
            {"rating": 2, "text": "Son kullanma tarihi çok yakındı, 3 ay kalmış. Stok devir hızı düşük galiba."},
        ],
    },
    {
        "id": "tc-005",
        "title": "ASUS TUF Gaming VG259QMR5A 24.5\" 310Hz 0.3ms HDMI+DP HDR FullHD G-Sync FreeSync IPS Monitör",
        "description": (
            "Ekran Boyutu: 24.5 inç. Çözünürlük: 1920 x 1080. Tepki Süresi: 0.3 ms. "
            "Bağlantı Özellikleri: HDMI, DisplayPort. Ekran Paneli: Fast IPS. "
            "Garanti: 36 Ay. Diğer Özellikler: Adaptive-Sync, G-Sync Compatible, FreeSync Premium. "
            "Kontrast: 1000:1. Ağırlık: 3.8 kg. Parlaklık: 300 cd/m². "
            "Dahili Hoparlör: 2W x 2. Yenileme Hızı: 310 Hz. HDR desteği ile daha canlı renkler."
        ),
        "price": 7499.00,
        "category": "Bilgisayar > Monitör > Gaming Monitör",
        "brand": "ASUS",
        "rating": 4.7,
        "review_count": 843,
        "images": [
            f"{_IMG}/tc005_1.png",
            f"{_IMG}/tc005_2.png",
            f"{_IMG}/tc005_3.png",
        ],
        "reviews": [
            {"rating": 5, "text": "310Hz gerçekten fark yaratıyor, CS2'de input lag hissetmiyorum artık. IPS paneli renkleri de çok iyi."},
            {"rating": 5, "text": "0.3ms tepki süresi abartı değil, ghosting sıfıra yakın. Valorant için mükemmel."},
            {"rating": 4, "text": "Renk kalibrasyonu kutudan çıktığı gibi iyi ama sRGB modu biraz soluk. Manuel ayar şart."},
            {"rating": 2, "text": "Kargo sırasında ekranın köşesinde dead pixel oluşmuş. İade süreci 2 hafta sürdü, çok yorucu."},
            {"rating": 5, "text": "VESA uyumlu olması büyük artı, monitör koluna taktım masam çok daha düzenli."},
            {"rating": 3, "text": "Hoparlörler çok kötü, ses tinny ve zayıf. Kulaklık veya harici hoparlör şart. Bu fiyata daha iyisi olmalıydı."},
            {"rating": 4, "text": "G-Sync ve FreeSync ikisi de çalışıyor, tearing yok. Ama stand biraz plastik hissiyatlı."},
            {"rating": 1, "text": "3 ay sonra ekranda sarı lekeler belirdi. Garanti kapsamında gönderdim ama 1 aydır haber yok ASUS servisinden."},
            {"rating": 5, "text": "Bu fiyata 310Hz IPS bulmak zor. Rakiplerinden en az 2000 TL ucuz ve aynı performans."},
            {"rating": 4, "text": "HDR desteği var ama gerçek HDR değil, sadece HDR400 seviyesi. Yine de SDR'den farkı belli."},
            {"rating": 3, "text": "Kutu içeriği fakir, HDMI kablosu var ama DP kablosu yok. 310Hz için DP gerekiyor, ayrı aldım."},
            {"rating": 5, "text": "E-spor turnuvasında kullanıyoruz, takım arkadaşlarım da aynısını aldı. Profesyonel seviye."},
        ],
    },
    {
        "id": "tc-006",
        "title": "Wesse WWG208402 Erkek Klasik Kol Saati",
        "description": (
            "Ağırlık: 84 gr. Kasa Kalınlığı: 10 mm. Kasa Çapı: 40 mm. "
            "Su Geçirmezlik: 5 ATM. Kadran Tipi: Analog. Kasa Materyali: Çelik. "
            "Kordon Özelliği: Çelik. Menşei: Çin. Kategori: Erkek Klasik Saat. "
            "Stil: Klasik Saatler. Kadran Rengi: Mavi. Kasa Rengi: Metalik Gri. "
            "Kordon Rengi: Metalik Gri. Cam Özelliği: Mineral. Mekanizma: Quartz. "
            "Alarm: Var. Kasa Şekli: Yuvarlak."
        ),
        "price": 1299.00,
        "category": "Aksesuar > Saat > Erkek Kol Saati",
        "brand": "Wesse",
        "rating": 4.2,
        "review_count": 156,
        "images": [
            f"{_IMG}/tc006_1.png",
            f"{_IMG}/tc006_2.png",
            f"{_IMG}/tc006_3.png",
        ],
        "reviews": [
            {"rating": 5, "text": "Mavi kadran metalik gri kordonla çok şık duruyor. İş ortamında sürekli iltifat alıyorum."},
            {"rating": 4, "text": "Fiyatına göre kaliteli bir saat. Quartz mekanizma doğru çalışıyor, 3 aydır dakika bile şaşmadı."},
            {"rating": 3, "text": "5 ATM su geçirmezlik yazıyor ama yüzmeye girmeye cesaret edemedim. Sadece el yıkamada kullandım."},
            {"rating": 2, "text": "Kargo kutusu çok küçük ve korumasızdı, saat kutusu ezilmiş geldi. Saat sağlam ama hediye verilecek hali kalmadı."},
            {"rating": 5, "text": "Babama doğum günü hediyesi aldım, çok beğendi. Kutusu da şık, hediye için ideal."},
            {"rating": 1, "text": "Kordon kilitçesi 2 haftada bozuldu, saat kolumdan düştü. Kalite kontrol yetersiz."},
            {"rating": 4, "text": "Mineral cam çizilmeye dayanıklı, 4 aydır günlük kullanıyorum çizik yok."},
            {"rating": 3, "text": "Alarm özelliği var yazıyor ama nasıl ayarlanacağı hakkında Türkçe kılavuz yok. İngilizce bile kısa."},
            {"rating": 5, "text": "Bu fiyata çelik kasa ve kordon bulmak zor. Çin menşeli ama işçilik iyi."},
            {"rating": 2, "text": "Fotoğraftaki renk ile gelen ürün arasında fark var. Kadran daha koyu mavi, metalik gri daha mat geldi."},
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
