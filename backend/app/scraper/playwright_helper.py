"""
Playwright ile sayfa render ederek ürün açıklaması çekme.

Trendyol bazı ürünlerde açıklamayı JavaScript ile yükler.
Bu modül opsiyoneldir — kurulu değilse scraper devam eder.

Kurulum: pip install playwright && playwright install chromium
"""

from __future__ import annotations


def get_rendered_description(url: str, timeout: float = 15.0) -> str | None:
    """
    Playwright ile sayfayı render eder, ürün açıklamasını döner.
    Playwright kurulu değilse None döner.

    Args:
        url: Trendyol ürün sayfası URL'si
        timeout: Sayfa yükleme zaman aşımı (saniye)

    Returns:
        Açıklama metni veya None
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    timeout_ms = int(timeout * 1000)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(locale="tr-TR")
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

                # Açıklama bazen sayfa kaydırıldıkça yükleniyor
                for scroll_y in (800, 1600, 2400, 3200, 4500):
                    text = _evaluate_description(page)
                    if text:
                        return text
                    page.evaluate(f"window.scrollTo(0, {scroll_y})")
                    page.wait_for_timeout(800)

                return _evaluate_description(page)
            finally:
                browser.close()
    except Exception:
        return None


# JavaScript ile sayfadan açıklama çeken kod
_DESCRIPTION_SCRIPT = """
() => {
  const clean = (el) => (el?.innerText || "").replace(/\\s+/g, " ").trim()
                         .replace(/^Ürün Açıklaması\\s*/i, "").trim();

  // Bilinen selector'lar
  const selectors = [
    "#rich-content-wrapper",
    '[data-testid="product-description-content"]',
    "#product-content-wrapper",
    ".content-description-content",
    ".product-content-wrapper__text",
  ];
  for (const sel of selectors) {
    const text = clean(document.querySelector(sel));
    if (text) return text;
  }

  // "Ürün Açıklaması" başlığını bul, içeriği al
  const heading = Array.from(document.querySelectorAll("h1,h2,h3,h4,h5,span,div"))
    .find(el => el.innerText?.trim().toLowerCase() === "ürün açıklaması");
  if (!heading) return null;

  for (const parent of [heading.parentElement, heading.parentElement?.parentElement]) {
    const text = clean(parent);
    if (text && text.toLowerCase() !== "ürün açıklaması") return text;
  }

  return null;
}
"""


def _evaluate_description(page: object) -> str | None:
    try:
        result = page.evaluate(_DESCRIPTION_SCRIPT)
        return result.strip() if isinstance(result, str) and result.strip() else None
    except Exception:
        return None
