#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# App server one-time setup script
# Run this on your NEW production server (NOT the Italian file server)
#
# What it does:
#   1. Installs Python 3, git, rsync
#   2. Clones the GitHub repo
#   3. Creates Python virtual environment + installs dependencies
#   4. Creates .env from template (you fill in secrets after)
#   5. Creates DB tables in Supabase
#   6. Installs uvicorn as a systemd service (auto-start on boot)
#   7. Accepts SSH public key from Italian server (for rsync)
#
# Usage:
#   scp scripts/setup_app_server.sh ubuntu@APP_SERVER_IP:~/
#   ssh ubuntu@APP_SERVER_IP "bash ~/setup_app_server.sh"
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

REPO_URL="https://github.com/STG-707/cloudbased-xml.git"
APP_DIR="/home/ubuntu/cloudbased-xml"
DATA_DIR="/home/ubuntu/SII_CLOUD"
VENV="$APP_DIR/venv"

echo "=== SII Energy Platform — App Server Setup ==="

# ── 1. System packages ────────────────────────────────────────────────────────
echo "[1/7] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3 python3-pip python3-venv python3-dev \
    git rsync curl \
    libpq-dev build-essential

echo "  Python: $(python3 --version)"
echo "  rsync:  $(rsync --version | head -1)"

# ── 2. Clone repo ─────────────────────────────────────────────────────────────
echo "[2/7] Cloning repository..."
if [ -d "$APP_DIR" ]; then
    echo "  Repo exists — pulling latest..."
    cd "$APP_DIR" && git pull
else
    git clone "$REPO_URL" "$APP_DIR"
fi

# ── 3. Virtual environment ────────────────────────────────────────────────────
echo "[3/7] Setting up Python virtual environment..."
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install -r "$APP_DIR/requirements.txt"
echo "  Packages installed."

# ── 4. Environment file ───────────────────────────────────────────────────────
echo "[4/7] Creating .env..."
if [ ! -f "$APP_DIR/.env" ]; then
    cat > "$APP_DIR/.env" << 'ENVEOF'
# ── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL=postgresql+psycopg://postgres.YOUR_PROJECT_REF:YOUR_PASSWORD@aws-1-ap-southeast-2.pooler.supabase.com:5432/postgres

# ── App ───────────────────────────────────────────────────────────────────────
ENVIRONMENT=production
LOG_LEVEL=INFO
SECRET_KEY=CHANGE_ME_USE_A_LONG_RANDOM_STRING

# ── Auth ──────────────────────────────────────────────────────────────────────
API_KEY=CHANGE_ME_API_KEY
ADMIN_USERNAME=admin
ADMIN_PASSWORD=CHANGE_ME_ADMIN_PASSWORD

# ── Data path — files rsynced from Italian server ─────────────────────────────
SII_DATA_PATH=/home/ubuntu/SII_CLOUD
ENVEOF
    echo ""
    echo "  *** ACTION REQUIRED: fill in .env secrets ***"
    echo "  Run: nano $APP_DIR/.env"
    echo ""
else
    echo "  .env already exists — skipping."
fi

# ── 5. SII_CLOUD directory ────────────────────────────────────────────────────
echo "[5/7] Creating SII_CLOUD data directory..."
mkdir -p "$DATA_DIR"
for account in BAT CH4 DINAMO EGOGREEN ENERGETICA ENERGIT; do
    mkdir -p "$DATA_DIR/$account"
done
echo "  $DATA_DIR created with account subfolders."

# ── 6. Systemd service ────────────────────────────────────────────────────────
echo "[6/7] Installing systemd service..."
sudo tee /etc/systemd/system/sii-api.service > /dev/null << SVCEOF
[Unit]
Description=SII Energy Measurement Analytics API
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=$APP_DIR
ExecStart=$VENV/bin/uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
EnvironmentFile=$APP_DIR/.env

[Install]
WantedBy=multi-user.target
SVCEOF

sudo systemctl daemon-reload
sudo systemctl enable sii-api
echo "  Service installed (not started — fill .env first)."

# ── 7. SSH authorized_keys for Italian server rsync ───────────────────────────
echo "[7/7] Authorised keys setup..."
mkdir -p /home/ubuntu/.ssh
chmod 700 /home/ubuntu/.ssh
touch /home/ubuntu/.ssh/authorized_keys
chmod 600 /home/ubuntu/.ssh/authorized_keys
echo ""
echo "  To allow rsync FROM Italian server, paste the Italian server's"
echo "  public key here (cat ~/.ssh/id_sii.pub on Italian server):"
echo ""
echo "  echo 'PASTE_PUBLIC_KEY_HERE' >> /home/ubuntu/.ssh/authorized_keys"
echo ""

# ── Done ──────────────────────────────────────────────────────────────────────
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Fill in secrets:    nano $APP_DIR/.env"
echo "  2. Create DB tables:   cd $APP_DIR && $VENV/bin/python3 -c \\"
echo "       \"import asyncio; from backend.models.base import Base; from backend.db.session import engine; asyncio.run(engine.begin().__aenter__())\""
echo "  3. Start API:          sudo systemctl start sii-api"
echo "  4. Check status:       sudo systemctl status sii-api"
echo "  5. Test API:           curl http://localhost:8000/health"
echo ""
echo "  6. On Italian server:  Set APP_SERVER_IP in scripts/italian_server_rsync.sh"
echo "     Then:               crontab -e"
echo "     Add:                0 1 * * * /home/ubuntu/sync_sii.sh >> /home/ubuntu/sync_sii.log 2>&1"
echo ""
echo "  7. Run first ingest:   cd $APP_DIR && source venv/bin/activate"
echo "     Then:               python3 -m backend.ingestion.ingest --all"
