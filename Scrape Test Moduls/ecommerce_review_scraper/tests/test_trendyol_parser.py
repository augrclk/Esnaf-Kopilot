from pathlib import Path
from typing import Any

from ecommerce_scraper.http_client import HttpResponse
from ecommerce_scraper.trendyol import TrendyolAdapter
from ecommerce_scraper.types import ScraperConfig, ScraperHttpError


def test_trendyol_product_parser_reads_json_ld() -> None:
    html = _fixture("trendyol_product.html")
    adapter = TrendyolAdapter(
        client=None,
        config=ScraperConfig(),
    )  # type: ignore[arg-type]

    product = adapter.parse_product_html(
        "https://www.trendyol.com/marka/urun-p-123",
        html,
    )

    assert product.platform == "trendyol"
    assert product.product_id == "123"
    assert product.title == "Trendyol Test Ürünü"
    assert product.description == (
        "Thalia Boutique Volare Eau De Parfüm Unisex 50ml "
        "Butik parfüm serisinde, sadeliği bilgelikle kucakladık. "
        "Thalia Volare, cesaret kanatlarını takıp uçmaktan korkmayan kişiler "
        "için tasarlandı."
    )


def test_trendyol_visible_review_parser() -> None:
    html = _fixture("trendyol_product.html")
    adapter = TrendyolAdapter(
        client=None,
        config=ScraperConfig(),
    )  # type: ignore[arg-type]
    product = adapter.parse_product_html(
        "https://www.trendyol.com/marka/urun-p-123",
        html,
    )

    reviews = adapter.parse_visible_reviews_html(
        product.url,
        product,
        html,
        page_number=1,
    )

    assert len(reviews) == 2
    assert reviews[0].review_id == "ty-1"
    assert reviews[0].review_text == "Ürün çok kaliteli, hızlı geldi."
    assert reviews[0].rating == 5.0
    assert reviews[0].user_name == "Ayşe K."


def test_trendyol_visible_review_parser_ignores_non_review_blocks() -> None:
    html = """
    <div class="comments-summary">
      Ürün değerlendirmeleri ve yorumları burada listelenir.
    </div>
    """
    adapter = TrendyolAdapter(
        client=None,
        config=ScraperConfig(),
    )  # type: ignore[arg-type]
    product = adapter.parse_product_html(
        "https://www.trendyol.com/marka/urun-p-123",
        _fixture("trendyol_product.html"),
    )

    reviews = adapter.parse_visible_reviews_html(
        product.url,
        product,
        html,
        page_number=1,
    )

    assert reviews == []


def test_trendyol_extract_reviews_uses_yorumlar_page_fallback() -> None:
    product_html = _fixture("trendyol_product.html")
    url = "https://www.trendyol.com/marka/urun-p-123?boutiqueId=61&merchantId=144133"
    client = _FakeClient(product_html)
    adapter = TrendyolAdapter(
        client=client,
        config=ScraperConfig(max_review_pages=1),
    )
    product = adapter.parse_product_html(url, product_html)

    reviews = adapter.extract_reviews(url, product)

    assert len(reviews) == 2
    assert client.requested_urls[-1] == (
        "https://www.trendyol.com/marka/urun-p-123/yorumlar"
        "?boutiqueId=61&merchantId=144133"
    )


def test_trendyol_product_parser_reads_description_from_script_json() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="Script Ürünü">
        <script>
          window.__PRODUCT_DETAIL_APP_INITIAL_STATE__ = {
            "product": {
              "contentDescriptions": [
                {"description": "<p>Gerçek açıklama <b>script</b> içinden.</p>"}
              ]
            }
          };
        </script>
      </head>
    </html>
    """
    adapter = TrendyolAdapter(
        client=None,
        config=ScraperConfig(),
    )  # type: ignore[arg-type]

    product = adapter.parse_product_html(
        "https://www.trendyol.com/marka/urun-p-123",
        html,
    )

    assert product.description == "Gerçek açıklama script içinden."


def test_trendyol_product_parser_reads_escaped_rich_content_wrapper() -> None:
    html = r"""
    <html>
      <head>
        <meta property="og:title" content="Escaped Ürün">
        <script>
          window.__HTML__ = "\u003Cdiv id=\"rich-content-wrapper\"\u003E
            \u003Cp\u003EThalia Boutique Volare Eau De Parfüm
            \u003Cb\u003E Unisex 50ml\u003C/b\u003E\u003C/p\u003E
            \u003Cdiv\u003EGerçek açıklama escaped HTML içinden.\u003C/div\u003E
          \u003C/div\u003E";
        </script>
      </head>
    </html>
    """
    adapter = TrendyolAdapter(
        client=None,
        config=ScraperConfig(),
    )  # type: ignore[arg-type]

    product = adapter.parse_product_html(
        "https://www.trendyol.com/marka/urun-p-123",
        html,
    )

    assert product.description == (
        "Thalia Boutique Volare Eau De Parfüm Unisex 50ml "
        "Gerçek açıklama escaped HTML içinden."
    )


def test_trendyol_product_parser_reads_real_rich_content_wrapper_html() -> None:
    html = """
    <html>
      <head><meta property="og:title" content="Thalia Ürünü"></head>
      <body>
        <div id="rich-content-wrapper">
          <div>
            <div>
              <div>
                <p>
                  Thalia Boutique Volare Eau De Parfüm<b> Unisex 50ml</b>
                  Butik parfüm serisinde, sadeliği bilgelikle kucakladık.
                  Bizim için sadelik lüksün bir varyasyonudur.
                  <br>
                </p>
                <div>
                  Thalia Volare, cesaret kanatlarını takıp uçmaktan korkmayan
                  kişiler için tasarlandı. Üst notalarda hissedilen
                  <b>çarkıfelek, şeftali ve armut notaları</b>
                  ile içinizdeki özgürlük hissini besliyor.&nbsp;
                </div>
                <div>
                  <b>Üst Notalar: </b>Çarkıfelek, Şeftali, Armut
                </div>
              </div>
            </div>
          </div>
        </div>
      </body>
    </html>
    """
    adapter = TrendyolAdapter(
        client=None,
        config=ScraperConfig(),
    )  # type: ignore[arg-type]

    product = adapter.parse_product_html(
        "https://www.trendyol.com/marka/urun-p-123",
        html,
    )

    assert product.description.startswith(
        "Thalia Boutique Volare Eau De Parfüm Unisex 50ml"
    )
    assert "çarkıfelek, şeftali ve armut notaları" in product.description
    assert "Üst Notalar: Çarkıfelek, Şeftali, Armut" in product.description


def test_trendyol_product_parser_reads_full_product_content_wrapper_html() -> None:
    html = """
    <html>
      <head>
        <meta
          property="og:title"
          content="Thalia Boutique Volare Eau De Parfüm 3 ML"
        >
      </head>
      <body>
        <div
          id="product-content-wrapper"
          data-testid="product-description-content"
          class="content-description-content product-content-wrapper__text"
        >
          <div id="rich-content-wrapper">
            <div>
              <div>
                <div>
                  <p>
                    Thalia Boutique Volare Eau De Parfüm<b> Unisex 50ml</b>
                    Butik parfüm serisinde, sadeliği bilgelikle kucakladık.
                    Bizim için sadelik lüksün bir varyasyonudur.
                    <br>
                  </p>
                  <div>
                    Thalia Volare, cesaret kanatlarını takıp uçmaktan korkmayan
                    kişiler için tasarlandı. Üst notalarda hissedilen
                    <b>çarkıfelek, şeftali ve armut notaları</b>
                    ile içinizdeki özgürlük hissini besliyor.&nbsp;
                  </div>
                  <div>
                    <b>Üst Notalar: </b>Çarkıfelek, Şeftali, Armut
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </body>
    </html>
    """
    adapter = TrendyolAdapter(
        client=None,
        config=ScraperConfig(),
    )  # type: ignore[arg-type]

    product = adapter.parse_product_html(
        "https://www.trendyol.com/marka/urun-p-123",
        html,
    )

    assert product.title == "Thalia Boutique Volare Eau De Parfüm 3 ML"
    assert product.description.startswith(
        "Thalia Boutique Volare Eau De Parfüm Unisex 50ml"
    )
    assert "Butik parfüm serisinde" in product.description
    assert "çarkıfelek, şeftali ve armut notaları" in product.description


def test_trendyol_product_parser_reads_double_escaped_rich_content() -> None:
    html = r"""
    <html>
      <head><meta property="og:title" content="Double Escaped Ürün"></head>
      <script>
        window.__STATE__ = "\\u003Cdiv id=\\\"rich-content-wrapper\\\"\\u003E
          \\u003Cp\\u003EThalia Boutique Volare Eau De Parfüm
          \\u003Cb\\u003E Unisex 50ml\\u003C/b\\u003E\\u003C/p\\u003E
          \\u003Cdiv\\u003EDouble escaped açıklama.\\u003C/div\\u003E
        \\u003C/div\\u003E";
      </script>
    </html>
    """
    adapter = TrendyolAdapter(
        client=None,
        config=ScraperConfig(),
    )  # type: ignore[arg-type]

    product = adapter.parse_product_html(
        "https://www.trendyol.com/marka/urun-p-123",
        html,
    )

    assert product.description == (
        "Thalia Boutique Volare Eau De Parfüm Unisex 50ml " "Double escaped açıklama."
    )


def test_trendyol_extract_product_uses_detail_api_when_html_desc_missing() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="API Ürünü">
        <meta
          name="description"
          content="API Ürünü yorumlarını inceleyin, satın alın."
        >
      </head>
    </html>
    """
    url = "https://www.trendyol.com/marka/urun-p-123?merchantId=144133"
    client = _FakeProductDetailClient(
        html=html,
        payload={
            "product": {
                "contentDescriptions": [{"description": "Gerçek açıklama API içinden."}]
            }
        },
    )
    adapter = TrendyolAdapter(client=client, config=ScraperConfig())

    product = adapter.extract_product(url)

    assert product.description == "Gerçek açıklama API içinden."


def test_trendyol_extract_product_reads_descriptions_content_descriptions() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="API Ürünü">
        <meta
          name="description"
          content="API Ürünü yorumlarını inceleyin, satın alın."
        >
      </head>
    </html>
    """
    url = "https://www.trendyol.com/marka/urun-p-123?merchantId=144133"
    client = _FakeProductDetailClient(
        html=html,
        payload={
            "result": {
                "descriptions": {
                    "content_descriptions": [
                        {
                            "description": "Bu ürün en fazla 5 adet alınır.",
                            "type": "legal",
                        },
                        {
                            "description": ("Asıl ürün açıklaması API şemasından."),
                            "type": "default",
                        },
                    ]
                }
            }
        },
    )
    adapter = TrendyolAdapter(client=client, config=ScraperConfig())

    product = adapter.extract_product(url)

    assert product.description == "Asıl ürün açıklaması API şemasından."


def test_trendyol_extract_product_reads_descriptions_text_list() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="API Ürünü">
        <meta
          name="description"
          content="API Ürünü yorumlarını inceleyin, satın alın."
        >
      </head>
    </html>
    """
    url = "https://www.trendyol.com/marka/urun-p-123?merchantId=144133"
    client = _FakeProductDetailClient(
        html=html,
        payload={
            "result": {
                "descriptions": [
                    {
                        "text": "Bu ürün Trendyol tarafından gönderilecektir.",
                        "priority": 2,
                    },
                    {
                        "text": "Koku ailesi: çiçeksi ve meyvemsi.",
                        "priority": 0,
                    },
                ]
            }
        },
    )
    adapter = TrendyolAdapter(client=client, config=ScraperConfig())

    product = adapter.extract_product(url)

    assert product.description == "Koku ailesi: çiçeksi ve meyvemsi."


def test_trendyol_extract_product_uses_rendered_dom_fallback(monkeypatch) -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="Rendered Ürün">
        <meta
          name="description"
          content="Rendered Ürün yorumlarını inceleyin, satın alın."
        >
      </head>
    </html>
    """
    url = "https://www.trendyol.com/marka/urun-p-123?merchantId=144133"
    client = _FakeProductDetailErrorClient(html=html)

    def fake_rendered_text(
        url: str,
        timeout_seconds: float,
    ) -> str:
        assert url.endswith("merchantId=144133")
        return "Rendered DOM açıklaması."

    monkeypatch.setattr(
        "ecommerce_scraper.trendyol.get_rendered_product_description",
        fake_rendered_text,
    )
    adapter = TrendyolAdapter(client=client, config=ScraperConfig())

    product = adapter.extract_product(url)

    assert product.description == "Rendered DOM açıklaması."


def _fixture(name: str) -> str:
    return (Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8")


class _FakeClient:
    def __init__(self, html: str) -> None:
        self.html = html
        self.requested_urls: list[str] = []

    def get(self, url: str, params: dict[str, Any] | None = None) -> HttpResponse:
        self.requested_urls.append(url)
        return HttpResponse(url=url, status_code=200, text=self.html, headers={})

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        raise ScraperHttpError(f"test endpoint disabled: {url}")


class _FakeProductDetailClient:
    def __init__(self, html: str, payload: dict[str, Any]) -> None:
        self.html = html
        self.payload = payload

    def get(self, url: str, params: dict[str, Any] | None = None) -> HttpResponse:
        return HttpResponse(url=url, status_code=200, text=self.html, headers={})

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        return self.payload


class _FakeProductDetailErrorClient:
    def __init__(self, html: str) -> None:
        self.html = html

    def get(self, url: str, params: dict[str, Any] | None = None) -> HttpResponse:
        return HttpResponse(url=url, status_code=200, text=self.html, headers={})

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        raise ScraperHttpError(f"test endpoint disabled: {url}")
