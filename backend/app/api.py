"""API Katmanı — FastAPI endpoint'leri."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
import json
import re
import csv
import io
import base64
from pydantic import BaseModel
import asyncio
import logging
import os
from datetime import datetime
from time import monotonic
from typing import Optional

from app.pipeline import EsnafKopilotPipeline
from app.scraper.http_client import HttpClient
from app.scraper.trendyol import TrendyolScraper
from app import test_commerce as tc_store
from app.analyzer.gemini_client import GeminiClient
from app.analyzer.content import ContentAnalyzer
from app.analyzer.image import ImageAnalyzer
from app.analyzer.review import ReviewAnalyzer
from app.analyzer.gift import GiftAdvisor
from app.models import ImageEditPrompt, ProductNotFoundError, UnsupportedPlatformError, Review, Product
from app.config import settings
from app.auth import get_current_user, AuthUser
from app import db

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
pipeline         = EsnafKopilotPipeline(
    scraper=scraper,
    content_analyzer=content_analyzer,
    image_analyzer=image_analyzer,
    review_analyzer=review_analyzer,
)

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
_image_lock = asyncio.Lock()   # _image_last_call erişimi için


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
        # Expired entry'leri temizle (memory leak önleme)
        now = monotonic()
        expired = [k for k, (_, ts) in _scrape_cache.items() if now - ts >= _CACHE_TTL]
        for k in expired:
            del _scrape_cache[k]
            _scrape_tasks.pop(k, None)

        # 1. Geçerli cache var mı?
        entry = _scrape_cache.get(url)
        if entry:
            scraped, ts = entry
            if now - ts < _CACHE_TTL:
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


_OUTPUTS_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "outputs"))


def _make_output_dir(uid: str) -> str:
    """Kullanıcıya özel çıktı dizini oluşturur."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(_OUTPUTS_DIR, uid, ts)
    os.makedirs(path, exist_ok=True)
    return path


from pydantic import Field

# ── Request Modelleri ────────────────────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    url: str
    max_review_pages: int = Field(default=5, ge=1, le=50)

class ScrapeRequest(BaseModel):
    url: str
    max_review_pages: int = Field(default=2, ge=1, le=50)

class PhaseRequest(BaseModel):
    url: str
    max_review_pages: int = Field(default=5, ge=1, le=50)

class ChatRequest(BaseModel):
    message: str
    analysis_context: dict


class ProductFromUrlRequest(BaseModel):
    url: str


class ProductManualRequest(BaseModel):
    platform: str = "Manuel"
    title: str
    description: str = ""


class ProductChatRequest(BaseModel):
    message: str
    product_id: Optional[str] = None


class ConnectStoreRequest(BaseModel):
    name: str
    platform: str
    api_url: str


class ImportProductsRequest(BaseModel):
    product_ids: list[str]


class DeployRequest(BaseModel):
    store_id: str


_IMAGE_INTENT_RE = re.compile(
    r"görsel\s*(üret|yap|oluştur|çek|hazırla|istiyorum|ver|çıkar)"
    r"|resim\s*(üret|yap|oluştur|çek|hazırla|istiyorum|ver|çıkar)"
    r"|fotoğraf\s*(üret|yap|oluştur|çek|hazırla|istiyorum|ver|çıkar)"
    r"|yeni\s*görsel"
    r"|görsel\s*üretimi"
    r"|bana\s*(bir\s*)?(görsel|resim|fotoğraf)",
    re.IGNORECASE,
)


# ── Health ───────────────────────────────────────────────────────────────────
@router.get("/health")
async def health_check():
    return {"status": "ok", "message": "Esnaf Kopilot API is running"}


# ── Tam pipeline (geriye uyumluluk) ─────────────────────────────────────────
@router.post("/analyze")
async def analyze_full_pipeline(
    req: AnalyzeRequest,
    user: AuthUser = Depends(get_current_user),
):
    _validate_url(req.url)
    out_dir = _make_output_dir(user.uid)
    try:
        results = await asyncio.to_thread(
            pipeline.run, req.url, req.max_review_pages, out_dir
        )
        return {"status": "success", "data": results}
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
async def phase_scrape(
    req: PhaseRequest,
    user: AuthUser = Depends(get_current_user),
):
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
async def phase_analyze(
    req: PhaseRequest,
    user: AuthUser = Depends(get_current_user),
):
    """
    FAZ 2 — İçerik + Yorum Analizi (paralel Gemini çağrıları).
    score() + review.analyze() asyncio.gather() ile aynı anda → ardından generate().
    """
    _validate_url(req.url)

    # Kota kontrolü
    await asyncio.to_thread(db.check_quota, user.uid, "analysis")
    await asyncio.to_thread(db.get_or_create_user, user.uid, user.email)

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

        result_data = {
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

        # Kullanım say + sonucu kaydet (hata olsa bile analiz dönülsün)
        try:
            await asyncio.to_thread(db.increment_usage, user.uid, "analysis")
            await asyncio.to_thread(
                db.save_result,
                user.uid,
                req.url,
                scraped.product.title,
                "",  # output_dir artık kullanılmıyor (Storage'a taşındı)
                result_data,
            )
        except Exception as db_err:
            log.warning("[DB] Kayıt hatası (analiz sonucu etkilenmedi): %s", db_err)

        return {
            "status": "success",
            "data":   result_data,
        }
    except HTTPException:
        raise
    except PermissionError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except ProductNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error("phase_analyze error for %s: %s", req.url, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/phase/images")
async def phase_images(
    req: PhaseRequest,
    user: AuthUser = Depends(get_current_user),
):
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
        out_dir = _make_output_dir(user.uid)

        try:
            # Kota kontrolü (stream başında)
            await asyncio.to_thread(db.check_quota, user.uid, "image")

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
                            async with _image_lock:
                                global _image_last_call
                                elapsed = asyncio.get_running_loop().time() - _image_last_call
                                if elapsed < _IMAGE_MIN_INTERVAL:
                                    await asyncio.sleep(_IMAGE_MIN_INTERVAL - elapsed)
                                _image_last_call = asyncio.get_running_loop().time()

                            enhanced = await asyncio.wait_for(
                                asyncio.to_thread(image_analyzer.enhance, task.source_image, dummy, out_path),
                                timeout=TASK_TIMEOUT
                            )
                        log.info("  ✓ Konsept %d: %s", idx, task.concept_name)
                        rel_path = os.path.relpath(enhanced.local_path, _OUTPUTS_DIR)
                        return {"idx": idx, "concept": task.concept_name, "path": rel_path}
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
                try:
                    result = await _enhance_task(idx, task)
                except Exception as exc:
                    log.error("Konsept %d beklenmeyen hata: %s", idx, exc)
                    result = None
                finally:
                    await queue.put((idx, result))

            futures = [
                asyncio.create_task(_run_and_enqueue(idx, task))
                for idx, task in enumerate(analysis.edit_tasks, 1)
            ]

            for _ in range(total):
                idx, result = await queue.get()
                if result:
                    count += 1
                    try:
                        await asyncio.to_thread(db.increment_usage, user.uid, "image")
                    except Exception as db_err:
                        log.warning("[DB] Görsel usage artırma başarısız: %s", db_err)
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
async def chat_with_product(
    req: ChatRequest,
    user: AuthUser = Depends(get_current_user),
):
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
        # ── Görsel üretim intent tespiti ────────────────────────────────────
        if _IMAGE_INTENT_RE.search(req.message):
            product_url = product.get("url", "")
            if not product_url:
                answer = await asyncio.to_thread(gemini.chat_text, system_prompt, req.message)
                return {"status": "success", "answer": answer}

            out_dir = _make_output_dir(user.uid)
            scraped     = await _get_or_scrape(product_url)
            downloaded  = await asyncio.to_thread(scraper.download_images, scraped.images, out_dir)
            valid_imgs  = [img for img in downloaded if img.local_path]

            if not valid_imgs:
                return {"status": "success", "answer": "Ürüne ait indirilebilir görsel bulunamadı."}

            source_img  = valid_imgs[0]
            safe_name   = "".join(c if c.isalnum() else "_" for c in req.message[:40])
            out_path    = os.path.join(out_dir, f"chat_gorsel_{safe_name}.jpg")
            prompt_obj  = ImageEditPrompt(concept_name="Özel Görsel", prompt=req.message)

            async with _IMAGE_SEM:
                async with _image_lock:
                    global _image_last_call
                    elapsed = asyncio.get_running_loop().time() - _image_last_call
                    if elapsed < _IMAGE_MIN_INTERVAL:
                        await asyncio.sleep(_IMAGE_MIN_INTERVAL - elapsed)
                    _image_last_call = asyncio.get_running_loop().time()
                result = await asyncio.wait_for(
                    asyncio.to_thread(image_analyzer.enhance, source_img, prompt_obj, out_path),
                    timeout=150,
                )

            rel_path = os.path.relpath(result.local_path, _OUTPUTS_DIR)

            try:
                await asyncio.to_thread(db.increment_usage, user.uid, "image")
            except Exception as db_err:
                log.warning("[DB] Chat görsel usage artırma başarısız: %s", db_err)

            return {
                "status": "success",
                "answer": "Görsel oluşturuldu!",
                "image_path": rel_path,
            }

        answer = await asyncio.to_thread(gemini.chat_text, system_prompt, req.message)
        return {"status": "success", "answer": answer}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Kullanıcı Endpoint'leri ──────────────────────────────────────────────────

@router.get("/user/me")
async def get_me(user: AuthUser = Depends(get_current_user)):
    """Mevcut kullanıcı bilgisi + tier."""
    profile = await asyncio.to_thread(db.get_or_create_user, user.uid, user.email)
    return {"status": "success", "data": profile}


@router.get("/user/usage")
async def get_usage(user: AuthUser = Depends(get_current_user)):
    """Mevcut ay kullanım istatistikleri + limitler."""
    usage = await asyncio.to_thread(db.get_usage, user.uid)
    return {"status": "success", "data": usage}


@router.get("/user/stats")
async def get_user_stats(user: AuthUser = Depends(get_current_user)):
    stats = await asyncio.to_thread(db.get_stats, user.uid)
    return {"status": "success", "data": stats}


@router.get("/user/results")
async def list_results(
    limit: int = Query(default=20, ge=1, le=100),
    user: AuthUser = Depends(get_current_user),
):
    """Kullanıcının geçmiş analizleri (data hariç)."""
    results = await asyncio.to_thread(db.list_results, user.uid, limit)
    return {"status": "success", "data": results}


@router.get("/user/results/{result_id}")
async def get_result(
    result_id: str,
    user: AuthUser = Depends(get_current_user),
):
    """Tek analiz sonucu (data dahil)."""
    result = await asyncio.to_thread(db.get_result, user.uid, result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Sonuç bulunamadı.")
    return {"status": "success", "data": result}


# ── Ürün Yönetimi ───────────────────────────────────────────────────────────

def _scraped_data_from(scraped) -> dict:
    return {
        "title": scraped.product.title,
        "description": scraped.product.description or "",
        "image_urls": [img.url for img in (scraped.images or [])[:8]],
        "review_count": len(scraped.reviews or []),
        "review_sample": [
            {"rating": r.rating, "text": r.text}
            for r in (scraped.reviews or [])[:10]
        ],
    }


def _analysis_payload(product_doc: dict, score_result, new_content, review_analysis, gift_suggestions) -> dict:
    sd = product_doc.get("scraped_data") or {}
    return {
        "product": {
            "original_title": sd.get("title", ""),
            "original_description": sd.get("description", ""),
            "url": product_doc.get("url", ""),
        },
        "content_analysis": {
            "score": score_result.total_score,
            "score_summary": score_result.summary,
            "categories": [
                {"name": c.name, "score": c.score, "max_score": c.max_score, "notes": c.notes}
                for c in score_result.categories
            ],
            "new_title": new_content.new_title,
            "new_description": new_content.new_description,
            "faq": new_content.faq,
            "keywords": new_content.suggested_keywords,
            "notes": new_content.notes,
        },
        "review_analysis": review_analysis,
        "gift_suggestions": gift_suggestions,
    }


def _product_review_models(product_doc: dict) -> tuple[Product, list[Review]]:
    sd = product_doc.get("scraped_data") or {}
    product = Product(
        url=product_doc.get("url") or "manual",
        product_id=None,
        title=sd.get("title") or product_doc.get("product_title") or "",
        description=sd.get("description", ""),
    )
    reviews = [
        Review(
            review_id=str(i),
            rating=r.get("rating"),
            title=None,
            text=r.get("text", ""),
            date=None,
            user=None,
            variant=None,
            helpful_count=None,
        )
        for i, r in enumerate(sd.get("review_sample") or [])
    ]
    return product, reviews


@router.get("/products")
async def list_products_endpoint(
    limit: int = Query(default=50, ge=1, le=100),
    user: AuthUser = Depends(get_current_user),
):
    return {"status": "success", "data": await asyncio.to_thread(db.list_products, user.uid, limit)}


@router.post("/products/chat")
async def chat_with_products(req: ProductChatRequest, user: AuthUser = Depends(get_current_user)):
    if not req.message.strip():
        raise HTTPException(status_code=422, detail="Mesaj boş olamaz.")

    if req.product_id:
        product = await asyncio.to_thread(db.get_product, user.uid, req.product_id)
        products = [product] if product else []
    else:
        product_refs = await asyncio.to_thread(db.list_products, user.uid, 20)
        products = [
            await asyncio.to_thread(db.get_product, user.uid, p["id"])
            for p in product_refs
        ]

    products = [p for p in products if p]
    if not products:
        raise HTTPException(status_code=422, detail="Önce Ürünlerim sayfasından ürün ekleyin.")

    def _product_summary(p: dict) -> str:
        sd = p.get("scraped_data") or {}
        data = p.get("data") or {}
        ca = data.get("content_analysis") or {}
        review = data.get("review_analysis") or {}
        comments = sd.get("review_sample") or []
        return f"""
Ürün: {sd.get("title") or p.get("product_title") or "Başlıksız"}
Platform: {p.get("platform", "-")}
Durum: {p.get("status", "-")}
Skor: {p.get("score") if p.get("score") is not None else "Henüz analiz edilmedi"}
Açıklama: {(sd.get("description") or "")[:700]}
Önerilen Başlık: {ca.get("new_title", "")}
Analiz Özeti: {ca.get("score_summary", "")}
Yorum Özeti: {review.get("sentiment_summary", "")}
Örnek Yorumlar: {" | ".join((r.get("text", "")[:160] for r in comments[:5]))}
""".strip()

    scope = "tek ürün" if req.product_id else "kullanıcının tüm ekli ürünleri"
    system_prompt = f"""Sen Esnaf Kopilot içinde çalışan e-ticaret AI asistanısın.
Kapsam: {scope}.
Sadece aşağıdaki ürün verilerine dayanarak Türkçe, kısa, net ve uygulanabilir cevap ver.
Kullanıcı analiz istemeden puan uydurma; skor yoksa analiz edilmediğini söyle.

=== ÜRÜNLER ===
{chr(10).join(_product_summary(p) for p in products)}
"""
    try:
        answer = await asyncio.to_thread(gemini.chat_text, system_prompt, req.message.strip())
        try:
            await asyncio.to_thread(db.increment_usage, user.uid, "chat_message")
        except Exception as db_err:
            log.warning("[DB] Chat usage artırma başarısız: %s", db_err)
        return {"status": "success", "answer": answer}
    except Exception as e:
        log.error("chat_with_products error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/products/{product_id}")
async def get_product_endpoint(product_id: str, user: AuthUser = Depends(get_current_user)):
    product = await asyncio.to_thread(db.get_product, user.uid, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Ürün bulunamadı.")
    return {"status": "success", "data": product}


@router.delete("/products/{product_id}")
async def delete_product_endpoint(product_id: str, user: AuthUser = Depends(get_current_user)):
    product = await asyncio.to_thread(db.get_product, user.uid, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Ürün bulunamadı.")
    await asyncio.to_thread(db.delete_product, user.uid, product_id)
    return {"status": "success"}


@router.post("/products/from-url")
async def add_product_from_url(req: ProductFromUrlRequest, user: AuthUser = Depends(get_current_user)):
    _validate_url(req.url)
    product_id = await asyncio.to_thread(db.create_product, user.uid, req.url, "", "Trendyol", "draft")
    try:
        scraped = await asyncio.to_thread(scraper.scrape, req.url, max_review_pages=2)
        scraped_data = _scraped_data_from(scraped)
        await asyncio.to_thread(db.update_product_scraped, user.uid, product_id, scraped_data, "inspected")
        return {"status": "success", "product_id": product_id, "scraped_data": scraped_data}
    except Exception as e:
        await asyncio.to_thread(db.delete_product, user.uid, product_id)
        log.error("add_product_from_url error: %s", e, exc_info=True)
        raise HTTPException(status_code=422, detail=f"Ürün çekilemedi: {str(e)}")


@router.post("/products/manual")
async def add_product_manual(req: ProductManualRequest, user: AuthUser = Depends(get_current_user)):
    if not req.title.strip():
        raise HTTPException(status_code=422, detail="Ürün başlığı boş olamaz.")
    platform = req.platform if req.platform in {"Trendyol", "Hepsiburada", "N11", "Manuel"} else "Manuel"
    product_id = await asyncio.to_thread(db.create_product, user.uid, "", req.title.strip(), platform, "draft")
    scraped_data = {
        "title": req.title.strip(),
        "description": req.description.strip(),
        "image_urls": [],
        "review_count": 0,
        "review_sample": [],
    }
    await asyncio.to_thread(db.update_product_scraped, user.uid, product_id, scraped_data, "draft")
    return {"status": "success", "product_id": product_id, "scraped_data": scraped_data}


@router.post("/products/{product_id}/analyze")
async def analyze_product(product_id: str, user: AuthUser = Depends(get_current_user)):
    product_doc = await asyncio.to_thread(db.get_product, user.uid, product_id)
    if product_doc is None:
        raise HTTPException(status_code=404, detail="Ürün bulunamadı.")
    if product_doc.get("data") and product_doc.get("score") is not None:
        return {"status": "success", "data": product_doc["data"], "product_id": product_id, "cached": True}

    try:
        await asyncio.to_thread(db.check_quota, user.uid, "analysis")
    except PermissionError as e:
        raise HTTPException(status_code=429, detail=str(e))

    product_obj, reviews = _product_review_models(product_doc)
    try:
        score_result, ra = await asyncio.gather(
            asyncio.to_thread(content_analyzer.score, product_obj, reviews),
            asyncio.to_thread(review_analyzer.analyze, product_obj, reviews),
        )
        new_content, gift_suggestions = await asyncio.gather(
            asyncio.to_thread(content_analyzer.generate, product_obj, reviews, score_result.total_score, ra),
            asyncio.to_thread(gift_advisor.suggest, product_obj, ra),
        )
    except Exception as e:
        log.error("analyze_product error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    result_data = _analysis_payload(product_doc, score_result, new_content, ra, gift_suggestions)
    await asyncio.to_thread(db.update_product_analyzed, user.uid, product_id, result_data, score_result.total_score)
    await asyncio.to_thread(db.increment_usage, user.uid, "analysis")
    await asyncio.to_thread(db.save_result, user.uid, product_doc.get("url") or "manual", product_obj.title, "", result_data)
    return {"status": "success", "data": result_data, "product_id": product_id, "cached": False}


@router.get("/products/{product_id}/improve")
async def improve_product_stream(product_id: str, user: AuthUser = Depends(get_current_user)):
    def _sse(event: dict) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    async def _stream():
        product_doc = await asyncio.to_thread(db.get_product, user.uid, product_id)
        if product_doc is None:
            yield _sse({"type": "error", "message": "Ürün bulunamadı."})
            return

        if product_doc.get("status") == "improved":
            yield _sse({"type": "done", "count": len(product_doc.get("image_paths") or []), "cached": True})
            return

        if not product_doc.get("data"):
            yield _sse({"type": "step", "step": 1, "message": "Analiz hazırlanıyor..."})
            try:
                await analyze_product(product_id, user)
            except HTTPException as e:
                yield _sse({"type": "error", "message": str(e.detail)})
                return
            product_doc = await asyncio.to_thread(db.get_product, user.uid, product_id)
            yield _sse({"type": "analyze_done", "data": {"score": product_doc.get("score")}})

        url = product_doc.get("url") or ""
        if not url or url == "manual":
            await asyncio.to_thread(db.update_product_improved, user.uid, product_id, [])
            yield _sse({"type": "done", "count": 0})
            return

        try:
            await asyncio.to_thread(db.check_quota, user.uid, "image")
        except PermissionError as e:
            yield _sse({"type": "error", "message": str(e)})
            return

        yield _sse({"type": "step", "step": 2, "message": "Görseller hazırlanıyor..."})
        try:
            scraped = await asyncio.to_thread(scraper.scrape, url, max_review_pages=1)
            out_dir = _make_output_dir(user.uid)
            downloaded = await asyncio.to_thread(scraper.download_images, scraped.images[:3], out_dir)
            valid_images = [img for img in downloaded if img.local_path]
            if not valid_images:
                await asyncio.to_thread(db.update_product_improved, user.uid, product_id, [])
                yield _sse({"type": "done", "count": 0})
                return

            analysis = await asyncio.to_thread(image_analyzer.plan_strategy, scraped.product, valid_images)
            yield _sse({"type": "start", "total": len(analysis.edit_tasks)})
            paths = []
            for idx, task in enumerate(analysis.edit_tasks, 1):
                safe_name = "".join(c if c.isalnum() else "_" for c in task.concept_name)
                out_path = os.path.join(out_dir, f"product_{product_id}_{idx}_{safe_name}.jpg")
                prompt_obj = ImageEditPrompt(concept_name=task.concept_name, prompt=task.prompt)
                async with _IMAGE_SEM:
                    enhanced = await asyncio.to_thread(image_analyzer.enhance, task.source_image, prompt_obj, out_path)
                rel_path = os.path.relpath(enhanced.local_path, _OUTPUTS_DIR)
                paths.append(rel_path)
                await asyncio.to_thread(db.increment_usage, user.uid, "image")
                yield _sse({"type": "image", "data": {"idx": idx, "concept": task.concept_name, "path": rel_path}})

            await asyncio.to_thread(db.update_product_improved, user.uid, product_id, paths)
            yield _sse({"type": "done", "count": len(paths)})
        except Exception as e:
            log.error("improve_product error: %s", e, exc_info=True)
            yield _sse({"type": "error", "message": str(e)})

    return StreamingResponse(_stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })


# ── Pazaryeri API Anahtarları ─────────────────────────────────────────────────

SUPPORTED_PLATFORMS = {"trendyol", "hepsiburada", "n11", "amazon", "ebay", "gittigidiyor"}

class ApiKeyRequest(BaseModel):
    platform: str
    api_key: str

@router.get("/user/api-keys")
async def get_api_keys(user: AuthUser = Depends(get_current_user)):
    keys = await asyncio.to_thread(db.list_api_keys, user.uid)
    return {"status": "success", "data": keys}

@router.post("/user/api-keys")
async def save_api_key(req: ApiKeyRequest, user: AuthUser = Depends(get_current_user)):
    if req.platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(status_code=422, detail=f"Desteklenmeyen platform: {req.platform}")
    if not req.api_key.strip():
        raise HTTPException(status_code=422, detail="API anahtarı boş olamaz.")
    await asyncio.to_thread(db.save_api_key, user.uid, req.platform, req.api_key.strip())
    return {"status": "success"}

@router.delete("/user/api-keys/{platform}")
async def delete_api_key(platform: str, user: AuthUser = Depends(get_current_user)):
    if platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(status_code=422, detail=f"Desteklenmeyen platform: {platform}")
    await asyncio.to_thread(db.delete_api_key, user.uid, platform)
    return {"status": "success"}


# ── Manuel Ürün Analizi ───────────────────────────────────────────────────────

class ManualAnalyzeRequest(BaseModel):
    title: str
    description: str = ""
    reviews_csv: str = ""  # raw CSV text, optional

class ManualImagesRequest(BaseModel):
    title: str
    description: str = ""
    images_b64: list[str] = []  # list of base64-encoded images, max 5


def _parse_reviews_csv(csv_text: str) -> list:
    """CSV metnini Review listesine çevirir. Beklenen sütunlar: rating, text"""
    reviews = []
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        for i, row in enumerate(reader):
            if i >= 50:  # max 50 reviews
                break
            text = (
                row.get("text") or row.get("yorum") or row.get("comment") or
                row.get("review") or row.get("içerik") or ""
            ).strip()
            rating_raw = row.get("rating") or row.get("puan") or row.get("score") or ""
            try:
                rating = float(rating_raw)
            except (ValueError, TypeError):
                rating = None
            if text:
                reviews.append(Review(
                    review_id=str(i),
                    rating=rating,
                    title=None,
                    text=text[:500],
                    date=None,
                    user=None,
                    variant=None,
                    helpful_count=None,
                ))
    except Exception as e:
        log.warning("[ManualAnalyze] CSV parse hatası: %s", e)
    return reviews


@router.post("/phase/manual-analyze")
async def phase_manual_analyze(
    req: ManualAnalyzeRequest,
    user: AuthUser = Depends(get_current_user),
):
    """
    Manuel ürün analizi (URL olmadan).
    Kullanıcı başlık + açıklama + opsiyonel CSV yorumları girer.
    Phase/analyze ile aynı çıktı formatını döner.
    """
    if not req.title.strip():
        raise HTTPException(status_code=422, detail="Ürün başlığı boş olamaz.")

    await asyncio.to_thread(db.check_quota, user.uid, "analysis")
    await asyncio.to_thread(db.get_or_create_user, user.uid, user.email)

    product = Product(
        url="manual",
        product_id=None,
        title=req.title.strip(),
        description=req.description.strip(),
    )
    reviews = _parse_reviews_csv(req.reviews_csv) if req.reviews_csv.strip() else []

    try:
        score_result, ra = await asyncio.gather(
            asyncio.to_thread(content_analyzer.score, product, reviews),
            asyncio.to_thread(review_analyzer.analyze, product, reviews),
        )
        new_content, gift_suggestions = await asyncio.gather(
            asyncio.to_thread(content_analyzer.generate, product, reviews, score_result.total_score, ra),
            asyncio.to_thread(gift_advisor.suggest, product, ra),
        )

        result_data = {
            "product": {
                "original_title":       product.title,
                "original_description": product.description,
                "url":                  "manual",
            },
            "content_analysis": {
                "score":         score_result.total_score,
                "score_summary": score_result.summary,
                "categories": [
                    {"name": c.name, "score": c.score, "max_score": c.max_score, "notes": c.notes}
                    for c in score_result.categories
                ],
                "new_title":       new_content.new_title,
                "new_description": new_content.new_description,
                "faq":             new_content.faq,
                "keywords":        new_content.suggested_keywords,
                "notes":           new_content.notes,
            },
            "review_analysis":  ra,
            "gift_suggestions": gift_suggestions,
            "review_count":     len(reviews),
        }

        try:
            await asyncio.to_thread(db.increment_usage, user.uid, "analysis")
            await asyncio.to_thread(db.save_result, user.uid, "manual", product.title, "", result_data)
        except Exception as db_err:
            log.warning("[DB] Manuel analiz kayıt hatası: %s", db_err)

        return {"status": "success", "data": result_data}

    except PermissionError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        log.error("phase_manual_analyze error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/phase/manual-images")
async def phase_manual_images(
    req: ManualImagesRequest,
    user: AuthUser = Depends(get_current_user),
):
    """
    Manuel görsel analizi — SSE stream.
    Base64 görseller alır, tempfile'a yazar, image_analyzer ile işler.
    phase/images ile aynı event formatını döner.
    """
    def _sse(event: dict) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    async def _stream():
        if not req.images_b64:
            yield _sse({"type": "done", "count": 0, "total": 0})
            return

        try:
            await asyncio.to_thread(db.check_quota, user.uid, "image")
        except PermissionError as e:
            yield _sse({"type": "error", "message": str(e)})
            return

        product = Product(url="manual", product_id=None, title=req.title, description=req.description)
        out_dir = _make_output_dir(user.uid)

        # Decode base64 images → temp files → ProductImage list
        from app.models import ProductImage
        valid_images = []
        for idx, b64 in enumerate(req.images_b64[:5]):  # max 5 images
            try:
                # Strip data URL prefix if present
                if "," in b64:
                    b64 = b64.split(",", 1)[1]
                img_bytes = base64.b64decode(b64)
                ext = "jpg"
                # Detect PNG from magic bytes
                if img_bytes[:4] == b"\x89PNG":
                    ext = "png"
                path = os.path.join(out_dir, f"manual_img_{idx}.{ext}")
                with open(path, "wb") as f:
                    f.write(img_bytes)
                valid_images.append(ProductImage(
                    url=f"manual_{idx}",
                    image_id=f"manual_{idx}",
                    position=idx,
                    local_path=path,
                ))
            except Exception as e:
                log.warning("[ManualImages] Görsel %d decode hatası: %s", idx, e)

        if not valid_images:
            yield _sse({"type": "done", "count": 0, "total": 0})
            return

        try:
            analysis = await asyncio.to_thread(image_analyzer.plan_strategy, product, valid_images)
            strategy_note = analysis.issues.get("analysis_note", "")
            total = len(analysis.edit_tasks)
            yield _sse({"type": "start", "total": total, "strategy_note": strategy_note})

            TASK_TIMEOUT = 120
            MAX_ATTEMPTS = 4
            RETRY_DELAYS = [10, 20, 40]
            queue = asyncio.Queue()
            count = 0

            async def _enhance_task(idx: int, task):
                safe_name = "".join(c if c.isalnum() else "_" for c in task.concept_name)
                out_path = os.path.join(out_dir, f"manual_KONSEPT_{idx}_{safe_name}.jpg")
                dummy = ImageEditPrompt(concept_name=task.concept_name, prompt=task.prompt)
                for attempt in range(MAX_ATTEMPTS):
                    try:
                        async with _IMAGE_SEM:
                            async with _image_lock:
                                global _image_last_call
                                elapsed = asyncio.get_running_loop().time() - _image_last_call
                                if elapsed < _IMAGE_MIN_INTERVAL:
                                    await asyncio.sleep(_IMAGE_MIN_INTERVAL - elapsed)
                                _image_last_call = asyncio.get_running_loop().time()
                            enhanced = await asyncio.wait_for(
                                asyncio.to_thread(image_analyzer.enhance, task.source_image, dummy, out_path),
                                timeout=TASK_TIMEOUT
                            )
                        rel_path = os.path.relpath(enhanced.local_path, _OUTPUTS_DIR)
                        return {"idx": idx, "concept": task.concept_name, "path": rel_path}
                    except asyncio.TimeoutError:
                        log.warning("Manuel konsept %d timeout", idx)
                    except Exception as e:
                        err = str(e)
                        if "429" in err or "RESOURCE_EXHAUSTED" in err or "503" in err:
                            if attempt < MAX_ATTEMPTS - 1:
                                await asyncio.sleep(RETRY_DELAYS[attempt])
                                continue
                        log.error("Manuel konsept %d hata: %s", idx, e)
                    break
                return None

            async def _run_enqueue(idx, task):
                try:
                    result = await _enhance_task(idx, task)
                except Exception as exc:
                    log.error("Manuel konsept %d beklenmeyen: %s", idx, exc)
                    result = None
                finally:
                    await queue.put((idx, result))

            futures = [
                asyncio.create_task(_run_enqueue(idx, task))
                for idx, task in enumerate(analysis.edit_tasks, 1)
            ]

            for _ in range(total):
                idx, result = await queue.get()
                if result:
                    count += 1
                    try:
                        await asyncio.to_thread(db.increment_usage, user.uid, "image")
                    except Exception:
                        pass
                    yield _sse({"type": "image", "data": result})

            await asyncio.gather(*futures)
            yield _sse({"type": "done", "count": count, "total": total})

        except Exception as e:
            log.error("[ManualImages] HATA: %s", e, exc_info=True)
            yield _sse({"type": "error", "message": str(e)})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "Connection":        "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ── Admin Endpoint'leri ──────────────────────────────────────────────────────

class SetTierRequest(BaseModel):
    uid:  str
    tier: str  # "free" | "pro" | "admin"


def _require_admin(user: AuthUser) -> None:
    """Kullanıcı admin değilse 403 fırlatır."""
    profile = db.get_or_create_user(user.uid, user.email)
    if profile.get("tier") != "admin":
        raise HTTPException(status_code=403, detail="Admin yetkisi gerekli.")


@router.post("/admin/set-tier")
async def admin_set_tier(
    req: SetTierRequest,
    user: AuthUser = Depends(get_current_user),
):
    """
    Admin: hedef kullanıcının tier'ını değiştirir.
    Sadece tier=admin olan kullanıcılar çağırabilir.
    """
    await asyncio.to_thread(_require_admin, user)
    try:
        await asyncio.to_thread(db.set_user_tier, req.uid, req.tier)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"status": "success", "uid": req.uid, "new_tier": req.tier}


@router.get("/admin/users")
async def admin_list_users(
    user: AuthUser = Depends(get_current_user),
):
    """
    Admin: tüm kullanıcıları listeler (tier + email).
    """
    await asyncio.to_thread(_require_admin, user)
    firestore_db = db._db()
    docs = firestore_db.collection("users").stream()
    users = []
    for doc in docs:
        d = doc.to_dict()
        if hasattr(d.get("created_at"), "isoformat"):
            d["created_at"] = d["created_at"].isoformat()
        d.pop("limits", None)  # limits tier'dan türetiliyor, gereksiz
        users.append(d)
    return {"status": "success", "data": users}


# ── Eski scrape endpoint (geriye uyumluluk) ──────────────────────────────────
@router.post("/scrape")
async def scrape_only(
    req: ScrapeRequest,
    user: AuthUser = Depends(get_current_user),
):
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


# ── Test Commerce (mock mağaza) ───────────────────────────────────────────────

@router.get("/test-commerce/products")
async def tc_list_products():
    """Test Commerce — ürün listesi. Auth gerekmez (herkese açık mock API)."""
    return {"status": "success", "data": tc_store.get_products()}


@router.get("/test-commerce/products/{product_id}")
async def tc_get_product(product_id: str):
    product = tc_store.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Ürün bulunamadı.")
    return {"status": "success", "data": product}


@router.put("/test-commerce/products/{product_id}")
async def tc_update_product(product_id: str, body: dict):
    updated = tc_store.update_product(
        product_id,
        title=body.get("title"),
        description=body.get("description"),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Ürün bulunamadı.")
    return {"status": "success", "data": updated}


# ── Bağlı Mağazalar ───────────────────────────────────────────────────────────

@router.get("/user/stores")
async def list_connected_stores(user: AuthUser = Depends(get_current_user)):
    stores = await asyncio.to_thread(db.list_stores, user.uid)
    return {"status": "success", "data": stores}


@router.post("/user/stores")
async def connect_store(req: ConnectStoreRequest, user: AuthUser = Depends(get_current_user)):
    if not req.api_url.strip():
        raise HTTPException(status_code=422, detail="API URL boş olamaz.")
    store_id = await asyncio.to_thread(
        db.save_store, user.uid, req.name.strip(), req.platform.strip(), req.api_url.strip()
    )
    return {"status": "success", "store_id": store_id}


@router.delete("/user/stores/{store_id}")
async def disconnect_store(store_id: str, user: AuthUser = Depends(get_current_user)):
    await asyncio.to_thread(db.delete_store, user.uid, store_id)
    return {"status": "success"}


@router.get("/stores/{store_id}/products")
async def proxy_store_products(store_id: str, user: AuthUser = Depends(get_current_user)):
    """Bağlı mağazanın ürün listesini proxy'ler."""
    import httpx
    store = await asyncio.to_thread(db.get_store, user.uid, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Mağaza bulunamadı.")
    api_url = store["api_url"].rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{api_url}/products")
            resp.raise_for_status()
            return {"status": "success", "data": resp.json().get("data", resp.json())}
    except Exception as e:
        log.error("proxy_store_products error: %s", e)
        raise HTTPException(status_code=502, detail=f"Mağazaya bağlanılamadı: {str(e)}")


@router.post("/stores/{store_id}/import")
async def import_from_store(
    store_id: str,
    req: ImportProductsRequest,
    user: AuthUser = Depends(get_current_user),
):
    """Seçilen ürünleri mağazadan içe aktarır, draft ürün olarak oluşturur."""
    import httpx
    store = await asyncio.to_thread(db.get_store, user.uid, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Mağaza bulunamadı.")
    api_url = store["api_url"].rstrip("/")
    platform_name = store.get("name", store.get("platform", "Mağaza"))
    created = []

    async with httpx.AsyncClient(timeout=10.0) as client:
        for pid in req.product_ids:
            try:
                resp = await client.get(f"{api_url}/products/{pid}")
                resp.raise_for_status()
                item = resp.json().get("data", {})
                title = item.get("title", "Başlıksız ürün")
                description = item.get("description", "")
                images = item.get("images") or []
                reviews_raw = item.get("reviews") or []

                product_id = await asyncio.to_thread(
                    db.create_product, user.uid, "", title, platform_name, "inspected"
                )
                scraped_data = {
                    "title":        title,
                    "description":  description,
                    "image_urls":   images[:8],
                    "review_count": len(reviews_raw),
                    "review_sample": [
                        {"rating": r.get("rating"), "text": r.get("text", "")}
                        for r in reviews_raw[:10]
                    ],
                }
                await asyncio.to_thread(
                    db.update_product_scraped, user.uid, product_id, scraped_data, "inspected"
                )
                await asyncio.to_thread(
                    db.update_product_source, user.uid, product_id, store_id, pid
                )
                created.append({"product_id": product_id, "title": title})
            except Exception as e:
                log.error("import_from_store error pid=%s: %s", pid, e)

    return {"status": "success", "imported": created}


@router.post("/products/{product_id}/deploy")
async def deploy_to_store(
    product_id: str,
    req: DeployRequest,
    user: AuthUser = Depends(get_current_user),
):
    """İyileştirilmiş içeriği bağlı mağazaya gönderir."""
    import httpx
    product = await asyncio.to_thread(db.get_product, user.uid, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Ürün bulunamadı.")

    store = await asyncio.to_thread(db.get_store, user.uid, req.store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Mağaza bulunamadı.")

    ca = (product.get("data") or {}).get("content_analysis") or {}
    new_title = ca.get("new_title") or ""
    new_desc  = ca.get("new_description") or ""
    if not new_title and not new_desc:
        raise HTTPException(status_code=422, detail="Ürün henüz analiz edilmemiş, deploy edilecek içerik yok.")

    store_product_id = product.get("source_product_id")
    if not store_product_id:
        raise HTTPException(status_code=422, detail="Bu ürünün kaynak mağaza ürün ID'si bilinmiyor.")

    api_url = store["api_url"].rstrip("/")
    payload = {}
    if new_title:
        payload["title"] = new_title
    if new_desc:
        payload["description"] = new_desc

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.put(f"{api_url}/products/{store_product_id}", json=payload)
            resp.raise_for_status()
        return {"status": "success", "deployed": payload}
    except Exception as e:
        log.error("deploy_to_store error: %s", e)
        raise HTTPException(status_code=502, detail=f"Mağazaya gönderilemedi: {str(e)}")
