"""Scraper hızlı test — gerçek Trendyol URL'si ile."""

import sys
sys.path.insert(0, ".")

from app.scraper.http_client import HttpClient
from app.scraper.trendyol import TrendyolScraper

URL = (
    "https://www.trendyol.com/imprime/"
    "pluie-edp-unisex-parfum-50ml-ferah-ciceksi-bergamot-"
    "pembe-biber-yagmur-gul-yasemin-cam-misk-p-962087817"
)

client = HttpClient(timeout=20, rate_limit=0.8, retry_count=2)
scraper = TrendyolScraper(client)

print("Scraping...", flush=True)
result = scraper.scrape(URL, max_review_pages=2)

print(f"\n✅ Ürün ID   : {result.product.product_id}")
print(f"✅ Başlık    : {result.product.title[:80]}")
print(f"✅ Açıklama  : {result.product.description[:120]}...")
print(f"✅ Yorumlar  : {len(result.reviews)} adet")
print(f"✅ Görseller : {len(result.images)} adet")

if result.images:
    print("\nGörsel URL'leri:")
    for img in result.images[:5]:
        print(f"  [{img.position}] {img.url}")
