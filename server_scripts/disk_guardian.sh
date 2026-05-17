#!/usr/bin/env bash
# disk_guardian.sh — Monitor disk space and auto-clean before it fills up.
# Runs every 15 minutes via systemd timer.
#
# Thresholds:
#   > 80%: prune Docker build cache + journal
#   > 88%: also remove old backfill logs (keep last 3)
#   > 93%: aggressive prune + alert via API log WARNING

set -uo pipefail

LOGFILE=/opt/sii/logs/disk_monitor.log
mkdir -p /opt/sii/logs

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOGFILE"; }

used_pct() { df / | awk 'NR==2 {gsub(/%/,"",$5); print $5}'; }

PCT=$(used_pct)
log "Disk: ${PCT}% used"

if [ "$PCT" -lt 80 ]; then
    exit 0
fi

log "WARNING: disk at ${PCT}% — starting cleanup"

# Level 1 (>80%): Docker build cache + journal
docker builder prune -f >> "$LOGFILE" 2>&1 && log "Docker build cache pruned"
journalctl --vacuum-size=50M >> "$LOGFILE" 2>&1 && log "Journal vacuumed to 50MB"
docker image prune -f >> "$LOGFILE" 2>&1 && log "Dangling images pruned"

PCT=$(used_pct)
log "After level-1 cleanup: ${PCT}%"

if [ "$PCT" -lt 88 ]; then
    exit 0
fi

log "WARNING: disk still at ${PCT}% — level-2 cleanup"

# Level 2 (>88%): Remove old backfill logs (keep last 3)
ls -t /opt/sii/logs/backfill_*.log 2>/dev/null | tail -n +4 | xargs rm -f
log "Old backfill logs removed"

# Remove stopped containers
docker container prune -f >> "$LOGFILE" 2>&1 && log "Stopped containers pruned"

PCT=$(used_pct)
log "After level-2 cleanup: ${PCT}%"

if [ "$PCT" -lt 93 ]; then
    exit 0
fi

# Level 3 (>93%): CRITICAL — log loudly, try to free more
log "CRITICAL: disk at ${PCT}% — emergency cleanup!"

# Truncate oldest remaining logs
find /opt/sii/logs -name "*.log" -not -name "disk_monitor.log" -not -newer /opt/sii/logs/disk_monitor.log \
    | head -5 | xargs rm -f 2>/dev/null
log "Old logs removed"

PCT=$(used_pct)
log "After level-3 cleanup: ${PCT}% — intervention may be needed if still >93%"
