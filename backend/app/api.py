from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Any
import os
from datetime import datetime

from app.pipeline import EsnafKopilotPipeline
from app.scraper.http_client import HttpClient
from app.scraper.trendyol import TrendyolScraper
from app.analyzer.gemini_client import GeminiClient
from app.analyzer.content import ContentAnalyzer
from app.analyzer.image import ImageAnalyzer

router = APIRouter()

# Servisleri başlat
http_client = HttpClient()
scraper = TrendyolScraper(http_client)
gemini = GeminiClient()
content_analyzer = ContentAnalyzer(gemini)
image_analyzer = ImageAnalyzer(gemini)
pipeline = EsnafKopilotPipeline()

# Modeller
class AnalyzeRequest(BaseModel):
    url: str
    max_review_pages: int = 5

class ScrapeRequest(BaseModel):
    url: str
    max_review_pages: int = 2

class ChatRequest(BaseModel):
    message: str
    analysis_context: dict  # pipeline.run() çıktısının data kısmı

@router.get("/health")
def health_check():
    """API ayakta mı kontrolü."""
    return {"status": "ok", "message": "Esnaf Kopilot API is running"}

@router.post("/analyze")
def analyze_full_pipeline(req: AnalyzeRequest):
    """
    Uçtan uca tüm süreci (Scrape -> Text -> Image) çalıştırır.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = f"outputs/api_{timestamp}"
    
    if not os.path.exists("outputs"):
        os.makedirs("outputs")
    
    try:
        results = pipeline.run(req.url, req.max_review_pages, output_dir=out_dir)
        return {"status": "success", "data": results, "output_dir": out_dir}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat")
def chat_with_product(req: ChatRequest):
    """
    Analiz edilmiş ürün hakkında AI asistanına soru sor.
    Mevcut analiz sonucu context olarak kullanılır.
    """
    try:
        ctx = req.analysis_context
        product = ctx.get("product", {})
        content = ctx.get("content_analysis", {})
        review = ctx.get("review_analysis", {})

        # Yorum analizinden önemli noktaları özet olarak hazırla
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
Önerilen Açıklama: {content.get("new_description", "")[:500]}
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

        response = gemini.chat_text(system_prompt, req.message)
        answer = response if isinstance(response, str) else str(response)

        return {"status": "success", "answer": answer}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/scrape")
def scrape_only(req: ScrapeRequest):
    """
    Sadece ürünü, yorumları ve görselleri çeker. Analiz yapmaz.
    """
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

