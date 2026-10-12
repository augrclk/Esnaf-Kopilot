# Esnaf Kopilot

E-ticaret satıcıları için yapay zeka destekli ürün optimizasyon platformu.

Mağazanızı bağlayın, ürünlerinizi analiz ettirin, AI ile içerik ve görselleri iyileştirin, satışlarınızı artırın.

---

## Ne Yapar?

1. **Mağaza Bağlantısı** — Pazaryeri mağazanızı bağlayın, ürünlerinizi otomatik içe aktarın
2. **Akıllı Analiz** — SEO/AEO puanlama (100 üzerinden), kategori bazlı kriterler, yorum analizi
3. **İçerik İyileştirme** — AI ile optimize edilmiş başlık, açıklama, anahtar kelimeler ve SSS üretimi
4. **Görsel İyileştirme** — Ürün görselleri profesyonel sahnelere yerleştirilerek yeniden üretilir (ürün birebir korunur)
5. **Hediye Önerileri** — Yorum analizine dayalı akıllı hediye paketi önerileri
6. **Deploy Önizleme** — İyileştirmeleri gerçek e-ticaret sayfası görünümünde önizleyin

---

## Ürün Yaşam Döngüsü

```
Mağaza Bağla → Ürün İçe Aktar → Analiz Et → İyileştir → Önizle & Deploy
```

| Aşama | Ne Olur |
|-------|---------|
| **İçe Aktar** | Mağazadan ürün verileri, görseller ve yorumlar çekilir |
| **Analiz Et** | Gemini AI ile SEO/AEO puanı + yorum analizi yapılır |
| **İyileştir** | Yeni başlık, açıklama, görseller, hediye önerileri üretilir |
| **Önizle** | Gerçek e-ticaret sayfası formatında tam sayfa önizleme |

---

## Mimari

```
frontend/
├── dashboard.html     # Ana dashboard (SPA)
├── app.js             # Uygulama mantığı
├── preview.html       # Ürün önizleme sayfası
└── style.css          # Stiller

backend/
├── app/
│   ├── config.py          # Ortam değişkeni yönetimi
│   ├── models.py          # Veri modelleri
│   ├── api.py             # FastAPI endpoint'leri + SSE streaming
│   ├── auth.py            # Firebase Authentication
│   ├── db.py              # Firestore veritabanı işlemleri
│   ├── test_commerce.py   # Mock e-ticaret mağazası (MVP)
│   ├── analyzer/
│   │   ├── gemini_client.py  # Gemini API wrapper (Vertex AI)
│   │   ├── content.py        # SEO/AEO analiz ve içerik üretimi
│   │   ├── image.py          # Görsel strateji ve iyileştirme
│   │   ├── review.py         # Yorum analizi
│   │   └── gift.py           # Hediye önerisi motoru
│   └── scraper/
│       ├── http_client.py    # Rate-limited HTTP istemci
│       └── trendyol.py       # Pazaryeri scraper
└── outputs/               # Üretilen görseller
```

## Teknoloji

| Katman | Teknoloji |
|--------|-----------|
| Frontend | Vanilla JS + Firebase Auth |
| Backend | Python 3.12 + FastAPI + SSE Streaming |
| AI | Google Gemini (Vertex AI) — metin + görsel |
| Veritabanı | Google Firestore |
| Auth | Firebase Authentication |
| Altyapı | GCP Compute Engine |

---

## Temel Özellikler

### Akıllı Puanlama
- 100 puan üzerinden SEO/AEO skoru
- Kategori bazlı dinamik kriterler (Kozmetik, Elektronik, Gıda vb.)
- Her kategoriye özel ağırlıklandırma

### Yorum Analizi
- Müşteri yorumlarından duygu analizi
- Tekrar eden şikayet ve övgü tespiti
- Yorum içgörülerinin içerik üretimine yansıtılması

### AI Görsel Üretimi
- Ürün birebir korunur, sahne tamamen değiştirilir
- Kategori bazlı sahne stratejisi (kozmetik → spa, elektronik → masa üstü, gıda → mutfak)
- İnfografik görseller için akıllı redesign
- 5-10 farklı konsept (stüdyo beyaz, yaşam tarzı, origin world vb.)

### Kuyruk Sistemi
- MVP API limitleri için akıllı kuyruk yönetimi
- Kullanıcıya gerçek zamanlı kuyruk durumu bildirimi
- 429 hatalarında otomatik exponential backoff retry

### Kullanıcı Yönetimi
- Firebase Auth (email/Google login)
- Tier bazlı kota sistemi (Free / Pro / Admin)
- Aylık analiz ve görsel üretim limitleri

---

## MVP — Test Commerce

MVP aşamasında gerçek pazaryeri API entegrasyonları yerine, test amaçlı **mock e-ticaret mağazası** hazırlanmıştır.

6 gerçek ürün (kozmetik, elektronik, aksesuar), gerçekçi müşteri yorumları ve ürün görselleriyle tam akışın test edilmesini sağlar.

Production'da Trendyol, Hepsiburada, Amazon gibi pazaryeri entegrasyonları eklenecektir.

---

## Kurulum

### Gereksinimler
- Python 3.12+
- Google Cloud hesabı (Vertex AI + Firestore + Firebase Auth)
- Node.js (opsiyonel, frontend dev server için)

### Backend

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Ortam Değişkenleri

```bash
cp .env.example .env
# .env dosyasını düzenle:
#   VERTEX_PROJECT=your-gcp-project
#   VERTEX_LOCATION=europe-west1
#   GEMINI_TEXT_MODEL=gemini-3.1-flash-lite
#   GEMINI_IMAGE_MODEL=gemini-3.1-flash-image-preview
```

### Çalıştır

```bash
uvicorn main:app --reload
```

API dokümantasyonu: `http://localhost:8000/docs`

### Frontend

Backend çalışırken ikinci bir terminalde, repo kökünden frontend'i sunun:

```bash
python3.12 -m http.server 5500 --bind 127.0.0.1 --directory frontend
```

Dashboard: `http://localhost:5500/dashboard.html`

Frontend, `localhost` üzerinde çalışırken API isteklerini `http://localhost:8000` adresine gönderir. Backend frontend dosyalarını sunmadığından dashboard'u frontend sunucusunun portundan açın.

---

## API Endpoint'leri

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| `POST` | `/api/products/{product_id}/analyze` | Ürün analizi (SEO/AEO skor + yorum) |
| `GET` | `/api/products/{product_id}/improve` | SSE stream — içerik + görsel iyileştirme |
| `GET` | `/api/products` | Kullanıcının ürün listesi |
| `POST` | `/api/stores/{store_id}/import` | Mağazadan ürün içe aktar; ürün kimlikleri istek gövdesindeki `product_ids` listesinde verilir |
| `GET` | `/api/queue/status` | Kuyruk durumu |
| `GET` | `/api/user/stats` | Dashboard metrikleri |
| `GET` | `/api/test-commerce/products` | Mock mağaza ürünleri |

---

## Lisans

Proprietary — Tüm hakları saklıdır.
