#!/bin/bash
# SII Nightly Sync v2 — batch-pull new files from Italian server
# Downloads only unprocessed ZIPs (max BATCH_SIZE per account per run),
# ingests them (process-and-delete), never accumulates a full mirror.
#
# Cron: 30 */2 * * * /opt/sii/sync_sii.sh

ITALIAN_HOST="ubuntu@57.131.24.23"
ITALIAN_BASE="/home/ubuntu/SII_CLOUD"
SSH_KEY="/root/.ssh/italian_server"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=30 -o ServerAliveInterval=60 -o BatchMode=yes"
LOCAL_DATA="/opt/sii/data"
LOGFILE="/var/log/sii-sync.log"
BATCH_SIZE=${BATCH_SIZE_OVERRIDE:-10000}
MIN_FREE_GB=3

ACCOUNTS="BAT CH4 DINAMO EGOGREEN ENERGETICA ENERGIT ENJOY ONDA POWERIT ROYAL SOS TOP"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
free_gb() { df -BG / | awk 'NR==2 {gsub("G","",$4); print $4}'; }

schema_for() {
    case $1 in
        DINAMO*)   echo dinamo_trade ;;
        ENJOY*)    echo enjoy_energy ;;
        ONDA*)     echo onda_piu ;;
        POWERIT*)  echo power_it ;;
        ROYAL*)    echo royal_group ;;
        TOP*)      echo top_energy ;;
        *)         echo "$(echo $1 | tr '[:upper:]' '[:lower:]')" ;;
    esac
}

exec >> "$LOGFILE" 2>&1

# Skip if backfill is running (only applies to cron; backfill itself sets BATCH_SIZE_OVERRIDE)
if [ -z "$BATCH_SIZE_OVERRIDE" ] && \
   [ -f "$LOCAL_DATA/.backfill_status.json" ] && \
   grep -qE '"running":\s*true' "$LOCAL_DATA/.backfill_status.json" 2>/dev/null; then
    log "Backfill running — nightly sync skipped"
    exit 0
fi

FREE=$(free_gb)
if [ "$FREE" -lt "$MIN_FREE_GB" ]; then
    log "ABORT: ${FREE}GB free < ${MIN_FREE_GB}GB minimum"
    exit 1
fi

log "=== SII sync started | ${FREE}GB free ==="
TMPDIR_WORK=$(mktemp -d)
trap 'rm -rf "$TMPDIR_WORK"' EXIT

TOTAL_NEW=0

DATE_FROM=$(date -d "$(date +%Y-%m-01) -12 months" +%Y%m)
DATE_TO=$(date +%Y%m)

for ACC in $ACCOUNTS; do
    SCHEMA=$(schema_for $ACC)

    # List remote ZIPs (relative paths from ITALIAN_BASE/ACC/)
    REMOTE_PATHS=$TMPDIR_WORK/${ACC}_paths.txt
    if ! ssh $SSH_OPTS $ITALIAN_HOST \
        "cd '${ITALIAN_BASE}/${ACC}' 2>/dev/null && find . -name '*.xml.zip' -printf '%P\n' | sort" \
        > $REMOTE_PATHS 2>/dev/null; then
        log "$ACC: WARNING - Italian server unreachable"
        continue
    fi
    REMOTE_COUNT=$(wc -l < $REMOTE_PATHS)
    [ $REMOTE_COUNT -eq 0 ] && continue

    # Filter to rolling 12-month retention window: AAAAMM (3rd _-field of basename)
    DATE_FILTERED=$TMPDIR_WORK/${ACC}_filtered.txt
    awk -F'/' -v from="$DATE_FROM" -v to="$DATE_TO" '{
        fname = $NF
        n = split(fname, p, "_")
        if (n >= 3 && length(p[3]) == 6 && p[3] >= from && p[3] <= to) print $0
    }' "$REMOTE_PATHS" > "$DATE_FILTERED"
    REMOTE_PATHS=$DATE_FILTERED
    REMOTE_COUNT=$(wc -l < "$REMOTE_PATHS")
    [ "$REMOTE_COUNT" -eq 0 ] && { log "$ACC: no files in date window ($DATE_FROM-$DATE_TO)"; continue; }

    # Get processed names from DB
    PROCESSED_LIST=$TMPDIR_WORK/${ACC}_processed.txt
    docker exec sii-db-1 psql -U sii -d sii -t -A -c \
        "SELECT file_name FROM ${SCHEMA}.files WHERE status='ok'" \
        > $PROCESSED_LIST 2>/dev/null || touch $PROCESSED_LIST
    sort -o $PROCESSED_LIST $PROCESSED_LIST

    # Find unprocessed: strip .zip, compare with DB, take up to BATCH_SIZE
    TODO_LIST=$TMPDIR_WORK/${ACC}_todo.txt
    sed 's|.*/||; s/\.zip$//' $REMOTE_PATHS | sort \
        | comm -23 - $PROCESSED_LIST | head -$BATCH_SIZE > $TODO_LIST
    TODO_COUNT=$(wc -l < $TODO_LIST)

    if [ $TODO_COUNT -eq 0 ]; then
        log "$ACC: up to date"
        continue
    fi
    log "$ACC: $TODO_COUNT new files"
    TOTAL_NEW=$((TOTAL_NEW + TODO_COUNT))

    # Build lookup and rsync file list
    LOOKUP=$TMPDIR_WORK/${ACC}_lookup.txt
    awk -F/ '{fname=$NF; sub(/\.zip$/,"",fname); print fname" "$0}' $REMOTE_PATHS | sort -k1,1 > $LOOKUP

    RSYNC_FILES=$TMPDIR_WORK/${ACC}_rsync.txt
    sort $TODO_LIST | join - $LOOKUP | awk '{print $2}' > $RSYNC_FILES
    RSYNC_COUNT=$(wc -l < $RSYNC_FILES)
    [ $RSYNC_COUNT -eq 0 ] && continue

    mkdir -p $LOCAL_DATA/$ACC
    rsync -az --files-from=$RSYNC_FILES \
        -e "ssh $SSH_OPTS" \
        "${ITALIAN_HOST}:${ITALIAN_BASE}/${ACC}/" \
        "$LOCAL_DATA/$ACC/" 2>&1 | tail -2

    log "$ACC: ingesting $RSYNC_COUNT files..."
    docker exec sii-api-1 python -m backend.ingestion.ingest --account=$ACC 2>&1 | tail -3
    log "$ACC: done"
done

log "=== Sync complete | $TOTAL_NEW new files | $(free_gb)GB free ==="
