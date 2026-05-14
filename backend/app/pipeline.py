"""
Esnaf Kopilot — Ana Orkestratör (Pipeline)
Tüm süreci yöneten ana servis.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.scraper.http_client import HttpClient
from app.scraper.trendyol import TrendyolScraper
from app.analyzer.gemini_client import GeminiClient
from app.analyzer.content import ContentAnalyzer
from app.analyzer.image import ImageAnalyzer
from app.models import Product, ScrapedProduct, ContentResult, ImageAnalysis, GeneratedImage


class EsnafKopilotPipeline:
    """
    Ürün analizinin uçtan uca çalıştırıldığı servis.
    """

    def __init__(self):
        self.http_client = HttpClient()
        self.scraper = TrendyolScraper(self.http_client)
        
        self.gemini = GeminiClient()
        self.content_analyzer = ContentAnalyzer(self.gemini)
        self.image_analyzer = ImageAnalyzer(self.gemini)

    def run(self, url: str, max_review_pages: int = 5, output_dir: str = "outputs") -> dict:
        """
        Tüm pipeline'ı çalıştırır: Scrape -> Text Analyze -> Image Analyze -> Image Enhance
        """
        os.makedirs(output_dir, exist_ok=True)
        
        # 1. Scraping
        print(f"[Pipeline] 1. Scraping basliyor: {url}")
        scraped = self.scraper.scrape(url, max_review_pages=max_review_pages)
        print(f"[Pipeline] -> Baslik: {scraped.product.title}, Yorum: {len(scraped.reviews)}, Gorsel: {len(scraped.images)}")

        # 2. İçerik Analizi (SEO / AEO)
        print("[Pipeline] 2. Metin Analizi basliyor...")
        score_result = self.content_analyzer.score(scraped.product, scraped.reviews)
        new_content = self.content_analyzer.generate(scraped.product, scraped.reviews, score_result.total_score)
        print(f"[Pipeline] -> Puan: {score_result.total_score}/100, Yeni Baslik: {new_content.new_title}")

        # 3. Görselleri İndirme
        print("[Pipeline] 3. Gorseller indiriliyor...")
        downloaded_images = self.scraper.download_images(scraped.images, output_dir)
        valid_images = [img for img in downloaded_images if img.local_path]
        print(f"[Pipeline] -> {len(valid_images)} gorsel basariyla indirildi.")

        # 4. Ana Görsel Analizi ve 7 Konsept Düzenlemesi
        print("[Pipeline] 4. Ana gorsel analizi ve 7 konsept uretimi basliyor...")
        
        image_results = []
        
        if not valid_images:
            print("[Pipeline] -> [HATA] İndirilmiş geçerli görsel bulunamadı.")
        else:
            main_image = valid_images[0]  # Kullanıcının yüklediği/seçtiği 1 Ana Görsel
            print(f"  -> Ana Gorsel Secildi: {main_image.local_path}")
            
            try:
                # 4.1. Analiz (Gemini Text/Vision ile 7 prompt üretimi)
                analysis = self.image_analyzer.analyze(scraped.product, main_image)
                print(f"  -> Uretilen Prompt Sayisi: {len(analysis.edit_prompts)}")
                if "analysis_note" in analysis.issues:
                    print(f"  -> Strateji Notu: {analysis.issues['analysis_note']}")
                
                # 4.2. Düzenleme (Gemini Image API ile tek tek üretim)
                enhanced_images = []
                for p_idx, prompt in enumerate(analysis.edit_prompts, 1):
                    print(f"    [{p_idx}/{len(analysis.edit_prompts)}] Duzenleniyor ({prompt.concept_name})...")
                    
                    base_name = os.path.basename(main_image.local_path).split('.')[0]
                    ext = os.path.basename(main_image.local_path).split('.')[-1]
                    concept_safe = "".join(c if c.isalnum() else "_" for c in prompt.concept_name)
                    out_path = os.path.join(output_dir, f"{base_name}_KONSEPT_{p_idx}_{concept_safe}.{ext}")
                    
                    try:
                        enhanced = self.image_analyzer.enhance(main_image, prompt, out_path)
                        enhanced_images.append({
                            "concept": prompt.concept_name,
                            "path": enhanced.local_path
                        })
                        print(f"      -> Basarili: {enhanced.local_path}")
                    except Exception as e:
                        print(f"      -> [HATA] Duzenleme basarisiz: {e}")
                
                image_results.append({
                    "original_url": main_image.url,
                    "original_local": main_image.local_path,
                    "type": "ANA_GORSEL",
                    "enhanced": enhanced_images
                })
                
            except Exception as e:
                print(f"  -> [HATA] Ana gorsel islenirken hata: {e}")

        # 5. Sonuç Dönüşü
        return {
            "product": {
                "id": scraped.product.product_id,
                "original_title": scraped.product.title,
                "original_description": scraped.product.description,
            },
            "content_analysis": {
                "score": score_result.total_score,
                "score_summary": score_result.summary,
                "new_title": new_content.new_title,
                "new_description": new_content.new_description,
                "faq": new_content.faq,
                "keywords": new_content.suggested_keywords
            },
            "images": image_results
        }
