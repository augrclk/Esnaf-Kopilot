"""API Katmanı — FastAPI endpoint'leri."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
import json
import re
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


def _safe_output_dir(user_dir: str) -> str:
    """
    output_dir path traversal koruması.
    Kullanıcıdan gelen dizin adını 'outputs/' altına kilitler.
    """
    if not user_dir:
        return f"outputs/api_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # ".." ve mutlak path'leri engelle
    base = os.path.basename(user_dir.rstrip("/"))
    if not base or base.startswith("."):
        base = f"api_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    safe = os.path.join("outputs", base)
    # Resolve sonrası outputs/ içinde olduğunu doğrula
    resolved = os.path.realpath(safe)
    outputs_root = os.path.realpath("outputs")
    if not resolved.startswith(outputs_root):
        raise HTTPException(status_code=422, detail="Geçersiz output_dir.")
    return safe


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
    output_dir: str = ""
    max_review_pages: int = Field(default=5, ge=1, le=50)

class ChatRequest(BaseModel):
    message: str
    analysis_context: dict
    output_dir: str = ""


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

    out_dir = _safe_output_dir(req.output_dir)
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
                out_dir,
                result_data,
            )
        except Exception as db_err:
            log.warning("[DB] Kayıt hatası (analiz sonucu etkilenmedi): %s", db_err)

        return {
            "status":     "success",
            "output_dir": out_dir,
            "data":       result_data,
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
        out_dir = _safe_output_dir(req.output_dir)
        os.makedirs(out_dir, exist_ok=True)

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
                            # İstekler arası minimum bekleme — 429 baskısını önler
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

            out_dir = _safe_output_dir(req.output_dir)
            os.makedirs(out_dir, exist_ok=True)

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

            try:
                await asyncio.to_thread(db.increment_usage, user.uid, "image")
            except Exception as db_err:
                log.warning("[DB] Chat görsel usage artırma başarısız: %s", db_err)

            return {
                "status": "success",
                "answer": "Görsel oluşturuldu!",
                "image_path": result.local_path,
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
