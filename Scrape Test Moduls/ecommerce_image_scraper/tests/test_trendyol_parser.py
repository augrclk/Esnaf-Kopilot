from pathlib import Path

from ecommerce_image_scraper.trendyol import TrendyolAdapter
from ecommerce_image_scraper.types import ScraperConfig


def test_trendyol_parser_extracts_and_deduplicates_product_images() -> None:
    html = _fixture("trendyol_product.html")
    adapter = TrendyolAdapter(
        client=None,
        config=ScraperConfig(),
    )  # type: ignore[arg-type]

    images = adapter.parse_product_images(
        "https://www.trendyol.com/marka/urun-p-123",
        html,
    )

    assert [image.position for image in images] == [1, 2, 3, 4, 5]
    assert images[0].image_url == (
        "https://cdn.dsmcdn.com/ty1/product/media/images/20260513/1/test-1.jpg"
    )
    assert images[0].source == "json_ld"
    assert images[0].product_id == "123"
    assert images[1].image_url.endswith("/test-2.webp")
    assert images[2].image_url.endswith("/test-3.png")
    assert images[3].image_url.endswith("/test-4.jpg")
    assert images[4].image_url.endswith("/test-5.jpg")


def test_trendyol_parser_ignores_non_product_assets() -> None:
    html = """
    <html>
      <head>
        <meta property="og:image" content="https://cdn.dsmcdn.com/assets/logo.png">
      </head>
      <body>
        <img src="https://cdn.dsmcdn.com/web/icon.png">
        <img src="https://cdn.dsmcdn.com/marketing/datascience/automation/banner.jpg">
        <img src="https://cdn.dsmcdn.com/ty1/campaign/boutique/banner.webp">
        <img src="https://cdn.dsmcdn.com/ty1/product/media/images/1/product.jpg">
      </body>
    </html>
    """
    adapter = TrendyolAdapter(
        client=None,
        config=ScraperConfig(),
    )  # type: ignore[arg-type]

    images = adapter.parse_product_images(
        "https://www.trendyol.com/marka/urun-p-123",
        html,
    )

    assert len(images) == 1
    assert images[0].image_url.endswith("/product.jpg")


def test_trendyol_parser_accepts_structured_qc_enrichment_images() -> None:
    html = """
    <html>
      <head>
        <meta
          property="og:image"
          content="https://cdn.dsmcdn.com/mnresize/620/920/ty1717/prod/QC_ENRICHMENT/20250801/12/main/1_org_zoom.jpg"
        >
        <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "QC Ürün",
            "image": {
              "type": "ImageObject",
              "contentUrl": [
                "https://cdn.dsmcdn.com/ty1717/prod/QC_ENRICHMENT/20250801/12/a/1_org_zoom.jpg",
                "https://cdn.dsmcdn.com/ty1721/prod/QC_ENRICHMENT/20250801/12/b/1_org_zoom.jpg"
              ]
            }
          }
        </script>
      </head>
      <body>
        <img src="https://cdn.dsmcdn.com/marketing/banner.jpg">
      </body>
    </html>
    """
    adapter = TrendyolAdapter(
        client=None,
        config=ScraperConfig(),
    )  # type: ignore[arg-type]

    images = adapter.parse_product_images(
        "https://www.trendyol.com/marka/urun-p-962087817",
        html,
    )

    assert len(images) == 3
    assert all("/prod/QC_ENRICHMENT/" in image.image_url for image in images)
    assert images[0].source == "json_ld"
    assert images[2].source == "meta"


def _fixture(name: str) -> str:
    return (Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8")
