#!/usr/bin/env bash
# disk_guardian.sh — Monitor disk space and auto-clean before it fills up.
# Runs every 15 minutes via cron (installed at /opt/sii/disk_monitor.sh).
#
# Watches TWO filesystems:
#   /                        — root disk (Docker images, logs, XML staging)
#   /mnt/volume_fra1_quanta  — PostgreSQL data volume (the DB lives here!)
#
# DB volume thresholds (2026-07-01 outage: volume hit 100%, PG crash-looped):
#   >= 85%: WARNING logged
#   >= 92%: CRITICAL — touch /opt/sii/data/.disk_critical sentinel (sync_sii.sh
#           refuses to start new ingests while it exists), stop backfill
#   <  92%: sentinel removed automatically
#
# Root disk thresholds:
#   > 80%: prune Docker build cache + journal
#   > 88%: also remove old backfill logs (keep last 3)
#   > 93%: aggressive prune + alert via API log WARNING

set -uo pipefail

LOGFILE=/opt/sii/logs/disk_monitor.log
DB_VOLUME=/mnt/volume_fra1_quanta
SENTINEL=/opt/sii/data/.disk_critical
mkdir -p /opt/sii/logs

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOGFILE"; }

used_pct() { df / | awk 'NR==2 {gsub(/%/,"",$5); print $5}'; }
vol_pct() { df "$DB_VOLUME" | awk 'NR==2 {gsub(/%/,"",$5); print $5}'; }

# ── DB volume check (most critical — PG crashes if this fills) ────────────────
if mountpoint -q "$DB_VOLUME"; then
    VPCT=$(vol_pct)
    if [ "$VPCT" -ge 92 ]; then
        log "CRITICAL: DB volume at ${VPCT}% — blocking syncs, stopping backfill"
        touch "$SENTINEL"
        docker stop sii-backfill 2>/dev/null && log "sii-backfill stopped" || true
    elif [ "$VPCT" -ge 85 ]; then
        log "WARNING: DB volume at ${VPCT}% — approaching capacity, plan cleanup/expansion"
        [ -f "$SENTINEL" ] && rm -f "$SENTINEL" && log "sentinel cleared (below critical)"
    else
        [ -f "$SENTINEL" ] && rm -f "$SENTINEL" && log "sentinel cleared (DB volume ${VPCT}%)"
    fi
else
    log "CRITICAL: DB volume $DB_VOLUME is NOT MOUNTED"
    touch "$SENTINEL"
fi

# ── Root disk check ────────────────────────────────────────────────────────────
PCT=$(used_pct)
log "Disk: root=${PCT}% volume=${VPCT:-n/a}%"

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
