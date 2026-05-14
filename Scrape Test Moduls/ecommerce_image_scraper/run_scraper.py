from ecommerce_image_scraper import scrape_product_images_to_files

result = scrape_product_images_to_files(
    url="https://www.trendyol.com/imprime/pluie-edp-unisex-parfum-50ml-ferah-ciceksi-bergamot-pembe-biber-yagmur-gul-yasemin-cam-misk-p-962087817",
    output_dir="outputs/product_2",
)

print(result)
