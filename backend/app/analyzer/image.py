"""
Görsel analiz servisi — Görsel puanlama ve iyileştirme promptları üretimi.
"""

from __future__ import annotations

import json
from app.analyzer.gemini_client import GeminiClient
from app.models import (
    Product,
    ProductImage,
    ImageAnalysis,
    ImageEditPrompt,
    GeneratedImage,
)

_IMAGE_EVAL_SYSTEM = """
You are an elite E-commerce Art Director, Creative Strategist, and Master Advertising Photographer.
You will be provided with detailed product information (title, description) and all available original images of the product (indexed from 1 to N).

YOUR MISSION: Deeply understand the product and devise the ultimate IMAGE SET (portfolio) strategy to maximize conversion rates and e-commerce sales.
You are NOT bound by templates. Every product has unique needs:
- A perfume might require 8 different lifestyle and ambient shots derived from a single bottle image.
- A technical gadget or power tool might only need 4-5 highly focused images using 3 different original source angles.

DECISIONS YOU MUST MAKE AUTONOMOUSLY:
1. QUANTITY: Decide exactly how many final images need to be generated (Minimum 3, Maximum 8). Scale this based on what the product genuinely needs to sell.
2. SOURCE MAPPING: For every concept you create, choose exactly WHICH original image index (source_image_index) should be used as the base.
3. THE RULE OF THE FIRST: The first image (Concept 1) MUST always be a "Platform Standard White" — a flawless, pure white background studio shot suitable for primary marketplace listings (Trendyol/Amazon).
4. CREATIVE FREEDOM: For the remaining images, the background does NOT need to be white. Design creative, thematic, lifestyle, contextual, or feature-infographic scenes that will make the customer say "WOW".

IMAGE-TO-IMAGE RULES:
- These prompts will be fed into the Gemini Image API.
- The core structure, shape, and packaging of the product in the chosen source image MUST NEVER be altered.
- Only the environment, background, lighting, scene, and composition should change.
- Write highly detailed, professional photography prompts in ENGLISH (e.g., 85mm lens, volumetric lighting, hyper-realistic, bokeh, cinematic composition).
- IMPORTANT LANGUAGE EXCEPTION: If you design a "Feature Infographic" concept that includes text directly on the image, you MUST explicitly state in the prompt that the typography/text must be written in TURKISH.

OUTPUT FORMAT (Respond ONLY with the following JSON structure):
{
  "best_image_analysis": "<Briefly explain your strategy in Turkish: Why did you choose these specific source images and concepts? What is the creative direction?>",
  "edit_tasks": [
    {
      "source_image_index": <Integer from 1 to N indicating the chosen original image>,
      "concept_name": "<Creative Concept Name in English (e.g., Platform Standard White, Tropical Splash)>",
      "prompt": "<Highly detailed image-to-image prompt in English. If it contains text, request the text explicitly in Turkish>"
    }
  ]
}
"""

class ImageAnalyzer:
    """Görsel analiz ve strateji servisi."""

    def __init__(self, client: GeminiClient) -> None:
        self._client = client

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
        raw = self._client.analyze_image(_IMAGE_EVAL_SYSTEM, user_prompt, image_paths)
        
        return self._parse_analysis_result(raw, valid_images)

    def enhance(self, original_image: ProductImage, prompt: ImageEditPrompt, output_path: str) -> GeneratedImage:
        """
        Gemini Image API ile görseli iyileştirir ve kaydeder.
        """
        if not original_image.local_path:
            raise ValueError("Orijinal görsel local_path eksik.")

        new_image_bytes = self._client.edit_image(prompt.prompt, original_image.local_path)
        
        with open(output_path, "wb") as f:
            f.write(new_image_bytes)

        return GeneratedImage(
            original_image=original_image,
            concept_name=prompt.concept_name,
            local_path=output_path,
        )

    def _parse_analysis_result(self, raw: dict, valid_images: list[ProductImage]) -> ImageAnalysis:
        import app.models as models
        
        tasks = []
        for task in raw.get("edit_tasks", []):
            idx = task.get("source_image_index", 1) - 1
            if idx < 0 or idx >= len(valid_images):
                idx = 0  # Fallback to the first image if out of bounds
                
            tasks.append(models.ImageEditTask(
                source_image=valid_images[idx],
                concept_name=str(task.get("concept_name", "")),
                prompt=str(task.get("prompt", "")),
            ))

        return models.ImageAnalysis(
            image=valid_images[0], # Legacy, keep to avoid breaking things
            image_type="STRATEJI",
            score=100,
            max_score=100,
            issues={"analysis_note": raw.get("best_image_analysis", "")},
            has_text=True,
            edit_tasks=tasks,
        )

