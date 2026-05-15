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

---

## 2026-05-14 17:40 — Faz 7 Tamamlandı ve Performans İyileştirmeleri Yapıldı

### Yapılan İş
- **Web Arayüzü (Frontend):** Modern, cam tasarımlı (Glassmorphism) `index.html`, `style.css` ve `app.js` dosyalarıyla bir test arayüzü yazıldı. Kullanıcı API üzerinden dönen tüm verileri (orijinal ürün, yeni başlık, yeni açıklama, SEO puanı, görsel stratejisi ve 8 farklı konsept) bu ekranda izleyebiliyor.
- **Paralel İşlem (Multithreading):** `pipeline.py` güncellendi. API kotaları genişletildiği için, görsel üretim aşaması `concurrent.futures.ThreadPoolExecutor` kullanılarak 8 resmin de **eşzamanlı (paralel)** üretilmesini sağlayacak şekilde yeniden tasarlandı. Süre dakikalardan saniyelere indirildi.
- **Prompt İyileştirmeleri:** Marka etiketlerinin otomatik üretilen başlıkta gereksiz yere en başa gelmesi önlendi (`prompts.py`). Yeni başlıkların tamamen organik ve doğal hissettirmesi sağlandı. Yeni açıklamaların (SEO & AEO uyumlu metinlerin) arayüzde gösterilmesindeki veri yolu (JSON path) hataları giderildi.

### Bir Sonraki Adım
Faz 8: Kullanıcı Testi ve Optimizasyonlar. Projenin ana iskeleti %100 tamamlandı. Sistem aktif olarak test edildikten sonra çıkacak olası edge-case'ler ve müşteri talepleri değerlendirilip ek iyileştirmeler (bug-fix) yapılacak.

---

## 2026-05-15 12:35 — Otonom AI Skill Mimarisi ve Dinamik Prompt Sistemi (Faz 8 İyileştirmeleri)

### Yapılan İş
- **"Skill" Tabanlı Görsel Planlama:** Sistem şablon tabanlı (statik 8 görsel) yapıdan **otonom Sanat Yönetmeni (AI Skill)** yapısına geçirildi. `app/analyzer/image.py` baştan yazılarak yapay zekaya "ürünün türüne göre kaç görsel üretilmesi gerektiği ve hangi orijinal kaynak görsellerin kullanılması gerektiği" konusunda tam özgürlük verildi.
- **İngilizce Profesyonel Promptlar:** Görsel üretimi için kullanılan Gemini promptları en üst düzey fotoğrafçılık terimleriyle ("cinematic composition", "85mm lens" vb.) İngilizceye çevrildi. Infografik üzerindeki metinlerin Türkçe olması kuralı katılaştırıldı.
- **Dinamik txt Okuma (Hot-Reload):** `Skor-kriter.txt` ve `Cıktı-Formati.txt` dosyalarının içeriği kod içine hardcode edilmekten kurtarıldı. `app/analyzer/prompts.py` güncellenerek, yapay zekanın her analizde bu `.txt` dosyalarını canlı (runtime) okuması sağlandı. Frontend çökmemesi için JSON çıktısını zorlayan güvenli system komutları kod bloklarına eklendi.
- **Model ve Hız Optimizasyonları:** Metin analiz modeli `gemini-2.5-flash`'a düşürülerek `503 Unavailable` hatası engellendi ve yorum tarama sayısı 5 sayfaya düşürülerek API/Scraper darboğazları aşıldı. Görsel üretim API model sırası `gemini-3.1-flash-image-preview` -> `gemini-3-pro-image-preview` olarak ayarlandı.

### Bir Sonraki Adım
Sistemin farklı e-ticaret kategorileri (tekstil, elektronik, kozmetik vb.) ile geniş çaplı son kullanıcı testlerinin yapılması.

---

## 2026-05-15 12:45 — Yorum Analizi ve Ürün Odaklı AI Chat Eklendi

### Yapılan İş
- **Yeni Modül — `analyzer/review.py`:** Ürün yorumlarını analiz eden bağımsız `ReviewAnalyzer` sınıfı yazıldı. Çekilen yorumları özetleyerek beğenilen noktalar, dikkat edilmesi gereken sorunlar ve cevaplanmamış müşteri soruları formatında yapılandırılmış JSON çıktı üretiyor.
- **Yeni API — `POST /api/chat`:** Ürün odaklı AI sohbet endpoint'i eklendi. Analiz sonucunun tamamını (SEO skoru, yeni başlık, yorum analizi) context olarak alır; genel sohbet yerine yalnızca söz konusu ürün hakkında yanıt verir. `GeminiClient`'a JSON parse gerektirmeyen `chat_text()` metodu eklendi.
- **Pipeline Güncellemesi:** `pipeline.py` güncellenerek yorum analizi pipeline'a eklendi. Artık `/api/analyze` yanıtı `review_analysis` alanını da içeriyor. Skor kategorileri (`categories`) ve content `notes` alanı da yanıta dahil edildi.
- **Frontend Güncellemesi:**
  - `Müşteri Yorum Analizi` kartı: Ortalama puan, beğenilen noktalar, sorunlar ve cevaplanmamış sorular iki sütunlu grid ile gösteriliyor.
  - `AI Chat` bölümü: "Bu ürün hakkında asistana sor" başlığıyla 6 hazır örnek soru ve serbest metin girişi ile chat arayüzü eklendi. Yazıyor animasyonu ve tam responsive tasarım mevcut.

### Bir Sonraki Adım
Farklı ürün kategorileriyle test; gerekirse chat context'ine SSS ve görsel strateji bilgisi de eklenebilir.
