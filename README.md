# Esnaf Kopilot

Trendyol satıcılarının ürün listelerini otomatik analiz edip iyileştiren SaaS backend.

Kullanıcı bir Trendyol ürün linki girer. Sistem:
1. Ürün başlığını, açıklamasını, yorumlarını ve görsellerini çeker
2. Gemini API ile SEO + AEO puanı verir (100 üzerinden)
3. Optimize edilmiş başlık ve açıklama üretir
4. Görselleri analiz edip iyileştirilmiş versiyonlarını üretir

---

## Mimari

```
backend/
├── app/
│   ├── config.py          # Ortam değişkeni yönetimi
│   ├── models.py          # Tüm veri modelleri
│   ├── api.py             # FastAPI endpoint'leri
│   ├── pipeline.py        # Ana iş akışı
│   ├── scraper/
│   │   ├── http_client.py    # Rate-limited HTTP istemci
│   │   ├── html_parsing.py   # HTML/JSON parsing yardımcıları
│   │   └── trendyol.py       # Trendyol veri çekici
│   └── analyzer/
│       ├── gemini_client.py  # Gemini API wrapper
│       ├── prompts.py        # Prompt şablonları
│       ├── content.py        # SEO/AEO analiz ve içerik üretimi
│       └── image.py          # Görsel analiz ve iyileştirme
├── criteria/              # Puanlama kriterleri (txt)
└── tests/                 # Testler
```

## Teknoloji

| Katman | Teknoloji |
|--------|-----------|
| Backend | Python 3.12 + FastAPI |
| AI | Google Gemini API |
| Scraping | urllib + regex (sıfır ek bağımlılık) |
| Config | pydantic-settings |

---

## Kurulum

### 1. Gereksinimler

- Python 3.12+
- Google Gemini API key ([buradan alınır](https://aistudio.google.com/apikey))

### 2. Kurulum

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

### 3. API Key

```bash
cp .env.example .env
# .env dosyasını aç, GEMINI_API_KEY alanını doldur
```

### 4. Çalıştır

```bash
uvicorn app.main:app --reload
```

API dokümantasyonu: http://localhost:8000/docs

---

## API Endpoint'leri

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| `POST` | `/api/analyze` | Tam analiz (scrape + puan + içerik + görsel) |
| `POST` | `/api/scrape` | Sadece veri çekme |
| `POST` | `/api/score` | Sadece SEO/AEO puanlama |
| `POST` | `/api/generate-content` | Başlık + açıklama üretimi |
| `POST` | `/api/analyze-images` | Görsel analiz |
| `POST` | `/api/enhance-image` | Tek görsel iyileştirme |
| `GET` | `/api/health` | Sağlık kontrolü |

### Örnek İstek

```bash
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.trendyol.com/urun-linki"}'
```

### Örnek Yanıt

```json
{
  "product": {
    "title": "...",
    "description": "..."
  },
  "score": {
    "total_score": 67,
    "max_score": 100,
    "categories": [...]
  },
  "content": {
    "new_title": "...",
    "new_description": "...",
    "suggested_keywords": [...],
    "faq": [...]
  },
  "image_analyses": [...],
  "generated_images": [...]
}
```

---

## Puanlama Sistemi

### SEO / Pazaryeri Arama Uyumu — 50 Puan

| # | Kriter | Puan |
|---|--------|------|
| 1 | Başlık kalitesi | 12 |
| 2 | Açıklama kalitesi | 12 |
| 3 | Anahtar kelime uyumu | 10 |
| 4 | Ürün özellik tamlığı | 10 |
| 5 | Kategori/marka tutarlılığı | 6 |

### AEO / AI Okunabilirlik — 50 Puan

| # | Kriter | Puan |
|---|--------|------|
| 6 | Cevap-öncelikli tanım | 10 |
| 7 | Yapılandırılmış bilgi düzeni | 10 |
| 8 | SSS uygunluğu | 8 |
| 9 | Yorum içgörüleri kullanımı | 10 |
| 10 | Varlık tutarlılığı | 7 |
| 11 | Doğrulanabilirlik | 5 |

---

## Görsel İyileştirme

Sistem görselleri **değiştirmez, iyileştirir**.

- Orijinal ürün 1:1 korunur (renk, form, materyal asla değişmez)
- ANA_GORSEL için 3 konsept üretilir:
  - **Profesyonel Beyaz Fon** — Platform listeleme standardı
  - **Tematik Sahne** — Ürüne uygun yaşam tarzı görseli
  - **Sosyal Medya** — Reklam için dikkat çekici kompozisyon
- DIGER_GORSEL için teknik kalite iyileştirmesi yapılır

---

## Veri Kaynakları

Trendyol scraper çok katmanlı fallback zinciri kullanır:

**Ürün bilgisi:**
JSON-LD → __NEXT_DATA__ → Trendyol API → HTML parsing → Playwright (opsiyonel)

**Yorumlar:**
Trendyol Review API (çok sayfalı, 30 yorum/sayfa)

**Görseller:**
JSON-LD → og:image meta → __NEXT_DATA__ → Script JSON → CDN regex

---

## Geliştirme Notları

- `Scrape Test Moduls/` — Geliştirme sürecinde test edilen ham scraper modülleri
- `criteria/` — Gemini prompt'larında kullanılan puanlama kriterleri
- `Log.md` — Adım adım geliştirme logu
- `Task List.md` — Görev takip listesi
