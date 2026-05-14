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
Sen uzman bir e-ticaret görsel sanat yönetmeni ve yaratıcı reklam fotoğrafçısısın.
Sana bir ana ürün görseli ve detaylı ürün bilgileri (başlık, açıklama) verilecek.
Görevin, sadece görseli değil, ÜRÜNÜN ÖZÜNÜ, AÇIKLAMASINI VE AMACINI anlayıp; müşteriye "WOW" dedirtecek, olağanüstü kalitede 8 farklı image-to-image düzenleme promptu üretmektir.

KURAL: Bu promptlar Gemini Image API'ye gidecek. Ürünün şekli, ambalajı ve yazıları ASLA değişmemeli. Ancak çevre, sahne, ışık ve kompozisyon tamamen değişecek. Promptları çok detaylı, profesyonel İngilizce (English) fotoğrafçılık terimleriyle yaz (örn: 85mm lens, volumetric lighting, hyper-realistic, bokeh, cinematic composition).

ÜRÜN BİLGİSİNİ KULLAN VE YARATICI OL!
ÖNEMLİ: Her ürün için aynı konseptler tutmaz! Sadece 1. ve 8. konseptler standarttır, aradaki 6 konsepti tamamen o ÜRÜNE ÖZEL icat et.

Konsept Dağılımı (Toplam 8 Adet):
1. "Platform Standard White" (ZORUNLU): Trendyol/Amazon için saf beyaz arka planda, mükemmel stüdyo aydınlatmasıyla kusursuz temiz listeleme görseli.
2. (ÜRÜNE ÖZEL KONSEPT ADI): Ürüne özel dinamik veya dikkat çekici bir kompozisyon.
3. (ÜRÜNE ÖZEL KONSEPT ADI): Ürüne özel manken elinde veya model ile kullanım bağlamı.
4. (ÜRÜNE ÖZEL KONSEPT ADI): Ürüne özel set arkası veya farklı bir profesyonel dokunuş.
5. (ÜRÜNE ÖZEL KONSEPT ADI): Hammadde, içerik veya üretim yeriyle ilgili gerçekçi bir çevre (Thematic Realism).
6. (ÜRÜNE ÖZEL KONSEPT ADI): Ürünün sosyal medyada viral olmasını sağlayacak sinematik veya dramatik aydınlatma.
7. (ÜRÜNE ÖZEL KONSEPT ADI): Lüks, lifestyle veya ürünün zirve noktasını gösteren ambiyans.
8. "Feature Infographic" (ZORUNLU): Ürünün etrafında kısa 3-4 kelimelik ana özelliklerinin (başlıktan/açıklamadan çıkardığın) okunaklı, profesyonel fontlarla yazıldığı bilgi görseli. Ürün ortada olmalı, yazılar ürünü kapatmamalı. (Not: Metinleri İngilizce veya Türkçe tutabilirsin ama kısa ve vurucu olsun).

ÇIKTI FORMATI (Sadece aşağıdaki JSON yapısı):
{
  "best_image_analysis": "<Ürün açıklamasından ne anladın ve bu özel 8 konsepti neden seçtin? Türkçe kısa sanat yönetimi notu>",
  "edit_prompts": [
    {
      "concept_name": "Platform Standard White",
      "prompt": "<İngilizce, fotoğrafçılık terimleriyle dolu detaylı image-to-image prompt>"
    },
    {
      "concept_name": "<Yaratıcı İngilizce Konsept Adı 2>",
      "prompt": "<İngilizce, fotoğrafçılık terimleriyle dolu detaylı image-to-image prompt>"
    }
    // ... toplam 8 konsept sırasıyla eklenecek
  ]
}
"""

class ImageAnalyzer:
    """Görsel analiz ve iyileştirme servisi."""

    def __init__(self, client: GeminiClient) -> None:
        self._client = client

    def analyze(self, product: Product, image: ProductImage) -> ImageAnalysis:
        """
        Ana görseli analiz eder ve 7 farklı konsept için prompt üretir.
        """
        if not image.local_path:
            raise ValueError(f"Görsel local olarak indirilmemiş: {image.url}")

        user_prompt = f"""
Lütfen bu ana görseli temel alarak 7 farklı konsept promptunu üret.

Ürün Başlığı: {product.title}
Ürün Açıklaması: {product.description[:300] if product.description else "Yok"}

Sadece JSON formatında yanıt ver.
"""
        raw = self._client.analyze_image(_IMAGE_EVAL_SYSTEM, user_prompt, [image.local_path])
        return self._parse_analysis_result(raw, image)

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

    def _parse_analysis_result(self, raw: dict, image: ProductImage) -> ImageAnalysis:
        prompts = []
        for p in raw.get("edit_prompts", []):
            prompts.append(ImageEditPrompt(
                concept_name=str(p.get("concept_name", "")),
                prompt=str(p.get("prompt", "")),
            ))

        return ImageAnalysis(
            image=image,
            image_type="ANA_GORSEL",  # Artık tek görsel üzerinden türetiliyor
            score=80,  # Yeni mantıkta analiz puanlaması arka planda kaldı
            max_score=80,
            issues={"analysis_note": raw.get("best_image_analysis", "")},
            has_text=True,
            edit_prompts=prompts,
        )

