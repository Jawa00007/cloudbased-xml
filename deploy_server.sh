#!/bin/bash
# SII Platform — Server Deployment Script
# Run on the Italian server as ubuntu user
# Usage: bash deploy_server.sh

set -e

echo "=== SII Energy Platform — Server Deployment ==="

# ── 1. System packages ─────────────────────────────────────────────────────────
echo "[1/7] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3 python3-pip python3-venv \
    git curl build-essential \
    libpq-dev

echo "Python version: $(python3 --version)"

# ── 2. Clone repo ──────────────────────────────────────────────────────────────
echo "[2/7] Cloning repository..."
cd /home/ubuntu

if [ -d "cloudbased-xml" ]; then
    echo "Repo exists — pulling latest..."
    cd cloudbased-xml
    git pull
else
    git clone https://github.com/STG-707/cloudbased-xml.git
    cd cloudbased-xml
fi

# ── 3. Virtual environment + dependencies ─────────────────────────────────────
echo "[3/7] Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt

echo "Packages installed."

# ── 4. Environment file ────────────────────────────────────────────────────────
echo "[4/7] Creating .env file..."
if [ ! -f ".env" ]; then
    cat > .env << 'ENVEOF'
# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL=postgresql+psycopg://postgres.YOUR_PROJECT_REF:YOUR_PASSWORD@aws-1-ap-southeast-2.pooler.supabase.com:5432/postgres

# ── App ───────────────────────────────────────────────────────────────────────
ENVIRONMENT=production
LOG_LEVEL=INFO
SECRET_KEY=change-me-in-production-use-random-string

# ── Auth ──────────────────────────────────────────────────────────────────────
API_KEY=your-api-key-here
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-admin-password-here

# ── Data path ─────────────────────────────────────────────────────────────────
SII_DATA_PATH=/home/ubuntu/SII_CLOUD
ENVEOF
    echo ""
    echo "*** IMPORTANT: Edit .env with your Supabase DATABASE_URL ***"
    echo "Run: nano .env"
    echo ""
else
    echo ".env already exists — skipping."
fi

# ── 5. Create DB tables ────────────────────────────────────────────────────────
echo "[5/7] Creating database tables (if not exist)..."
source venv/bin/activate
python3 -c "
import asyncio, sys
sys.path.insert(0, '.')
async def create():
    from backend.models.base import Base
    from backend.db.session import engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print('Tables OK')
asyncio.run(create())
" 2>&1 || echo "DB setup — check .env DATABASE_URL if this failed"

# ── 6. Test ingestion (BAT account, dry-run check) ────────────────────────────
echo "[6/7] Checking data files..."
ls /home/ubuntu/SII_CLOUD/

for account in BAT CH4 DINAMO EGOGREEN ENERGETICA ENERGIT; do
    path="/home/ubuntu/SII_CLOUD/$account"
    if [ -d "$path" ]; then
        xml_count=$(find "$path" -name "*.xml" 2>/dev/null | wc -l)
        zip_count=$(find "$path" -name "*.zip" 2>/dev/null | wc -l)
        echo "  $account: $xml_count .xml files, $zip_count .zip files"
    else
        echo "  $account: folder not found"
    fi
done

# ── 7. Systemd service ─────────────────────────────────────────────────────────
echo "[7/7] Installing systemd service..."
sudo tee /etc/systemd/system/sii-api.service > /dev/null << 'SVCEOF'
[Unit]
Description=SII Energy Measurement Analytics API
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/cloudbased-xml
ExecStart=/home/ubuntu/cloudbased-xml/venv/bin/uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
Environment=PATH=/home/ubuntu/cloudbased-xml/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin

[Install]
WantedBy=multi-user.target
SVCEOF

sudo systemctl daemon-reload
sudo systemctl enable sii-api
sudo systemctl start sii-api

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "API status:"
sudo systemctl status sii-api --no-pager -l

echo ""
echo "API available at: http://57.131.24.23:8000/docs"
echo ""
echo "Next steps:"
echo "  1. Edit .env: nano /home/ubuntu/cloudbased-xml/.env"
echo "  2. Add your Supabase DATABASE_URL"
echo "  3. Restart API: sudo systemctl restart sii-api"
echo "  4. Run ingestion: cd /home/ubuntu/cloudbased-xml && source venv/bin/activate && python3 -m backend.ingestion.ingest --all --data-path /home/ubuntu/SII_CLOUD"
