import sys
import json
import logging
import os
from datetime import datetime
from app.pipeline import EsnafKopilotPipeline

def main():
    url = "https://www.trendyol.com/tala/hindistan-cevizi-yagi-100-saf-ve-dogal-soguk-sikim-150-ml-p-322236564?boutiqueId=61&merchantId=113082"
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = f"outputs_test_{timestamp}"
    
    print(f"--- ESNAF KOPILOT PIPELINE TESTI ---")
    print(f"Hedef URL: {url}")
    print(f"Cikti Klasoru: {out_dir}\n")
    
    pipeline = EsnafKopilotPipeline()
    
    try:
        results = pipeline.run(url, max_review_pages=1, output_dir=out_dir)
        
        # Sonuclari JSON olarak kaydet
        with open(f"{out_dir}/pipeline_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
            
        print(f"\n✅ PIPELINE BASARIYLA TAMAMLANDI!")
        print(f"Sonuclar JSON olarak kaydedildi: {out_dir}/pipeline_results.json")
    except Exception as e:
        print(f"\n❌ PIPELINE HATASI: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
