# Esnaf Kopilot — Proje Dokümantasyonu

## Proje Özeti

Esnaf Kopilot, e-ticaret satıcılarının ürün listelerini otomatik olarak analiz edip iyileştiren bir SaaS aracıdır. Kullanıcı bir Trendyol ürün linki girer; sistem ürün başlığını, açıklamasını, yorumlarını ve görsellerini çeker. Gemini API ile bu verileri analiz ederek SEO/AEO puanı verir, optimize edilmiş başlık/açıklama üretir ve görselleri profesyonel kaliteye yükseltir.

---

## İş Akışı (Pipeline)

```
┌─────────────────────────────────────────────────────────────────┐
│  1. KULLANICI                                                   │
│     Trendyol ürün linkini girer                                 │
└──────────────────────┬──────────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. SCRAPER MODÜLÜ                                              │
│     ├── Ürün başlığı çekme                                      │
│     ├── Ürün açıklaması çekme (HTML + API + Playwright fallback)│
│     ├── Yorumları çekme (API endpoint + HTML fallback)          │
│     └── Görselleri çekme + indirme (JSON-LD, meta, CDN regex)  │
└──────────────────────┬──────────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. İÇERİK ANALİZ MODÜLÜ (Gemini API)                          │
│     ├── SEO puanlama (50 puan) — Skor-kriter.txt kriterlerine göre│
│     ├── AEO puanlama (50 puan) — Skor-kriter.txt kriterlerine göre│
│     ├── Yeni başlık üretimi                                     │
│     └── Yeni açıklama üretimi                                   │
└──────────────────────┬──────────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. GÖRSEL ANALİZ MODÜLÜ (Gemini API)                           │
│     ├── Her görseli sınıflandır (ANA_GORSEL / DIGER_GORSEL)     │
│     ├── Görsel puanlama (Image-kriter.txt — 80 puan)            │
│     ├── Her görsel için düzenleme promptu üret                  │
│     │   ├── ANA_GORSEL → 3 konsept (beyaz fon, tematik, reklam) │
│     │   └── DIGER_GORSEL → 1 konsept (teknik iyileştirme)       │
│     └── Gemini Image API ile görselleri iyileştir               │
└──────────────────────┬──────────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. SONUÇ                                                       │
│     ├── Mevcut durum puanı (SEO + AEO = 100 üzerinden)          │
│     ├── Kategori bazlı puan kırılımı                            │
│     ├── Yeni başlık + açıklama önerisi                          │
│     ├── Görsel bazlı puanlar                                    │
│     └── İyileştirilmiş görseller (orijinal korunarak)           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Teknik Mimari

### Tech Stack

| Katman | Teknoloji |
|--------|-----------|
| Backend Framework | FastAPI |
| Python Sürümü | 3.12+ |
| AI API | Google Gemini (google-genai SDK) |
| HTTP Client | urllib (stdlib) + curl fallback |
| HTML Parsing | regex + HTMLParser (stdlib, bağımlılık yok) |
| Rendered Fallback | Playwright (opsiyonel) |
| Config | pydantic-settings + .env |
| Frontend | Vanilla HTML/CSS/JS (test amaçlı) |

### Dizin Yapısı

```
Esnaf-Kopilot/
├── Esnaf Kopilot.md          # Bu dosya — proje dokümantasyonu
├── Task List.md              # Görev listesi
├── Log.md                    # Geliştirme logu
├── Skor-kriter.txt           # SEO/AEO puanlama kriterleri
├── Cıktı-Formati.txt         # Çıktı format şablonu
├── backend/
│   ├── pyproject.toml        # Proje bağımlılıkları
│   ├── .env.example          # Ortam değişkenleri şablonu
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py           # FastAPI uygulama, CORS, static files
│   │   ├── config.py         # Pydantic Settings, env yönetimi
│   │   ├── models.py         # Tüm veri modelleri (Product, Review, vb.)
│   │   ├── api.py            # REST endpoint'ler + request/response şemaları
│   │   ├── pipeline.py       # Ana orkestrasyon servisi
│   │   ├── scraper/
│   │   │   ├── __init__.py
│   │   │   ├── http_client.py    # Rate-limited HTTP client (text + binary)
│   │   │   ├── html_parsing.py   # HTML/JSON parsing yardımcıları
│   │   │   └── trendyol.py       # Trendyol: ürün + yorum + görsel çekme
│   │   └── analyzer/
│   │       ├── __init__.py
│   │       ├── gemini_client.py  # Gemini API wrapper (text + image)
│   │       ├── prompts.py        # Prompt şablonları ve builder'lar
│   │       ├── content.py        # SEO/AEO puanlama + içerik üretimi
│   │       └── image.py          # Görsel analiz + iyileştirme
│   ├── criteria/                 # Kriter dosyaları (txt)
│   │   ├── skor_kriter.txt
│   │   ├── image_kriter.txt
│   │   └── image_olusturucu.txt
│   └── tests/
│       ├── __init__.py
│       └── test_scraper.py
└── frontend/
    ├── index.html
    ├── index.css
    └── app.js
```

### Toplam: ~15 Python dosyası

---

## Modül Detayları

### 1. Scraper Modülü (`app/scraper/`)

Trendyol ürün sayfasından veri çekme. Mevcut `modultest/backend/` altındaki iki ayrı scraper projesinin birleştirilmiş ve temizlenmiş hali.

**http_client.py** — Tek HTTP istemci:
- Rate limiting (istekler arası bekleme)
- Retry mekanizması (5xx hatalarda tekrar deneme)
- curl fallback (urllib başarısız olursa)
- Hem text hem binary (görsel) indirme desteği

**html_parsing.py** — Ortak parsing fonksiyonları:
- `normalize_text()` — HTML tag temizleme, whitespace düzenleme
- `first_non_empty()` — İlk boş olmayan değeri seçme
- `extract_meta_content()` — Meta tag'lerden veri çekme
- `extract_json_ld_products()` — JSON-LD structured data parsing
- `extract_next_data()` — __NEXT_DATA__ script parsing
- `find_values_by_keys()` — Nested JSON'da key arama
- `extract_product_id_from_url()` — URL'den ürün ID çıkarma
- `extract_img_urls()` — IMG tag'lerden URL çıkarma
- `extract_visible_text_by_class()` — CSS class ile metin çekme
- `parse_json_reviews()` — JSON formatında yorumları parse etme
- `parse_html_reviews()` — HTML formatında yorumları parse etme

**trendyol.py** — Trendyol'a özel adapter:
- `TrendyolScraper` sınıfı — tek giriş noktası
- `scrape_all(url)` → `ScrapedProduct` döner (başlık + açıklama + yorumlar + görseller)
- Ürün açıklaması için 3 katmanlı fallback:
  1. HTML sayfasından direkt parse
  2. Trendyol API endpoint'lerinden çekme
  3. Playwright ile rendered sayfadan çekme (opsiyonel)
- Yorumlar için API endpoint + HTML fallback
- Görseller için JSON-LD, meta, NEXT_DATA, script JSON, CDN regex

### 2. Analyzer Modülü (`app/analyzer/`)

Gemini API ile analiz ve üretim.

**gemini_client.py** — API wrapper:
- `analyze_text(system_prompt, user_prompt)` → JSON string
- `analyze_with_images(system_prompt, user_prompt, images)` → JSON string
- `edit_image(prompt, image_bytes)` → bytes
- Retry, timeout, rate limit
- JSON extraction (markdown code block'lardan)

**prompts.py** — Prompt şablonları:
- `build_scoring_prompt(product, reviews)` — Skor-kriter.txt kullanarak puanlama promptu
- `build_content_prompt(product, reviews, score)` — İçerik üretim promptu
- `build_image_analysis_prompt(product)` — Görsel sınıflandırma + düzenleme prompt üretimi
- `build_image_edit_prompt(analysis_json)` — Gemini Image API için düzenleme promptu

**content.py** — İçerik analiz servisi:
- `ContentAnalyzer.score(product, reviews)` → `ScoreResult`
- `ContentAnalyzer.generate(product, reviews, score)` → `ContentResult`

**image.py** — Görsel analiz servisi:
- `ImageAnalyzer.analyze(product, images)` → `list[ImageAnalysis]`
- `ImageAnalyzer.enhance(image_bytes, prompt)` → `bytes`

### 3. Pipeline (`app/pipeline.py`)

Tüm modülleri sırasıyla çalıştıran orkestrasyon:
1. URL → Scraper → ScrapedProduct
2. ScrapedProduct → ContentAnalyzer.score() → ScoreResult
3. ScrapedProduct + ScoreResult → ContentAnalyzer.generate() → ContentResult
4. ScrapedProduct → ImageAnalyzer.analyze() → ImageAnalysis listesi
5. Her görsel + prompt → ImageAnalyzer.enhance() → İyileştirilmiş görseller
6. Tüm sonuçları birleştir → AnalysisResult

İlk sürümde senkron çalışacak (kullanıcı bekler).

### 4. API (`app/api.py`)

FastAPI REST endpoint'leri:
- `POST /api/analyze` — Tam pipeline (URL gönder, tüm sonuçları al)
- `POST /api/scrape` — Sadece scraping
- `POST /api/score` — Sadece puanlama
- `POST /api/generate-content` — Sadece içerik üretimi
- `POST /api/analyze-images` — Sadece görsel analiz
- `POST /api/enhance-image` — Tek görsel iyileştirme
- `GET /api/health` — Health check

### 5. Frontend (`frontend/`)

Backend'i test etmek için minimal ama kullanılabilir web arayüzü:
- URL giriş alanı + "Analiz Başlat" butonu
- Ürün bilgileri paneli
- SEO/AEO puan göstergesi
- Yeni başlık/açıklama önerileri
- Görsel galerisi (orijinal vs iyileştirilmiş)
- Dark theme, responsive

---

## Puanlama Sistemi

### SEO / Pazaryeri Arama Uyumu — 50 Puan

| # | Kriter | Max Puan |
|---|--------|----------|
| 1 | Başlık Kalitesi | 12 |
| 2 | Açıklama Kalitesi | 12 |
| 3 | Anahtar Kelime ve Arama Niyeti Uyumu | 10 |
| 4 | Ürün Özellikleri / Attribute Tamlığı | 10 |
| 5 | Kategori, Marka ve Varyant Tutarlılığı | 6 |

### AEO / AI Okunabilirlik — 50 Puan

| # | Kriter | Max Puan |
|---|--------|----------|
| 6 | Cevap-Öncelikli Ürün Tanımı | 10 |
| 7 | Yapılandırılmış Bilgi Düzeni | 10 |
| 8 | SSS / Soru-Cevap Uygunluğu | 8 |
| 9 | Yorumlardan Gelen İçgörülerin Kullanımı | 10 |
| 10 | Varlık Tutarlılığı | 7 |
| 11 | Doğrulanabilirlik ve Uydurma Riskinin Düşüklüğü | 5 |

### Görsel Analiz — 80 Puan (Görsel Başına)

| # | Kriter | Max Puan |
|---|--------|----------|
| 1 | Teknik Kalite | 20 |
| 2 | Ana Görsel Kalitesi (sadece ANA_GORSEL) | 20 |
| 3 | Görsel Çeşitlilik (tüm set) | 15 |
| 4 | Metin ve Yazı Analizi | 15 |
| 5 | Kategori Uygunluğu | 10 |

---

## Görsel İyileştirme Konseptleri

### ANA_GORSEL için 3 Konsept:

1. **Profesyonel Beyaz Fon** — Platform listeleme standardı. Saf beyaz arka plan, stüdyo aydınlatması, merkez kadraj.
2. **Tematik Sahne** — Yaşam tarzı görseli. Ürüne uygun tema (tropikal, doğal, lüks, minimal vb.) ile sahne oluşturma.
3. **Sosyal Medya / Reklam** — Dikkat çekici reklam görseli. Tamamlayıcı renkler, metin alanı bırakma, premium his.

### DIGER_GORSEL için 1 Konsept:

- **Teknik İyileştirme** — Kompozisyon değişmez. Sadece çözünürlük, aydınlatma, netlik, renk canlılığı artırılır.

### Etik Sınırlar (Asla Çiğnenmez):
- ✗ Orijinal ürün görseli ile üretilen görsel arasında ürün 1:1 aynı olmalı — renk, materyal, form, şekil değiştirilemez
- ✗ İnsan/model eklenemez
- ✓ Arka plan ve ortam değiştirilebilir, özgün olabilir (sadece ANA_GORSEL) — mangolar, çiçekler, tematik sahneler eklenebilir
- ✓ Aydınlatma, çözünürlük, netlik iyileştirilebilir
- ~ Görseldeki yazılar: **İçerik korunur.** Font, renk, layout iyileştirilebilir. Sistem daha iyi bir tasar ım üretebiliyorsa uygular, aksi halde olduğu gibi bırakır.

---

## Referans Kodlar

Mevcut scraper kodları `Desktop/modultest/backend/` altında:
- `ecommerce_review_scraper/` — Ürün + yorum çekme (856 satır trendyol.py)
- `ecommerce_image_scraper/` — Görsel çekme + indirme (216 satır trendyol.py)
- `analyzer/` — Kriter txt dosyaları (skor, görsel analiz, görsel düzenleme şablonları)

Bu kodlar referans olarak kullanılacak, mantıkları korunarak temiz ve birleşik şekilde yeniden yazılacak.

---

## Kararlar

| Karar | Seçim | Sebep |
|-------|-------|-------|
| Pipeline modu | Senkron | İlk sürüm için basitlik |
| Görsel depolama | Dosya sistemi (outputs/) | Test için yeterli, sonra cloud eklenebilir |
| Gemini modeli (text/analiz) | gemini-3.1-pro-preview | Analiz, puanlama, içerik üretimi, görsel prompt hazırlama |
| Gemini modeli (image) | gemini-3-pro-image-preview | Görsel üretme/düzenleme (Nano Banana Pro) |
| HTML rendering | Playwright (opsiyonel) | Bazı açıklamalar JS ile yükleniyor |
| Veritabanı | Yok (ilk sürüm) | İlk sürümde dosya bazlı çıktı |
