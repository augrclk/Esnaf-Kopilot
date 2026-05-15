"""
API Katmanı — FastAPI endpoint'leri.

Mimari Notlar:
- Tüm endpoint'ler `async def` — FastAPI event loop'u bloke etmez
- Bloke eden Gemini çağrıları `asyncio.to_thread()` ile thread pool'a alınır
- Phase 2 içinde score() ve review.analyze() asyncio.gather() ile PARALEL çalışır
- Phase 3 içinde her görsel enhance görevi asyncio.gather() ile PARALEL çalışır
- ThreadPoolExecutor tamamen kaldırıldı → asyncio native parallelism
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import asyncio
import os
from datetime import datetime

from app.pipeline import EsnafKopilotPipeline
from app.scraper.http_client import HttpClient
from app.scraper.trendyol import TrendyolScraper
from app.analyzer.gemini_client import GeminiClient
from app.analyzer.content import ContentAnalyzer
from app.analyzer.image import ImageAnalyzer
from app.analyzer.review import ReviewAnalyzer
from app.models import ImageEditPrompt

router = APIRouter()

# ── Servisler (singleton) ────────────────────────────────────────────────────
http_client = HttpClient()
scraper     = TrendyolScraper(http_client)
gemini      = GeminiClient()
content_analyzer = ContentAnalyzer(gemini)
image_analyzer   = ImageAnalyzer(gemini)
review_analyzer  = ReviewAnalyzer(gemini)
pipeline         = EsnafKopilotPipeline()

# ── Scrape Cache (URL → ScrapedProduct) ─────────────────────────────────────
_scrape_cache: dict = {}

def _get_cached_scrape(url: str, max_review_pages: int = 5):
    """Senkron cache lookup — Phase 1 sonrası sadece dict okuma yapılır."""
    if url not in _scrape_cache:
        _scrape_cache[url] = scraper.scrape(url, max_review_pages=max_review_pages)
    return _scrape_cache[url]


# ── Request Modelleri ────────────────────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    url: str
    max_review_pages: int = 5

class ScrapeRequest(BaseModel):
    url: str
    max_review_pages: int = 2

class PhaseRequest(BaseModel):
    url: str
    output_dir: str = ""
    max_review_pages: int = 5

class ChatRequest(BaseModel):
    message: str
    analysis_context: dict


# ── Health ───────────────────────────────────────────────────────────────────
@router.get("/health")
async def health_check():
    return {"status": "ok", "message": "Esnaf Kopilot API is running"}


# ── Tam pipeline (geriye uyumluluk) ─────────────────────────────────────────
@router.post("/analyze")
async def analyze_full_pipeline(req: AnalyzeRequest):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir   = f"outputs/api_{timestamp}"
    os.makedirs(out_dir, exist_ok=True)
    try:
        results = await asyncio.to_thread(
            pipeline.run, req.url, req.max_review_pages, out_dir
        )
        return {"status": "success", "data": results, "output_dir": out_dir}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════════════
# AŞAMALI ENDPOINT'LER — async + paralel
# ════════════════════════════════════════════════════════════════════════════

@router.post("/phase/scrape")
async def phase_scrape(req: PhaseRequest):
    """
    FAZ 1 — Senkron scraping (network I/O).
    asyncio.to_thread ile thread pool'a alınır, event loop bloke olmaz.
    Sonuç cache'lenir → diğer fazlar tekrar çekmez.
    """
    try:
        scraped = await asyncio.to_thread(
            _get_cached_scrape, req.url, req.max_review_pages
        )

        review_sample = [
            {
                "rating": r.rating,
                "text": r.text[:180] + ("..." if len(r.text) > 180 else "")
            }
            for r in scraped.reviews[:5]
        ]

        return {
            "status": "success",
            "data": {
                "product": {
                    "title":       scraped.product.title,
                    "description": scraped.product.description,
                    "url":         scraped.product.url,
                    "product_id":  scraped.product.product_id,
                },
                "review_count":        len(scraped.reviews),
                "review_sample":       review_sample,
                "image_count":         len(scraped.images),
                "original_image_urls": [img.url for img in scraped.images[:3]],
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/phase/analyze")
async def phase_analyze(req: PhaseRequest):
    """
    FAZ 2 — İçerik + Yorum Analizi.

    Paralel çalışan Gemini metin çağrıları:
      ┌──────────────────────┐  ┌──────────────────────┐
      │  content_analyzer    │  │  review_analyzer     │
      │  .score()   ~15-20s  │  │  .analyze()  ~15-25s │
      └──────────────────────┘  └──────────────────────┘
              │ asyncio.gather() ile aynı anda başlar
              ▼
      score_result + review_analysis hazır olunca:
      └─► content_analyzer.generate()  ~20-30s
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir   = req.output_dir or f"outputs/api_{timestamp}"
    os.makedirs(out_dir, exist_ok=True)

    try:
        scraped = _get_cached_scrape(req.url, req.max_review_pages)  # cache lookup — instant

        # ── PARALEL: Puanlama + Yorum Analizi aynı anda ──────────────────────
        score_result, ra = await asyncio.gather(
            asyncio.to_thread(content_analyzer.score, scraped.product, scraped.reviews),
            asyncio.to_thread(review_analyzer.analyze, scraped.product, scraped.reviews),
        )

        # ── Ardından: Yeni içerik üretimi (score sonucuna bağlı) ─────────────
        new_content = await asyncio.to_thread(
            content_analyzer.generate,
            scraped.product,
            scraped.reviews,
            score_result.total_score
        )

        return {
            "status": "success",
            "output_dir": out_dir,
            "data": {
                "product": {
                    "original_title":       scraped.product.title,
                    "original_description": scraped.product.description,
                    "url":                  scraped.product.url,
                },
                "content_analysis": {
                    "score":         score_result.total_score,
                    "score_summary": score_result.summary,
                    "categories": [
                        {
                            "name":      c.name,
                            "score":     c.score,
                            "max_score": c.max_score,
                            "notes":     c.notes,
                        }
                        for c in score_result.categories
                    ],
                    "new_title":       new_content.new_title,
                    "new_description": new_content.new_description,
                    "faq":             new_content.faq,
                    "keywords":        new_content.suggested_keywords,
                    "notes":           new_content.notes,
                },
                "review_analysis": ra,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/phase/images")
async def phase_images(req: PhaseRequest):
    """
    FAZ 3 — Görsel İndirme + AI Üretim.

    Akış:
      1. Görselleri indir (asyncio.to_thread)
      2. AI strateji planla (asyncio.to_thread)
      3. Her konsepti asyncio.gather ile PARALEL enhance et
         — her biri bağımsız asyncio.to_thread görevi
         — timeout: her görev için 120s, aşarsa atlanır
    """
    out_dir = req.output_dir or f"outputs/api_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(out_dir, exist_ok=True)

    try:
        scraped = _get_cached_scrape(req.url, req.max_review_pages)  # instant

        # ── 1. Görselleri indir ───────────────────────────────────────────────
        downloaded  = await asyncio.to_thread(scraper.download_images, scraped.images, out_dir)
        valid_images = [img for img in downloaded if img.local_path]

        if not valid_images:
            return {"status": "success", "data": {"images": []}}

        # ── 2. AI strateji planla ─────────────────────────────────────────────
        analysis     = await asyncio.to_thread(image_analyzer.plan_strategy, scraped.product, valid_images)
        strategy_note = analysis.issues.get("analysis_note", "")
        print(f"[Phase/Images] Strateji: {len(analysis.edit_tasks)} konsept — paralel üretiliyor")

        # ── 3. Her konsepti bağımsız async görev olarak başlat ────────────────
        TASK_TIMEOUT = 120  # saniye

        async def _enhance_task(idx: int, task) -> dict | None:
            base      = os.path.basename(task.source_image.local_path).split('.')[0]
            ext       = os.path.basename(task.source_image.local_path).split('.')[-1]
            safe_name = "".join(c if c.isalnum() else "_" for c in task.concept_name)
            out_path  = os.path.join(out_dir, f"{base}_KONSEPT_{idx}_{safe_name}.{ext}")
            try:
                dummy_prompt = ImageEditPrompt(concept_name=task.concept_name, prompt=task.prompt)
                # Bloke eden enhance() → thread pool'a gönder
                enhanced = await asyncio.wait_for(
                    asyncio.to_thread(image_analyzer.enhance, task.source_image, dummy_prompt, out_path),
                    timeout=TASK_TIMEOUT
                )
                print(f"  ✓ Konsept {idx}: {task.concept_name}")
                return {"concept": task.concept_name, "path": enhanced.local_path}
            except asyncio.TimeoutError:
                print(f"  ✗ Konsept {idx} timeout ({TASK_TIMEOUT}s) — atlandı")
                return None
            except Exception as e:
                print(f"  ✗ Konsept {idx} hata: {e}")
                return None

        # Tüm task'lar asyncio.gather ile eş zamanlı başlatılır
        tasks = [
            _enhance_task(idx, task)
            for idx, task in enumerate(analysis.edit_tasks, 1)
        ]
        results  = await asyncio.gather(*tasks)
        enhanced = [r for r in results if r]

        return {
            "status": "success",
            "data": {
                "images": [{
                    "strategy_note":  strategy_note,
                    "enhanced":       enhanced,
                    "original_local": valid_images[0].local_path if valid_images else "",
                }]
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── AI Chat ──────────────────────────────────────────────────────────────────
@router.post("/chat")
async def chat_with_product(req: ChatRequest):
    """
    Ürün odaklı AI asistan.
    Gemini çağrısı asyncio.to_thread ile thread pool'da çalışır.
    """
    try:
        ctx     = req.analysis_context
        product = ctx.get("product", {})
        content = ctx.get("content_analysis", {})
        review  = ctx.get("review_analysis", {})

        positives_text = "\n".join(
            f"- {p.get('title', '')}: {p.get('detail', '')}"
            for p in review.get("positives", [])[:5]
        ) or "(Bilgi yok)"

        negatives_text = "\n".join(
            f"- {p.get('title', '')}: {p.get('detail', '')}"
            for p in review.get("negatives", [])[:5]
        ) or "(Bilgi yok)"

        unanswered = "\n".join(
            f"- {q}" for q in review.get("unanswered_questions", [])[:5]
        ) or "(Bilgi yok)"

        system_prompt = f"""Sen "Esnaf Kopilot" adlı bir e-ticaret AI asistanısın.
Sadece aşağıdaki ürün hakkında konuş. Genel sohbet etme, konudan çıkma.
Yanıtlar Türkçe, kısa ve pratik olsun.

=== ÜRÜN BİLGİSİ ===
Başlık: {product.get("original_title", "")}
Açıklama: {product.get("original_description", "")[:500]}

=== SEO ANALİZİ ===
Mevcut SEO Skoru: {content.get("score", "?")}/100
Önerilen Yeni Başlık: {content.get("new_title", "")}
Skor Özeti: {content.get("score_summary", "")}

=== MÜŞTERİ YORUM ANALİZİ ===
Beğenilen Noktalar:
{positives_text}

Sorunlu Noktalar:
{negatives_text}

Cevaplanmamış Sorular:
{unanswered}

Genel Duygu: {review.get("sentiment_summary", "")}
"""
        answer = await asyncio.to_thread(gemini.chat_text, system_prompt, req.message)
        return {"status": "success", "answer": answer}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Eski scrape endpoint (geriye uyumluluk) ──────────────────────────────────
@router.post("/scrape")
async def scrape_only(req: ScrapeRequest):
    try:
        scraped = await asyncio.to_thread(
            scraper.scrape, req.url, max_review_pages=req.max_review_pages
        )
        return {
            "status": "success",
            "data": {
                "product":       scraped.product,
                "reviews_count": len(scraped.reviews),
                "images":        scraped.images
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
