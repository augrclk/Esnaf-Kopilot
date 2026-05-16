"""
Gemini API wrapper — metin analizi ve görsel işlemleri.

Iki ana kullanım:
  1. analyze_text()  — SEO/AEO puanlama ve içerik üretimi
  2. analyze_image() — Görsel analiz ve düzenleme promptu üretimi
  3. edit_image()    — Gemini Image API ile görsel iyileştirme
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from google import genai
from google.genai import types

from app.config import settings
from app.models import GeminiError

log = logging.getLogger(__name__)


class GeminiClient:
    """
    Gemini API istemcisi.

    Tek örnek olarak kullanılır — uygulama genelinde bir kez oluşturulur.
    """

    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._text_model = settings.gemini_text_model
        self._image_model = settings.gemini_image_model

    def analyze_text(self, system_prompt: str, user_prompt: str) -> dict:
        """
        Metin tabanlı analiz yapar. JSON dict döner.

        Args:
            system_prompt: Modelin rolünü ve kuralları tanımlayan sistem mesajı
            user_prompt: Analiz edilecek veri ve görev

        Returns:
            Gemini'nin döndürdüğü JSON içeriği dict olarak

        Raises:
            GeminiError: API çağrısı başarısız olduğunda
        """
        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        response_text = self._call_text_api(full_prompt)
        return _parse_json_response(response_text)

    def analyze_image(
        self,
        system_prompt: str,
        user_prompt: str,
        image_paths: list[str],
    ) -> dict:
        """
        Görsel(ler) ile birlikte analiz yapar. JSON dict döner.

        Args:
            system_prompt: Analiz kuralları
            user_prompt: Analiz görevi
            image_paths: Analiz edilecek görsellerin local dosya yolları

        Returns:
            Gemini'nin döndürdüğü JSON içeriği dict olarak
        """
        parts: list = [f"{system_prompt}\n\n{user_prompt}"]

        for path in image_paths:
            image_bytes = Path(path).read_bytes()
            mime = _mime_type(path)
            parts.append(types.Part.from_bytes(data=image_bytes, mime_type=mime))

        response_text = self._call_text_api_with_parts(parts)
        return _parse_json_response(response_text)

    def edit_image(self, prompt: str, image_path: str) -> bytes:
        """
        Gemini Image API ile görseli düzenler, yeni görsel bytes döner.

        Args:
            prompt: Düzenleme talimatı (ürün değişmeden, arka plan/sahne yönergesi)
            image_path: Düzenlenecek görselin local dosya yolu

        Returns:
            Düzenlenmiş görsel içeriği (bytes)

        Raises:
            GeminiError: API çağrısı başarısız olduğunda veya görsel üretilemediğinde
        """
        image_bytes = Path(image_path).read_bytes()
        mime = _mime_type(image_path)

        # Config'den gelen model önce, ardından fallback'ler
        # Gerçek timeout asyncio.wait_for ile api.py katmanında yönetilir.
        models_to_try = [
            self._image_model,
            "gemini-2.5-flash-image",
            "gemini-3-pro-image-preview",
        ]
        seen: set[str] = set()
        models = [x for x in models_to_try if not (x in seen or seen.add(x))]

        last_error = None

        for model_name in models:
            for attempt in range(2):  # Her model için en fazla 2 deneme
                try:
                    response = self._client.models.generate_content(
                        model=model_name,
                        contents=[
                            prompt,
                            types.Part.from_bytes(data=image_bytes, mime_type=mime),
                        ],
                        config=types.GenerateContentConfig(
                            response_modalities=["IMAGE", "TEXT"],
                        ),
                    )

                    for part in response.candidates[0].content.parts:
                        if part.inline_data is not None:
                            return part.inline_data.data

                    raise GeminiError(f"Gemini ({model_name}) gorsel uretemedi — yanıtta inline_data yok")

                except Exception as exc:
                    err_str = str(exc)
                    if "503" in err_str or "429" in err_str or "high demand" in err_str.lower():
                        if attempt < 1:
                            log.warning("[API MESGUL] %s yogun. 10s bekleniyor... (Deneme %d/2)", model_name, attempt + 1)
                            time.sleep(10)
                            continue
                    last_error = exc
                    log.warning("[UYARI] %s basarisiz, diger modele geciliyor. Hata: %s", model_name, exc)
                    break

        raise GeminiError(f"Gorsel duzenleme basarisiz. Son hata: {last_error}") from last_error


    # ------------------------------------------------------------------
    # Dahili API çağrıları
    # ------------------------------------------------------------------

    def chat_text(self, system_prompt: str, user_message: str) -> str:
        """
        Sohbet tarzı soru için ham metin yanıtı döner (JSON parse edilmez).

        Args:
            system_prompt: Asistan rolü ve bağlam
            user_message: Kullanıcının sorusu

        Returns:
            Gemini'nin düz metin yanıtı
        """
        full_prompt = f"{system_prompt}\n\nKullanıcı: {user_message}"
        return self._call_text_api(full_prompt)

    def _call_text_api(self, prompt: str, retry: int = 2) -> str:
        """Metin promptu ile Gemini'yi çağırır. Model başarısız → fallback sırasını dener."""
        models_to_try = [self._text_model, "gemini-2.5-flash", "gemini-2.5-pro"]
        seen: set[str] = set()
        models = [m for m in models_to_try if not (m in seen or seen.add(m))]

        last_error: Exception | None = None

        for model_name in models:
            for attempt in range(retry + 1):
                try:
                    response = self._client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                    )
                    return response.text or ""
                except Exception as exc:
                    last_error = exc
                    err_str = str(exc)
                    if ("503" in err_str or "429" in err_str or "high demand" in err_str.lower()):
                        if attempt < retry:
                            wait = 2 ** attempt
                            log.warning("[API MESGUL] %s yogun. %ds bekleniyor... (%d/%d)",
                                        model_name, wait, attempt + 1, retry + 1)
                            time.sleep(wait)
                            continue
                    log.warning("[UYARI] %s basarisiz, fallback'e geciliyor. Hata: %s", model_name, exc)
                    break

        raise GeminiError(f"Text API tum modeller basarisiz. Son hata: {last_error}") from last_error

    def _call_text_api_with_parts(self, parts: list, retry: int = 2) -> str:
        """Çok parçalı (metin + görsel) promptla Gemini'yi çağırır. Fallback destekli."""
        models_to_try = [self._text_model, "gemini-2.5-flash", "gemini-2.5-pro"]
        seen: set[str] = set()
        models = [m for m in models_to_try if not (m in seen or seen.add(m))]

        last_error: Exception | None = None

        for model_name in models:
            for attempt in range(retry + 1):
                try:
                    response = self._client.models.generate_content(
                        model=model_name,
                        contents=parts,
                    )
                    return response.text or ""
                except Exception as exc:
                    last_error = exc
                    err_str = str(exc)
                    if ("503" in err_str or "429" in err_str or "high demand" in err_str.lower()):
                        if attempt < retry:
                            wait = 2 ** attempt
                            log.warning("[API MESGUL] %s yogun. %ds bekleniyor... (%d/%d)",
                                        model_name, wait, attempt + 1, retry + 1)
                            time.sleep(wait)
                            continue
                    log.warning("[UYARI] %s basarisiz, fallback'e geciliyor. Hata: %s", model_name, exc)
                    break

        raise GeminiError(f"Multimodal API tum modeller basarisiz. Son hata: {last_error}") from last_error


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------


def _parse_json_response(text: str) -> dict:
    """
    Gemini'nin yanıtından JSON çıkarır.

    Gemini bazen JSON'u markdown code block içinde döner:
      ```json
      { ... }
      ```
    Bu fonksiyon her iki formatı da işler.
    """
    if not text:
        raise GeminiError("Gemini boş yanıt döndürdü")

    # Markdown code block içindeki JSON'u çıkar
    code_block = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    json_text = code_block.group(1).strip() if code_block else text.strip()

    # Yanıt bazen { ile başlamıyor olabilir, ilk { konumunu bul
    start = json_text.find("{")
    if start > 0:
        json_text = json_text[start:]

    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        # JSON parse edilemedi — ham metni debug için döndür
        raise GeminiError(
            f"Gemini yanıtı JSON olarak parse edilemedi.\nHam yanıt: {text[:500]}"
        )


def _mime_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "image/jpeg")
