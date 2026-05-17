"""API Katmanı — FastAPI endpoint'leri."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import json
from pydantic import BaseModel
import asyncio
import logging
import os
from datetime import datetime
from time import monotonic

from app.pipeline import EsnafKopilotPipeline
from app.scraper.http_client import HttpClient
from app.scraper.trendyol import TrendyolScraper
from app.analyzer.gemini_client import GeminiClient
from app.analyzer.content import ContentAnalyzer
from app.analyzer.image import ImageAnalyzer
from app.analyzer.review import ReviewAnalyzer
from app.analyzer.gift import GiftAdvisor
from app.models import ImageEditPrompt, ProductNotFoundError, UnsupportedPlatformError
from app.config import settings

log = logging.getLogger(__name__)

router = APIRouter()

# ── Servisler (singleton) ────────────────────────────────────────────────────
http_client = HttpClient(
    timeout=settings.scraper_timeout,
    rate_limit=settings.scraper_rate_limit,
    retry_count=settings.scraper_retry_count,
)
scraper          = TrendyolScraper(http_client)
gemini           = GeminiClient()
content_analyzer = ContentAnalyzer(gemini)
image_analyzer   = ImageAnalyzer(gemini)
review_analyzer  = ReviewAnalyzer(gemini)
gift_advisor     = GiftAdvisor(gemini)
pipeline         = EsnafKopilotPipeline()

# ── Scrape Cache (URL → (ScrapedProduct, timestamp)) ─────────────────────────
# Phase 1 → Phase 2 → Phase 3 arasında verinin yaşaması için TTL'li async cache.
# _scrape_tasks: aynı URL için eş zamanlı ikinci istek gelirse tekrar scrape etmez,
#                devam eden Task'a attach olur → thundering herd önlenir.
_scrape_cache: dict = {}
_scrape_tasks: dict[str, asyncio.Task] = {}
_cache_lock = asyncio.Lock()
_CACHE_TTL = 7200  # 2 saat

# ── Görsel üretimde rate limiter ─────────────────────────────────────────────
# Semaphore=1: tek eş zamanlı istek.
# IMAGE_MIN_INTERVAL: ardışık istekler arası minimum süre (saniye).
# gemini-3.1-flash-image-preview ~4 RPM → 15s gap güvenli.
_IMAGE_SEM = asyncio.Semaphore(1)
_IMAGE_MIN_INTERVAL = 15.0  # saniye
_image_last_call: float = 0.0


async def _do_scrape(url: str, max_review_pages: int):
    """Bloklayan scrape işlemini thread pool'da çalıştırır, sonucu cache'e yazar."""
    scraped = await asyncio.to_thread(scraper.scrape, url, max_review_pages)
    async with _cache_lock:
        _scrape_cache[url] = (scraped, monotonic())
    return scraped


async def _get_or_scrape(url: str, max_review_pages: int = 5):
    """
    TTL'li async scrape cache — thundering herd korumalı.

    Cache hit  → anında döner.
    Scrape devam ediyor → aynı Task'a attach olur, iki kez scrape etmez.
    Cache miss → yeni Task başlatır, cache'e yazar.
    """
    async with _cache_lock:
        # 1. Geçerli cache var mı?
        entry = _scrape_cache.get(url)
        if entry:
            scraped, ts = entry
            if monotonic() - ts < _CACHE_TTL:
                return scraped

        # 2. Zaten devam eden scrape var mı?
        existing = _scrape_tasks.get(url)
        if existing and not existing.done():
            task = existing
        else:
            # 3. Yeni scrape başlat
            task = asyncio.create_task(_do_scrape(url, max_review_pages))
            _scrape_tasks[url] = task

    return await task


def _validate_url(url: str) -> None:
    """URL Trendyol domain'ine ait değilse 422 fırlatır."""
    if not TrendyolScraper.supports(url):
        raise HTTPException(
            status_code=422,
            detail="Sadece trendyol.com URL'leri destekleniyor.",
        )


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
    _validate_url(req.url)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir   = f"outputs/api_{timestamp}"
    os.makedirs(out_dir, exist_ok=True)
    try:
        results = await asyncio.to_thread(
            pipeline.run, req.url, req.max_review_pages, out_dir
        )
        return {"status": "success", "data": results, "output_dir": out_dir}
    except HTTPException:
        raise
    except ProductNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error("analyze error for %s: %s", req.url, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════════════
# AŞAMALI ENDPOINT'LER — async + paralel
# ════════════════════════════════════════════════════════════════════════════

@router.post("/phase/scrape")
async def phase_scrape(req: PhaseRequest):
    """FAZ 1 — Scraping. Sonuç TTL cache'e alınır → Phase 2/3 tekrar çekmez."""
    _validate_url(req.url)
    try:
        scraped = await _get_or_scrape(req.url, req.max_review_pages)

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
    except HTTPException:
        raise
    except ProductNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error("phase_scrape error for %s: %s", req.url, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/phase/analyze")
async def phase_analyze(req: PhaseRequest):
    """
    FAZ 2 — İçerik + Yorum Analizi (paralel Gemini çağrıları).
    score() + review.analyze() asyncio.gather() ile aynı anda → ardından generate().
    """
    _validate_url(req.url)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir   = req.output_dir or f"outputs/api_{timestamp}"
    os.makedirs(out_dir, exist_ok=True)

    try:
        scraped = await _get_or_scrape(req.url, req.max_review_pages)

        # ── PARALEL: Puanlama + Yorum Analizi aynı anda ──────────────────────
        score_result, ra = await asyncio.gather(
            asyncio.to_thread(content_analyzer.score, scraped.product, scraped.reviews),
            asyncio.to_thread(review_analyzer.analyze, scraped.product, scraped.reviews),
        )

        # ── PARALEL: İçerik üretimi + Hediye önerisi (ikisi de ra'ya bağlı) ──
        new_content, gift_suggestions = await asyncio.gather(
            asyncio.to_thread(
                content_analyzer.generate,
                scraped.product, scraped.reviews, score_result.total_score, ra,
            ),
            asyncio.to_thread(
                gift_advisor.suggest,
                scraped.product, ra,
            ),
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
                "gift_suggestions": gift_suggestions,
            }
        }
    except HTTPException:
        raise
    except ProductNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error("phase_analyze error for %s: %s", req.url, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/phase/images")
async def phase_images(req: PhaseRequest):
    """
    FAZ 3 — SSE Streaming görsel üretim.

    Her görsel tamamlanır tamamlanmaz `data:` eventi olarak gönderilir.
    Frontend hepsini beklemeden anında gösterir.

    Events:
      {type: 'start',    total: N, strategy_note: '...'}
      {type: 'image',    data: {concept, path}}   ← her görsel hazır olunca
      {type: 'retry',    idx: N, concept: '...'}  ← retry başladığında
      {type: 'done',     count: N, total: N}
      {type: 'error',    message: '...'}
    """
    _validate_url(req.url)

    def _sse(event: dict) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    async def _stream():
        out_dir = req.output_dir or f"outputs/api_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        os.makedirs(out_dir, exist_ok=True)

        try:
            scraped = await _get_or_scrape(req.url, req.max_review_pages)
            downloaded   = await asyncio.to_thread(scraper.download_images, scraped.images, out_dir)
            valid_images = [img for img in downloaded if img.local_path]

            if not valid_images:
                yield _sse({"type": "done", "count": 0, "total": 0})
                return

            analysis      = await asyncio.to_thread(image_analyzer.plan_strategy, scraped.product, valid_images)
            strategy_note = analysis.issues.get("analysis_note", "")
            total         = len(analysis.edit_tasks)
            log.info("[Phase/Images] %d konsept — SSE stream başlıyor", total)

            # Strateji hazır — frontend bölümü açabilir
            yield _sse({"type": "start", "total": total, "strategy_note": strategy_note})

            TASK_TIMEOUT = 120
            MAX_ATTEMPTS = 4
            RETRY_DELAYS = [10, 20, 40]  # attempt 1, 2, 3 sonrası bekleme

            async def _enhance_task(idx: int, task) -> dict | None:
                base      = os.path.basename(task.source_image.local_path).split('.')[0]
                ext       = os.path.basename(task.source_image.local_path).split('.')[-1]
                safe_name = "".join(c if c.isalnum() else "_" for c in task.concept_name)
                out_path  = os.path.join(out_dir, f"{base}_KONSEPT_{idx}_{safe_name}.{ext}")
                dummy     = ImageEditPrompt(concept_name=task.concept_name, prompt=task.prompt)

                for attempt in range(MAX_ATTEMPTS):
                    try:
                        async with _IMAGE_SEM:
                            # İstekler arası minimum bekleme — 429 baskısını önler
                            global _image_last_call
                            elapsed = asyncio.get_event_loop().time() - _image_last_call
                            if elapsed < _IMAGE_MIN_INTERVAL:
                                await asyncio.sleep(_IMAGE_MIN_INTERVAL - elapsed)
                            _image_last_call = asyncio.get_event_loop().time()

                            enhanced = await asyncio.wait_for(
                                asyncio.to_thread(image_analyzer.enhance, task.source_image, dummy, out_path),
                                timeout=TASK_TIMEOUT
                            )
                        log.info("  ✓ Konsept %d: %s", idx, task.concept_name)
                        return {"idx": idx, "concept": task.concept_name, "path": enhanced.local_path}
                    except asyncio.TimeoutError:
                        log.warning("Konsept %d timeout (%ds)", idx, TASK_TIMEOUT)
                    except Exception as e:
                        err = str(e)
                        if "429" in err or "RESOURCE_EXHAUSTED" in err or "503" in err:
                            if attempt < MAX_ATTEMPTS - 1:
                                wait = RETRY_DELAYS[attempt]
                                log.warning("  ⏳ Konsept %d rate-limit — %ds bekleniyor (deneme %d/%d)",
                                            idx, wait, attempt + 1, MAX_ATTEMPTS)
                                await asyncio.sleep(wait)
                                continue
                        log.error("Konsept %d hata: %s", idx, e)
                    break

                log.warning("Konsept %d tüm denemeler sonrası üretilemedi.", idx)
                return None

            # ── Tüm görevler paralel başlar, her biten anında stream'e gönderilir ──
            queue   = asyncio.Queue()
            count   = 0

            async def _run_and_enqueue(idx, task):
                result = await _enhance_task(idx, task)
                await queue.put((idx, result))

            futures = [
                asyncio.create_task(_run_and_enqueue(idx, task))
                for idx, task in enumerate(analysis.edit_tasks, 1)
            ]

            for _ in range(total):
                idx, result = await queue.get()
                if result:
                    count += 1
                    yield _sse({"type": "image", "data": result})

            await asyncio.gather(*futures)

            log.info("[Phase/Images] Tamamlandı: %d/%d görsel", count, total)
            yield _sse({"type": "done", "count": count, "total": total})

        except Exception as e:
            log.error("[Phase/Images] HATA: %s", e, exc_info=True)
            yield _sse({"type": "error", "message": str(e)})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection":    "keep-alive",
            "X-Accel-Buffering": "no",   # nginx buffering'i kapat
        }
    )



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
    _validate_url(req.url)
    try:
        scraped = await _get_or_scrape(req.url, req.max_review_pages)
        return {
            "status": "success",
            "data": {
                "product":       scraped.product,
                "reviews_count": len(scraped.reviews),
                "images":        scraped.images
            }
        }
    except HTTPException:
        raise
    except ProductNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error("scrape_only error for %s: %s", req.url, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
