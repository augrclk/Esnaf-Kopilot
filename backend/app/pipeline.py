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
from app.analyzer.review import ReviewAnalyzer
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
        self.review_analyzer = ReviewAnalyzer(self.gemini)

    def run(self, url: str, max_review_pages: int = 5, output_dir: str = "outputs") -> dict:
        """
        Tüm pipeline'ı çalıştırır: Scrape -> Text Analyze -> Image Analyze -> Image Enhance
        """
        os.makedirs(output_dir, exist_ok=True)
        
        # 1. Scraping
        print(f"[Pipeline] 1. Scraping basliyor: {url}")
        scraped = self.scraper.scrape(url, max_review_pages=max_review_pages)
        print(f"[Pipeline] -> Baslik: {scraped.product.title}, Yorum: {len(scraped.reviews)}, Gorsel: {len(scraped.images)}")

        # 2. İçerik Analizi (SEO / AEO) + Yorum Analizi (paralel)
        print("[Pipeline] 2. Metin Analizi ve Yorum Analizi basliyor...")
        score_result = self.content_analyzer.score(scraped.product, scraped.reviews)
        new_content = self.content_analyzer.generate(scraped.product, scraped.reviews, score_result.total_score)
        print(f"[Pipeline] -> Puan: {score_result.total_score}/100, Yeni Baslik: {new_content.new_title}")

        print("[Pipeline] 2b. Yorum Analizi basliyor...")
        review_analysis = self.review_analyzer.analyze(scraped.product, scraped.reviews)
        print(f"[Pipeline] -> Yorum Analizi tamamlandi. Begenilen: {len(review_analysis.get('positives', []))}, Sorun: {len(review_analysis.get('negatives', []))}")

        # 3. Görselleri İndirme
        print("[Pipeline] 3. Gorseller indiriliyor...")
        downloaded_images = self.scraper.download_images(scraped.images, output_dir)
        valid_images = [img for img in downloaded_images if img.local_path]
        print(f"[Pipeline] -> {len(valid_images)} gorsel basariyla indirildi.")

        # 4. Görsellerin Analizi ve Yapay Zeka Stratejisinin (Skill) Çalıştırılması
        print("[Pipeline] 4. Sanat Yönetmeni (AI Skill) görsel stratejisi planlıyor...")
        
        image_results = []
        
        if not valid_images:
            print("[Pipeline] -> [HATA] İndirilmiş geçerli görsel bulunamadı.")
        else:
            try:
                # 4.1. Analiz (Gemini ile dinamik strateji kurulumu)
                analysis = self.image_analyzer.plan_strategy(scraped.product, valid_images)
                print(f"  -> Uretilecek Toplam Konsept Sayisi: {len(analysis.edit_tasks)}")
                if "analysis_note" in analysis.issues:
                    print(f"  -> Strateji Notu: {analysis.issues['analysis_note']}")
                
                # 4.2. Düzenleme (Gemini Image API ile PARALEL üretim)
                enhanced_images = []
                
                def _process_image_task(args):
                    p_idx, task = args
                    print(f"    [{p_idx}/{len(analysis.edit_tasks)}] Duzenleniyor ({task.concept_name}) - Kaynak Görsel {task.source_image.position}...")
                    
                    base_name = os.path.basename(task.source_image.local_path).split('.')[0]
                    ext = os.path.basename(task.source_image.local_path).split('.')[-1]
                    concept_safe = "".join(c if c.isalnum() else "_" for c in task.concept_name)
                    out_path = os.path.join(output_dir, f"{base_name}_KONSEPT_{p_idx}_{concept_safe}.{ext}")
                    
                    try:
                        from app.models import ImageEditPrompt
                        # enhance metodunu bozmamak icin gecici ImageEditPrompt objesi
                        dummy_prompt = ImageEditPrompt(concept_name=task.concept_name, prompt=task.prompt)
                        enhanced = self.image_analyzer.enhance(task.source_image, dummy_prompt, out_path)
                        print(f"      -> Basarili: {enhanced.local_path}")
                        return {
                            "concept": task.concept_name,
                            "path": enhanced.local_path
                        }
                    except Exception as e:
                        print(f"      -> [HATA] Duzenleme basarisiz ({task.concept_name}): {e}")
                        return None
                        
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
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
                print(f"  -> [HATA] Görsel stratejisi islenirken hata: {e}")

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
