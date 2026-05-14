# Esnaf Kopilot — Geliştirme Logu

Her görev tamamlandığında buraya not alınır.
Format: Tarih Saat:Dakika → Ne yapıldı → Neden → Bir sonraki adım

---

## 2026-05-13 19:36 — Proje Planlama

### Yapılan İş
- Mevcut referans kodlar incelendi:
  - `modultest/backend/ecommerce_review_scraper/` — Ürün + yorum çekme (5 dosya, ~28K trendyol.py)
  - `modultest/backend/ecommerce_image_scraper/` — Görsel çekme (5 dosya, ~7K trendyol.py)
  - `modultest/backend/analyzer/` — Kriter txt dosyaları (4 dosya)
- İki scraper'daki ortak kodlar tespit edildi (html_parsing, http_client, types tekrar ediyor)
- Kriter dosyaları okundu:
  - `Skor-kriter.txt` = `Cıktı-Formati.txt` (aynı içerik, SEO 50p + AEO 50p = 100p)
  - `Image-kriter.txt` — Görsel puanlama (80 puan, 5 kategori)
  - `Image-olusturucu.txt` — Görsel düzenleme prompt şablonları (3 konsept ANA_GORSEL, 1 konsept DIGER_GORSEL)

### Kararlar
- Dosya sayısı sadeleştirildi: ~25'ten ~15'e düşürüldü
- İlk sürüm senkron çalışacak
- Görseller dosya sisteminde tutulacak
- Gemini 2.5 Pro (text) + Gemini 2.0 Flash (image) kullanılacak

### Proje Dosyaları Oluşturuldu
- `Esnaf Kopilot.md` — Proje dokümantasyonu
- `Task List.md` — Görev listesi (8 faz)
- `Log.md` — Bu dosya

### Bir Sonraki Adım
- Faz 1: Proje altyapısını oluştur (dizinler, pyproject.toml, config, models)

## 2026-05-13 19:52 — Ortam Değişkenleri + Model Kararları

### Yapılan İş
- `backend/.env.example` oluşturuldu (GEMINI_API_KEY şablonu)
- `backend/.env` oluşturuldu (kullanıcı key'ini oraya ekleyecek)
- `backend/.gitignore` oluşturuldu (.env git'e gitmeyecek)

### Model Kararları Güncellendi
- Analiz, içerik üretimi, görsel prompt hazırlama: `gemini-2.5-pro-preview`
- Görsel üretme/düzenleme: `gemini-3-pro-image-preview`

### Görsel Etik Kurallar Güncellendi
- Orijinal ürün görseli ile üretilen görsel 1:1 aynı ürünü içermeli
- Arka plan, ortam, sahne özgün olabilir
- Görseldeki yazılar korunur — ancak sistem daha iyi bir versiyon üretebiliyorsa değiştirilebilir (içerik değil, tasarım)

### Bir Sonraki Adım
- Faz 1'e başla: Proje altyapısı (dizinler, pyproject.toml, config.py, models.py)

---

<!-- Sonraki loglar buraya eklenecek -->

## 2026-05-14 14:29 — Faz 1 + Faz 2 Tamamlandı

### Yapılan İş
**Faz 1 — Proje Altyapısı:** pyproject.toml, config.py, models.py, Python 3.12 venv kuruldu.
**Faz 2 — Scraper:** http_client.py, html_parsing.py, trendyol.py yazıldı ve test edildi.

### Test Sonucu (gerçek URL)
Ürün ID ✅ | Başlık ✅ | 26 Yorum ✅ | 7 Görsel ✅ | Açıklama ❌ (JS render gerekiyor, Playwright ile çözüldü)

---

## 2026-05-14 16:55 — Faz 3, Faz 4 ve Faz 5 Tamamlandı (AI ve Görsel Entegrasyonu)

### Yapılan İş
- **Gemini Client:** Text ve Image API işlemleri için `gemini_client.py` yazıldı. 503 ve 429 API Rate Limit hatalarına karşı **Exponential Backoff (Bekle-Tekrar Dene)** ve **Fallback Model** mantığı kuruldu.
- **Metin Analizi:** `content.py` yazıldı. SEO ve AEO kriterlerine göre ürün açıklaması, başlığı ve yorumlar analiz edilip 100 üzerinden puanlama yapıldı ve yepyeni optimize edilmiş içerik/başlık oluşturuldu.
- **Görsel Analizi & Üretimi:** `image.py` yazıldı.
  - Statik 7 konsept yerine, ürün bilgisinden yola çıkarak **ürüne tamamen özel 8 konsept** ("WOW" faktörlü) icat eden dinamik bir yapı kuruldu.
  - 8. konsept olarak **"Feature Infographic"** (Özellikleri resmin üstüne yazma) kuralı eklendi.
- **Orkestratör (Pipeline):** `pipeline.py` yazıldı. URL'yi alıp tüm bu aşamaları uçtan uca (Scrape -> Text -> Image -> 8 Concept Edit) otonom şekilde yürüten beyin tamamlandı.

### Bir Sonraki Adım
Faz 6: FastAPI Endpoint'lerinin yazılması (`app/api.py` ve `main.py`). Pipeline'ın HTTP istekleriyle tetiklenebilir hale getirilmesi.

---

## 2026-05-14 17:04 — Faz 6 Tamamlandı (API ve FastAPI)

### Yapılan İş
- **FastAPI Altyapısı:** `main.py` dosyası uvicorn ile çalışacak bir FastAPI uygulamasına dönüştürüldü. CORS ayarları ve statik dosya sunumu (`/outputs` dizini) yapılandırıldı.
- **Rotalar (Endpoints):** `app/api.py` dosyası oluşturuldu. 
  - `GET /api/health`
  - `POST /api/scrape`
  - `POST /api/analyze` uç noktaları eklendi. Sistem tamamen RESTful API mantığına oturtuldu.

### Bir Sonraki Adım
Faz 7: Test Frontend. Geliştirilen bu API'yi görselleştirecek ve test edilmesini sağlayacak basit bir web arayüzü hazırlanacak.
