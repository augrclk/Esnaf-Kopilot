from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any
import os
import concurrent.futures
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

# ── Servisler ───────────────────────────────────────────────────────────────
http_client = HttpClient()
scraper = TrendyolScraper(http_client)
gemini = GeminiClient()
content_analyzer = ContentAnalyzer(gemini)
image_analyzer = ImageAnalyzer(gemini)
review_analyzer = ReviewAnalyzer(gemini)
pipeline = EsnafKopilotPipeline()

# ── In-memory scrape cache (URL → ScrapedProduct) ──────────────────────────
# Aynı URL için birden fazla fazda scraping yapılmasını önler
_scrape_cache: dict = {}

def _get_cached_scrape(url: str, max_review_pages: int = 5):
    if url not in _scrape_cache:
        _scrape_cache[url] = scraper.scrape(url, max_review_pages=max_review_pages)
    return _scrape_cache[url]


# ── Request Modelleri ───────────────────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    url: str
    max_review_pages: int = 5

class ScrapeRequest(BaseModel):
    url: str
    max_review_pages: int = 2

class PhaseRequest(BaseModel):
    url: str
    output_dir: str = ""     # Phase 3'te Phase 2'nin oluşturduğu dizini kullanmak için
    max_review_pages: int = 5

class ChatRequest(BaseModel):
    message: str
    analysis_context: dict


# ── Mevcut tek seferlik endpoint (geriye uyumluluk) ─────────────────────────
@router.get("/health")
def health_check():
    return {"status": "ok", "message": "Esnaf Kopilot API is running"}

@router.post("/analyze")
def analyze_full_pipeline(req: AnalyzeRequest):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = f"outputs/api_{timestamp}"
    os.makedirs(out_dir, exist_ok=True)
    try:
        results = pipeline.run(req.url, req.max_review_pages, output_dir=out_dir)
        return {"status": "success", "data": results, "output_dir": out_dir}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── AŞAMALI (PROGRESSIVE) ENDPOINT'LER ─────────────────────────────────────

@router.post("/phase/scrape")
def phase_scrape(req: PhaseRequest):
    """
    Faz 1: Ürünü scrape et. Hızlıca çalışır (~2-5 saniye).
    Sonucu cache'ler — diğer fazlar aynı URL için tekrar çekmez.
    """
    try:
        scraped = _get_cached_scrape(req.url, req.max_review_pages)

        # Frontend'e göstermek için ilk 5 yorum özeti
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
                    "title": scraped.product.title,
                    "description": scraped.product.description,
                    "url": scraped.product.url,
                    "product_id": scraped.product.product_id,
                },
                "review_count": len(scraped.reviews),
                "review_sample": review_sample,
                "image_count": len(scraped.images),
                "original_image_urls": [img.url for img in scraped.images[:3]],
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/phase/analyze")
def phase_analyze(req: PhaseRequest):
    """
    Faz 2: İçerik analizi (SEO/AEO puanlama + yeni başlık/açıklama) ve yorum analizi.
    Gemini metin API'si kullanır (~30-60 saniye).
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = req.output_dir or f"outputs/api_{timestamp}"
    os.makedirs(out_dir, exist_ok=True)

    try:
        scraped = _get_cached_scrape(req.url, req.max_review_pages)

        score_result = content_analyzer.score(scraped.product, scraped.reviews)
        new_content = content_analyzer.generate(scraped.product, scraped.reviews, score_result.total_score)
        ra = review_analyzer.analyze(scraped.product, scraped.reviews)

        return {
            "status": "success",
            "output_dir": out_dir,
            "data": {
                "product": {
                    "original_title": scraped.product.title,
                    "original_description": scraped.product.description,
                    "url": scraped.product.url,
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
                "review_analysis": ra,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/phase/images")
def phase_images(req: PhaseRequest):
    """
    Faz 3: Görselleri indir ve Gemini Image API ile yeni versiyonlarını oluştur.
    En uzun süren faz (~2-5 dakika, paralel).
    """
    out_dir = req.output_dir or f"outputs/api_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(out_dir, exist_ok=True)

    try:
        scraped = _get_cached_scrape(req.url, req.max_review_pages)

        # Görselleri indir
        downloaded = scraper.download_images(scraped.images, out_dir)
        valid_images = [img for img in downloaded if img.local_path]

        image_results = []

        if not valid_images:
            return {"status": "success", "data": {"images": []}}

        # AI strateji planla
        analysis = image_analyzer.plan_strategy(scraped.product, valid_images)
        strategy_note = analysis.issues.get("analysis_note", "")
        print(f"[Phase/Images] Strateji: {len(analysis.edit_tasks)} konsept üretilecek")

        def _process_task(args):
            idx, task = args
            base_name = os.path.basename(task.source_image.local_path).split('.')[0]
            ext = os.path.basename(task.source_image.local_path).split('.')[-1]
            concept_safe = "".join(c if c.isalnum() else "_" for c in task.concept_name)
            out_path = os.path.join(out_dir, f"{base_name}_KONSEPT_{idx}_{concept_safe}.{ext}")
            try:
                dummy_prompt = ImageEditPrompt(concept_name=task.concept_name, prompt=task.prompt)
                enhanced = image_analyzer.enhance(task.source_image, dummy_prompt, out_path)
                print(f"  ✓ Konsept {idx}: {task.concept_name}")
                return {"concept": task.concept_name, "path": enhanced.local_path}
            except Exception as e:
                print(f"  ✗ Konsept {idx} başarısız: {e}")
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(_process_task, enumerate(analysis.edit_tasks, 1)))

        enhanced = [r for r in results if r]

        return {
            "status": "success",
            "data": {
                "images": [{
                    "strategy_note": strategy_note,
                    "enhanced": enhanced,
                    "original_local": valid_images[0].local_path if valid_images else "",
                }]
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Chat ─────────────────────────────────────────────────────────────────────
@router.post("/chat")
def chat_with_product(req: ChatRequest):
    """Analiz edilmiş ürün hakkında AI asistanına soru sor."""
    try:
        ctx = req.analysis_context
        product = ctx.get("product", {})
        content = ctx.get("content_analysis", {})
        review = ctx.get("review_analysis", {})

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

        answer = gemini.chat_text(system_prompt, req.message)
        return {"status": "success", "answer": answer}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Eski scrape endpoint (geriye uyumluluk) ──────────────────────────────────
@router.post("/scrape")
def scrape_only(req: ScrapeRequest):
    try:
        scraped = scraper.scrape(req.url, max_review_pages=req.max_review_pages)
        return {
            "status": "success",
            "data": {
                "product": scraped.product,
                "reviews_count": len(scraped.reviews),
                "images": scraped.images
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
