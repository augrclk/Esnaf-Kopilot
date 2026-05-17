# GCP Deploy Rehberi

## 1. VM Oluştur (GCP Console)

- **Compute Engine → VM instances → Create**
- Machine type: `e2-medium` (2 vCPU, 4GB RAM)
- Boot disk: Ubuntu 22.04 LTS, 20GB SSD
- Firewall: ✅ Allow HTTP, ✅ Allow HTTPS
- Region: `europe-west1` (Belçika) — Türkiye'ye en yakın

## 2. Secrets Hazırla (local makinede)

```bash
cd /path/to/Esnaf-Kopilot/backend

# VM'e gönder (VM_IP = GCP'den aldığın external IP)
gcloud compute scp firebase_credentials.json VM_ADI:/tmp/
gcloud compute scp .env VM_ADI:/tmp/
```

## 3. VM'e SSH + Kurulum

```bash
gcloud compute ssh VM_ADI

# Scripti çalıştır
sudo bash /tmp/setup.sh   # önce repo URL'ini güncelle!
```

## 4. Secrets Yerleştir

```bash
sudo mv /tmp/firebase_credentials.json /opt/esnaf-kopilot/backend/
sudo mv /tmp/.env /opt/esnaf-kopilot/backend/
sudo chown www-data:www-data /opt/esnaf-kopilot/backend/firebase_credentials.json
sudo chown www-data:www-data /opt/esnaf-kopilot/backend/.env
```

## 5. Servis + Nginx

```bash
sudo cp /opt/esnaf-kopilot/deploy/esnaf-kopilot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable esnaf-kopilot
sudo systemctl start esnaf-kopilot

sudo cp /opt/esnaf-kopilot/deploy/nginx.conf /etc/nginx/sites-available/esnaf-kopilot
sudo ln -s /etc/nginx/sites-available/esnaf-kopilot /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

## 6. Kontrol

```bash
sudo systemctl status esnaf-kopilot
sudo journalctl -u esnaf-kopilot -f   # canlı log
curl http://localhost:8000/api/health
```

## 7. Frontend API_BASE Güncelle

`frontend/app.js` satır 2-4:
```js
const API_BASE = window.location.hostname === 'localhost'
    ? 'http://localhost:8000'
    : '';  // production: nginx same-origin proxy — değiştirme
```
Production'da nginx `/api/` → `127.0.0.1:8000` proxy yaptığı için `''` doğru.

## Güncelleme (sonraki deploylar)

```bash
gcloud compute ssh VM_ADI
cd /opt/esnaf-kopilot
sudo git pull
cd backend && source .venv/bin/activate && pip install -e .
sudo systemctl restart esnaf-kopilot
```
