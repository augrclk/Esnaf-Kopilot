from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Uygulama ayarları — .env dosyasından veya ortam değişkenlerinden okunur."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Gemini API
    gemini_api_key: str

    # Gemini model isimleri
    gemini_text_model: str = "gemini-3-flash-preview"
    gemini_image_model: str = "gemini-2.5-flash-image"

    # Scraper ayarları
    scraper_timeout: float = 20.0
    scraper_rate_limit: float = 0.8
    scraper_retry_count: int = 2
    max_review_pages: int = 50

    # Çıktı dizini
    output_dir: str = "outputs"


# Uygulama genelinde tek örnek
settings = Settings()
