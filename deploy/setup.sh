#!/bin/bash
# Esnaf Kopilot — GCP VM kurulum scripti
# Ubuntu 22.04 LTS üzerinde çalışır
# Kullanım: sudo bash setup.sh

set -e

APP_DIR="/opt/esnaf-kopilot"
REPO_URL="https://github.com/KULLANICI_ADI/esnaf-kopilot.git"  # GitHub repo URL'ini gir
DOMAIN=""  # Alan adı varsa gir (örn: esnafkopilot.com), yoksa boş bırak

echo "=== Sistem güncellemesi ==="
apt-get update -y && apt-get upgrade -y

echo "=== Paket kurulumu ==="
apt-get install -y python3 python3-pip python3-venv nginx git certbot python3-certbot-nginx ufw

echo "=== Firewall ==="
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

echo "=== Uygulama dizini ==="
mkdir -p $APP_DIR
cd $APP_DIR

echo "=== Repo klonla ==="
git clone $REPO_URL .

echo "=== Python venv ==="
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .

echo "=== outputs/ dizini ==="
mkdir -p outputs

echo ""
echo "=== MANUEL ADIMLAR ==="
echo "1. Secrets dosyalarını kopyala:"
echo "   scp firebase_credentials.json user@IP:/opt/esnaf-kopilot/backend/"
echo "   scp .env user@IP:/opt/esnaf-kopilot/backend/"
echo ""
echo "2. Systemd servisini kur:"
echo "   sudo cp /opt/esnaf-kopilot/deploy/esnaf-kopilot.service /etc/systemd/system/"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable esnaf-kopilot"
echo "   sudo systemctl start esnaf-kopilot"
echo ""
echo "3. Nginx config kur:"
echo "   sudo cp /opt/esnaf-kopilot/deploy/nginx.conf /etc/nginx/sites-available/esnaf-kopilot"
echo "   sudo ln -s /etc/nginx/sites-available/esnaf-kopilot /etc/nginx/sites-enabled/"
echo "   sudo rm -f /etc/nginx/sites-enabled/default"
echo "   sudo nginx -t && sudo systemctl reload nginx"
echo ""
echo "4. SSL (domain varsa):"
echo "   sudo certbot --nginx -d yourdomain.com"
