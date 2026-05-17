from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import logging

from app.api import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

app = FastAPI(
    title="Esnaf Kopilot API",
    description="Trendyol Ürün Analiz ve Görsel İyileştirme API'si",
    version="1.0.0"
)

# allow_credentials=True ile allow_origins="*" kombinasyonu CORS spec'e göre geçersiz.
# credentials gerekmediği için False bırakıldı.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

# Rotaları ekle
app.include_router(router, prefix="/api")

# Görseller artık Firebase Storage'dan sunuluyor — StaticFiles mount gereksiz.

if __name__ == "__main__":
    print("🚀 Esnaf Kopilot API baslatiliyor... (http://localhost:8000)")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
