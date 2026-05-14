# Esnaf Kopilot — Görev Listesi

## Faz 1: Proje Altyapısı

- [ ] 1.1 — Backend proje yapısını oluştur (dizinler, __init__.py dosyaları)
- [ ] 1.2 — pyproject.toml oluştur (bağımlılıklar tanımla)
- [ ] 1.3 — .env.example oluştur
- [ ] 1.4 — config.py — Pydantic Settings ile ortam değişkeni yönetimi
- [ ] 1.5 — models.py — Tüm veri modelleri (Product, Review, ProductImage, ScrapedProduct, ScoreResult, ContentResult, ImageAnalysis, AnalysisResult)
- [ ] 1.6 — Kriter txt dosyalarını backend/criteria/ altına kopyala

## Faz 2: Scraper Modülü

- [ ] 2.1 — http_client.py — Rate-limited HTTP client (retry, curl fallback, text + binary)
- [ ] 2.2 — html_parsing.py — Ortak HTML/JSON parsing yardımcıları (iki eski scraper'dan birleştir)
- [ ] 2.3 — trendyol.py — TrendyolScraper sınıfı:
  - [ ] 2.3.1 — Ürün başlık + açıklama çekme (HTML + API endpoint fallback)
  - [ ] 2.3.2 — Yorum çekme (API endpoint + HTML fallback)
  - [ ] 2.3.3 — Görsel URL çekme + indirme
  - [ ] 2.3.4 — scrape_all() — Birleşik scraping metodu
- [ ] 2.4 — Scraper modülünü test et (gerçek Trendyol URL ile)

## Faz 3: Gemini API Entegrasyonu

- [ ] 3.1 — gemini_client.py — Gemini API wrapper:
  - [ ] 3.1.1 — Text analiz metodu (analyze_text)
  - [ ] 3.1.2 — Görsel analiz metodu (analyze_with_images)
  - [ ] 3.1.3 — Görsel düzenleme metodu (edit_image)
  - [ ] 3.1.4 — JSON response parsing (markdown code block extraction)
  - [ ] 3.1.5 — Retry ve error handling
- [ ] 3.2 — Gemini client'ı basit bir promptla test et

## Faz 4: İçerik Analiz Modülü

- [ ] 4.1 — prompts.py — Prompt şablonları:
  - [ ] 4.1.1 — build_scoring_prompt() — SEO/AEO puanlama promptu
  - [ ] 4.1.2 — build_content_prompt() — Başlık/açıklama üretim promptu
  - [ ] 4.1.3 — build_image_analysis_prompt() — Görsel analiz promptu
  - [ ] 4.1.4 — build_image_edit_prompt() — Görsel düzenleme promptu
- [ ] 4.2 — content.py — ContentAnalyzer:
  - [ ] 4.2.1 — score() — Ürünü puanlama (100 puan üzerinden)
  - [ ] 4.2.2 — generate() — Yeni başlık + açıklama üretimi
- [ ] 4.3 — İçerik analizini test et (scraper çıktısı ile)

## Faz 5: Görsel Analiz Modülü

- [ ] 5.1 — image.py — ImageAnalyzer:
  - [ ] 5.1.1 — analyze() — Görselleri sınıflandır + puana + düzenleme promptu üret
  - [ ] 5.1.2 — enhance() — Gemini Image API ile görsel iyileştirme
- [ ] 5.2 — Görsel analizini test et

## Faz 6: Pipeline ve API

- [ ] 6.1 — pipeline.py — Ana orkestrasyon:
  - [ ] 6.1.1 — run_full_analysis(url) — Tam pipeline
  - [ ] 6.1.2 — Her adımı bağımsız çağırabilme
- [ ] 6.2 — api.py — FastAPI endpoint'ler:
  - [ ] 6.2.1 — POST /api/analyze (tam pipeline)
  - [ ] 6.2.2 — POST /api/scrape (sadece scraping)
  - [ ] 6.2.3 — POST /api/score (sadece puanlama)
  - [ ] 6.2.4 — POST /api/generate-content (sadece içerik üretimi)
  - [ ] 6.2.5 — POST /api/analyze-images (sadece görsel analiz)
  - [ ] 6.2.6 — POST /api/enhance-image (tek görsel iyileştirme)
  - [ ] 6.2.7 — GET /api/health
- [ ] 6.3 — main.py — FastAPI app, CORS, static file mounting
- [ ] 6.4 — API'yi test et (curl / Postman ile)

## Faz 7: Test Frontend

- [ ] 7.1 — index.html — Sayfa yapısı
- [ ] 7.2 — index.css — Dark theme, modern stil
- [ ] 7.3 — app.js — API çağrıları, sonuç gösterimi
- [ ] 7.4 — Frontend'i tarayıcıda test et

## Faz 8: Entegrasyon Testi

- [ ] 8.1 — Tam pipeline testi (gerçek Trendyol URL → sonuç)
- [ ] 8.2 — Hata senaryolarını test et (geçersiz URL, API hatası, vb.)
- [ ] 8.3 — Kod kalitesi kontrolü (ruff lint, docstring'ler)
- [ ] 8.4 — README.md oluştur (kurulum + kullanım talimatları)
