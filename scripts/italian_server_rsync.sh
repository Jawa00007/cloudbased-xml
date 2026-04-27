#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Italian server → App server rsync push
# Runs on the ITALIAN SERVER (57.131.24.23) as a nightly cron job at 01:00
# (one hour before the ingestion job fires at 02:00 on the app server)
#
# Setup on Italian server:
#   1. Copy this file:   scp scripts/italian_server_rsync.sh ubuntu@57.131.24.23:~/sync_sii.sh
#   2. Make executable:  chmod +x ~/sync_sii.sh
#   3. Generate SSH key: ssh-keygen -t ed25519 -f ~/.ssh/id_sii -N ""
#   4. Copy key to app:  ssh-copy-id -i ~/.ssh/id_sii.pub ubuntu@APP_SERVER_IP
#   5. Add cron:         crontab -e
#      0 1 * * * /home/ubuntu/sync_sii.sh >> /home/ubuntu/sync_sii.log 2>&1
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Config — edit these before deploying ─────────────────────────────────────
APP_SERVER_IP="YOUR_APP_SERVER_IP"          # e.g. 164.90.200.100
APP_SERVER_USER="ubuntu"
SSH_KEY="/home/ubuntu/.ssh/id_sii"
LOCAL_DATA="/home/ubuntu/SII_CLOUD"
REMOTE_DATA="/home/ubuntu/SII_CLOUD"
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"
# ─────────────────────────────────────────────────────────────────────────────

echo "$LOG_PREFIX Starting rsync: $LOCAL_DATA -> $APP_SERVER_USER@$APP_SERVER_IP:$REMOTE_DATA"

rsync \
    --archive \
    --compress \
    --checksum \
    --delete \
    --exclude="_extracted/" \
    --exclude="*.tmp" \
    --progress \
    -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=30" \
    "$LOCAL_DATA/" \
    "$APP_SERVER_USER@$APP_SERVER_IP:$REMOTE_DATA/"

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "$LOG_PREFIX Rsync completed successfully."
else
    echo "$LOG_PREFIX ERROR: rsync failed with exit code $EXIT_CODE"
    exit $EXIT_CODE
fi

# Count synced files per account for the log
echo "$LOG_PREFIX File counts after sync:"
for account in BAT CH4 DINAMO EGOGREEN ENERGETICA ENERGIT; do
    count=$(find "$LOCAL_DATA/$account" -name "*.zip" 2>/dev/null | wc -l)
    echo "  $account: $count zip files"
done
