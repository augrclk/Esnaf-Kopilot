from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
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
    
    # outputs klasoru yoksa olustur (main.py de yapiyor ama garanti olsun)
    if not os.path.exists("outputs"):
        os.makedirs("outputs")
    
    try:
        results = pipeline.run(req.url, req.max_review_pages, output_dir=out_dir)
        return {"status": "success", "data": results, "output_dir": out_dir}
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
