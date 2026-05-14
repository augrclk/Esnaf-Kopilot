from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn
import os

from app.api import router

app = FastAPI(
    title="Esnaf Kopilot API",
    description="Trendyol Ürün Analiz ve Görsel İyileştirme API'si",
    version="1.0.0"
)

# CORS ayarları (Frontend'in her porttan erişebilmesi için)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rotaları ekle
app.include_router(router, prefix="/api")

# Eğer outputs klasörü varsa static olarak sun
if not os.path.exists("outputs"):
    os.makedirs("outputs")
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")

if __name__ == "__main__":
    print("🚀 Esnaf Kopilot API baslatiliyor... (http://localhost:8000)")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
