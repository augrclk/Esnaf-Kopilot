"""Esnaf Kopilot — Ana Orkestratör (Pipeline)"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor

from app.scraper.http_client import HttpClient
from app.scraper.trendyol import TrendyolScraper
from app.analyzer.gemini_client import GeminiClient
from app.analyzer.content import ContentAnalyzer
from app.analyzer.image import ImageAnalyzer
from app.analyzer.review import ReviewAnalyzer
from app.models import ImageEditPrompt

log = logging.getLogger(__name__)



class EsnafKopilotPipeline:
    """
    Ürün analizinin uçtan uca çalıştırıldığı servis.
    Servisler dışarıdan enjekte edilir — api.py'deki singleton'lar kullanılır.
    """

    def __init__(
        self,
        scraper: TrendyolScraper | None = None,
        content_analyzer: ContentAnalyzer | None = None,
        image_analyzer: ImageAnalyzer | None = None,
        review_analyzer: ReviewAnalyzer | None = None,
    ):
        # Fallback: dependency injection verilmezse kendi oluşturur (geriye uyumluluk)
        if scraper is None:
            http_client = HttpClient()
            scraper = TrendyolScraper(http_client)
        if content_analyzer is None or image_analyzer is None or review_analyzer is None:
            gemini = GeminiClient()
            content_analyzer = content_analyzer or ContentAnalyzer(gemini)
            image_analyzer = image_analyzer or ImageAnalyzer(gemini)
            review_analyzer = review_analyzer or ReviewAnalyzer(gemini)

        self.scraper = scraper
        self.content_analyzer = content_analyzer
        self.image_analyzer = image_analyzer
        self.review_analyzer = review_analyzer

    def run(self, url: str, max_review_pages: int = 5, output_dir: str = "outputs") -> dict:
        """
        Tüm pipeline'ı çalıştırır: Scrape -> Text Analyze -> Image Analyze -> Image Enhance
        """
        os.makedirs(output_dir, exist_ok=True)
        
        # 1. Scraping
        log.info("[Pipeline] 1. Scraping basliyor: %s", url)
        scraped = self.scraper.scrape(url, max_review_pages=max_review_pages)
        log.info("[Pipeline] -> Baslik: %s, Yorum: %d, Gorsel: %d",
                 scraped.product.title, len(scraped.reviews), len(scraped.images))

        # 2. Puanlama + Yorum Analizi
        log.info("[Pipeline] 2. Puanlama ve Yorum Analizi basliyor...")
        score_result = self.content_analyzer.score(scraped.product, scraped.reviews)
        review_analysis = self.review_analyzer.analyze(scraped.product, scraped.reviews)
        log.info("[Pipeline] -> Puan: %d/100, Begenilen: %d, Sorun: %d",
                 score_result.total_score, len(review_analysis.get('positives', [])), len(review_analysis.get('negatives', [])))

        # 2b. İçerik üretimi (score + review_analysis sonuçlarına bağlı)
        log.info("[Pipeline] 2b. Yeni içerik üretiliyor...")
        new_content = self.content_analyzer.generate(scraped.product, scraped.reviews, score_result.total_score, review_analysis)
        log.info("[Pipeline] -> Yeni Baslik: %s", new_content.new_title)

        # 3. Görselleri İndirme
        log.info("[Pipeline] 3. Gorseller indiriliyor...")
        downloaded_images = self.scraper.download_images(scraped.images, output_dir)
        valid_images = [img for img in downloaded_images if img.local_path]
        log.info("[Pipeline] -> %d gorsel basariyla indirildi.", len(valid_images))

        # 4. Görsellerin Analizi ve Yapay Zeka Stratejisinin (Skill) Çalıştırılması
        log.info("[Pipeline] 4. Sanat Yönetmeni (AI Skill) görsel stratejisi planlıyor...")
        
        image_results = []
        
        if not valid_images:
            log.warning("[Pipeline] -> İndirilmiş geçerli görsel bulunamadı.")
        else:
            try:
                # 4.1. Analiz (Gemini ile dinamik strateji kurulumu)
                analysis = self.image_analyzer.plan_strategy(scraped.product, valid_images)
                log.info("  -> Uretilecek Toplam Konsept Sayisi: %d", len(analysis.edit_tasks))
                if "analysis_note" in analysis.issues:
                    log.info("  -> Strateji Notu: %s", analysis.issues['analysis_note'])

                # 4.2. Düzenleme (Gemini Image API ile PARALEL üretim)
                enhanced_images = []

                def _process_image_task(args):
                    p_idx, task = args
                    log.info("    [%d/%d] Duzenleniyor (%s) - Kaynak Görsel %d...",
                             p_idx, len(analysis.edit_tasks), task.concept_name, task.source_image.position)
                    
                    base_name = os.path.basename(task.source_image.local_path).split('.')[0]
                    ext = os.path.basename(task.source_image.local_path).split('.')[-1]
                    concept_safe = "".join(c if c.isalnum() else "_" for c in task.concept_name)
                    out_path = os.path.join(output_dir, f"{base_name}_KONSEPT_{p_idx}_{concept_safe}.{ext}")
                    
                    try:
                        dummy_prompt = ImageEditPrompt(concept_name=task.concept_name, prompt=task.prompt)
                        enhanced = self.image_analyzer.enhance(task.source_image, dummy_prompt, out_path)
                        log.info("      -> Basarili: %s", enhanced.local_path)
                        return {
                            "concept": task.concept_name,
                            "path": enhanced.local_path
                        }
                    except Exception as e:
                        log.error("      -> Duzenleme basarisiz (%s): %s", task.concept_name, e)
                        return None

                with ThreadPoolExecutor(max_workers=8) as executor:
                    args_list = [(p_idx, task) for p_idx, task in enumerate(analysis.edit_tasks, 1)]
                    results = list(executor.map(_process_image_task, args_list))
                    
                # Başarılı olanları listeye ekle
                for res in results:
                    if res:
                        enhanced_images.append(res)
                
                image_results.append({
                    "original_url": valid_images[0].url, # Eski formata uygunluk icin
                    "original_local": valid_images[0].local_path,
                    "type": "DINAMIK_STRATEJI",
                    "strategy_note": analysis.issues.get("analysis_note", ""),
                    "enhanced": enhanced_images
                })
                
            except Exception as e:
                log.error("  -> Görsel stratejisi islenirken hata: %s", e, exc_info=True)

        # 5. Sonuç Dönüşü
        return {
            "product": {
                "id": scraped.product.product_id,
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
            "review_analysis": review_analysis,
            "images": image_results
        }
