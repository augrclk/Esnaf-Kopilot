"""
Görsel analiz servisi — Görsel puanlama ve iyileştirme promptları üretimi.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from app.analyzer.gemini_client import GeminiClient
from app.models import (
    Product,
    ProductImage,
    ImageAnalysis,
    ImageEditPrompt,
    ImageEditTask,
    GeneratedImage,
)

log = logging.getLogger(__name__)

# Skill dosyası proje kökünden dinamik okunur (Skor-kriter.txt mantığıyla aynı)
# backend/app/analyzer/image.py → backend/app/analyzer → backend/app → backend → Esnaf-Kopilot
_BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

_SKILL_FILE = _BASE_DIR / "esnaf-kopilot-gorsel-analiz-skill-v5.txt"

def _load_image_skill() -> str:
    """Görsel analiz skill prompt'unu txt dosyasından yükler."""
    if _SKILL_FILE.exists():
        content = _SKILL_FILE.read_text(encoding="utf-8").strip()
        log.info("[ImageAnalyzer] Skill yüklendi: %s (%d karakter)", _SKILL_FILE.name, len(content))
        return content
    # Fallback — dosya yoksa minimal prompt
    log.warning("[ImageAnalyzer] %s bulunamadı, varsayılan prompt kullanılıyor.", _SKILL_FILE.name)
    return """You are an elite E-commerce Art Director.
Analyze the product and create a safe, conversion-focused image set strategy.
Concept 1 must always be 'Platform Standard White'.
Return valid JSON only:
{"best_image_analysis": "<Turkish>", "edit_tasks": [{"source_image_index": 1, "concept_name": "<English>", "prompt": "<English>"}]}"""


class ImageAnalyzer:
    """Görsel analiz ve strateji servisi."""

    def __init__(self, client: GeminiClient) -> None:
        self._client = client
        self._system_prompt = _load_image_skill()  # Sunucu başlarken bir kez yüklenir

    def plan_strategy(self, product: Product, images: list[ProductImage]) -> ImageAnalysis:
        """
        Ürünü ve tüm görsellerini analiz ederek yapay zekanın kendi kurguladığı 
        bir görsel üretim stratejisi (edit tasks) döner.
        """
        valid_images = [img for img in images if img.local_path]
        if not valid_images:
            raise ValueError("Geçerli hiçbir yerel görsel bulunamadı.")

        user_prompt = f"""
Ürün Başlığı: {product.title}
Ürün Açıklaması: {product.description[:300] if product.description else "Yok"}

MEVCUT ORİJİNAL GÖRSELLER (Aşağıdaki dosyalar sırasıyla 1'den {len(valid_images)}'e kadar indekslenmiştir):
"""
        for idx, img in enumerate(valid_images, 1):
            user_prompt += f"{idx}. Görsel URL: {img.url}\n"
            
        user_prompt += "\nLütfen ürünün doğasına en uygun görsel stratejini belirle ve JSON döndür."
        
        image_paths = [img.local_path for img in valid_images]
        raw = self._client.analyze_image(self._system_prompt, user_prompt, image_paths)
        
        return self._parse_analysis_result(raw, valid_images)

    _PRESERVATION_PREFIX = (
        "Use the exact same product from the reference image. "
        "Preserve the same visible angle, silhouette, proportions, colors, "
        "logo placement, label design, materials, texture, and all visible details. "
        "Do not rotate, redesign, reconstruct, reinterpret, or invent unseen parts. "
    )

    def enhance(self, original_image: ProductImage, prompt: ImageEditPrompt, output_path: str) -> GeneratedImage:
        """Gemini Image API ile görseli iyileştirir ve kaydeder (atomic write)."""
        if not original_image.local_path:
            raise ValueError("Orijinal görsel local_path eksik.")

        full_prompt = self._PRESERVATION_PREFIX + prompt.prompt
        new_image_bytes = self._client.edit_image(full_prompt, original_image.local_path)

        # Atomic write: temp dosyaya yaz, sonra rename — disk dolarsa truncated file kalmaz
        tmp_path = output_path + ".tmp"
        try:
            with open(tmp_path, "wb") as f:
                f.write(new_image_bytes)
            os.replace(tmp_path, output_path)   # atomic on POSIX
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

        return GeneratedImage(
            original_image=original_image,
            concept_name=prompt.concept_name,
            local_path=output_path,
        )

    def _parse_analysis_result(self, raw: dict, valid_images: list[ProductImage]) -> ImageAnalysis:
        tasks = []
        for task in raw.get("edit_tasks", []):
            idx = task.get("source_image_index", 1) - 1
            if idx < 0 or idx >= len(valid_images):
                idx = 0

            tasks.append(ImageEditTask(
                source_image=valid_images[idx],
                concept_name=str(task.get("concept_name", "")),
                prompt=str(task.get("prompt", "")),
            ))

        return ImageAnalysis(
            image=valid_images[0],
            image_type="STRATEJI",
            score=100,
            max_score=100,
            issues={"analysis_note": raw.get("best_image_analysis", "")},
            has_text=True,
            edit_tasks=tasks,
        )

