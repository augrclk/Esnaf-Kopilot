from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn
import logging
import os

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
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

# Rotaları ekle
app.include_router(router, prefix="/api")

# outputs/ klasörünü static olarak sun
_OUTPUTS = os.path.join(os.path.dirname(__file__), "outputs")
os.makedirs(_OUTPUTS, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=_OUTPUTS), name="outputs")

if __name__ == "__main__":
    print("🚀 Esnaf Kopilot API baslatiliyor... (http://localhost:8000)")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
