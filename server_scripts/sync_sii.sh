#!/bin/bash
# SII Nightly Sync v3 — batch-pull new files from Italian server, then chain a
# full re-check (all-accounts ingest_all) once the pull finishes. Downloads only
# unprocessed ZIPs (max BATCH_SIZE per account per run), ingests them
# (process-and-delete), never accumulates a full mirror.
#
# Cron: 0 2 * * * /opt/sii/sync_sii.sh
#
# Sequence: pull+ingest each account (synchronous, existing behavior) -> once
# every account's triggered ingestion has actually finished, trigger one
# all-accounts POST /api/sync as a full re-check. This also retries any file
# that errored during the per-account phase, since ingest_all()/ingest_account()
# never delete status='error' files.

ITALIAN_HOST="ubuntu@57.131.24.23"
ITALIAN_BASE="/home/ubuntu/SII_CLOUD"
SSH_KEY="/root/.ssh/italian_server"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=30 -o ServerAliveInterval=60 -o BatchMode=yes"
LOCAL_DATA="/opt/sii/data"
LOGFILE="/var/log/sii-sync.log"
BATCH_SIZE=${BATCH_SIZE_OVERRIDE:-10000}
MIN_FREE_GB=3
DB_VOLUME="/mnt/volume_fra1_quanta"
MIN_VOLUME_FREE_GB=30
SENTINEL="$LOCAL_DATA/.disk_critical"

# Fetch active accounts from public.accounts table (includes any newly-added accounts)
# Falls back to hardcoded list if DB is unavailable
_DB_ACCOUNTS=$(docker exec sii-db-1 psql -U sii -d sii -t -A -c \
  "SELECT account_id FROM public.accounts WHERE active = true ORDER BY account_id" \
  2>/dev/null | tr '\n' ' ' | xargs)
ACCOUNTS=${_DB_ACCOUNTS:-"BAT CH4 DINAMO EGOGREEN ENERGETICA ENERGIT ENJOY ONDA POWERIT ROYAL SOS TOP"}

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
free_gb() { df -BG / | awk 'NR==2 {gsub("G","",$4); print $4}'; }
volume_free_gb() { df -BG "$DB_VOLUME" 2>/dev/null | awk 'NR==2 {gsub("G","",$4); print $4}'; }

# Poll /api/sync/status every 15s until the ingestion guard is idle (max $1
# seconds, default 8h). Returns 1 on timeout so callers can log a warning
# instead of hanging forever.
_wait_idle() {
    local max_wait=${1:-28800}
    local waited=0
    while [ "$waited" -lt "$max_wait" ]; do
        sleep 15; waited=$((waited + 15))
        local running
        running=$(curl -sk -H "X-API-Key: $API_KEY" "https://localhost/api/sync/status" 2>/dev/null \
            | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print('yes' if any(x.get('running') for x in d) else 'no')
except Exception:
    print('yes')
" 2>/dev/null)
        [ "$running" = "no" ] && return 0
    done
    return 1
}

# Files that errored during ingestion for a given account (post-run check).
_account_error_count() {
    curl -sk -H "X-API-Key: $API_KEY" "https://localhost/api/sync/status" 2>/dev/null \
        | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    row = next((x for x in d if x.get('account_id') == '$1'), None)
    print(int(row.get('files_error') or 0) if row else 0)
except Exception:
    print(0)
" 2>/dev/null
}

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

# Prevent concurrent runs — only one instance at a time
LOCKFILE="/var/run/sync_sii.lock"
if [ -f "$LOCKFILE" ]; then
    OLD_PID=$(cat "$LOCKFILE" 2>/dev/null)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        log "Another sync_sii.sh (PID $OLD_PID) is running — skipping"
        exit 0
    fi
fi
echo $$ > "$LOCKFILE"
trap 'rm -f "$LOCKFILE"' EXIT

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

# DB volume guard — ingesting fills the PostgreSQL volume, not the root disk.
# 2026-07-01 outage: volume hit 100% and PG crash-looped; root disk was fine.
if [ -f "$SENTINEL" ]; then
    log "ABORT: disk-critical sentinel present ($SENTINEL) — DB volume too full for ingestion"
    exit 1
fi
VFREE=$(volume_free_gb)
if [ -z "$VFREE" ]; then
    log "ABORT: cannot read DB volume free space ($DB_VOLUME not mounted?)"
    exit 1
fi
if [ "$VFREE" -lt "$MIN_VOLUME_FREE_GB" ]; then
    log "ABORT: DB volume ${VFREE}GB free < ${MIN_VOLUME_FREE_GB}GB minimum — clean up or expand volume"
    exit 1
fi

log "=== SII sync started | root ${FREE}GB free | DB volume ${VFREE}GB free ==="
TMPDIR_WORK=$(mktemp -d)
trap 'rm -rf "$TMPDIR_WORK"' EXIT

API_KEY=$(grep '^API_KEY=' /opt/sii/.env | cut -d= -f2- | tr -d '\r\n' 2>/dev/null)

TOTAL_NEW=0
TOTAL_ERRORS=0
ERROR_ACCOUNTS=""

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
    rsync_out=$(rsync -az --files-from="$RSYNC_FILES" \
        -e "ssh $SSH_OPTS" \
        "${ITALIAN_HOST}:${ITALIAN_BASE}/${ACC}/" \
        "$LOCAL_DATA/$ACC/" 2>&1)
    rsync_exit=$?
    echo "$rsync_out" | tail -5
    if [ "$rsync_exit" -ne 0 ]; then
        log "$ACC: WARNING — rsync exited $rsync_exit (partial transfer); missing files will retry next sync run"
    fi

    log "$ACC: ingesting $RSYNC_COUNT files..."
    _HTTP=$(curl -sk -o /dev/null -w "%{http_code}" -X POST \
        -H "X-API-Key: $API_KEY" "https://localhost/api/sync/$ACC" 2>/dev/null)
    if [ "$_HTTP" = "200" ] || [ "$_HTTP" = "202" ]; then
        if ! _wait_idle 28800; then
            log "$ACC: WARNING — still running after 8h wait, moving on without checking errors"
        else
            _ERR=$(_account_error_count "$ACC")
            _ERR=${_ERR:-0}
            if [ "$_ERR" -gt 0 ] 2>/dev/null; then
                log "$ACC: WARNING — $_ERR file(s) failed ingestion (retried automatically by the full re-check below)"
                ERROR_ACCOUNTS="$ERROR_ACCOUNTS $ACC($_ERR)"
                TOTAL_ERRORS=$((TOTAL_ERRORS + _ERR))
            fi
        fi
    elif [ "$_HTTP" = "409" ]; then
        # API lock held by another sync — skip this account, retry next cron run
        log "$ACC: API busy (409) — another sync is running, skipping until next cron run"
    else
        # API unavailable (5xx, timeout) — skip, retry next cron run.
        # Never fall back to docker exec: it bypasses the ingestion guard,
        # has no BATCH_SIZE limit, and blocks all subsequent cron slots for hours.
        log "$ACC: API returned HTTP $_HTTP — skipping, will retry next cron run"
    fi
    log "$ACC: done"
done

if [ -n "$ERROR_ACCOUNTS" ]; then
    log "=== Sync complete | $TOTAL_NEW new files | $TOTAL_ERRORS error(s) —$ERROR_ACCOUNTS | $(free_gb)GB free ==="
else
    log "=== Sync complete | $TOTAL_NEW new files | 0 errors | $(free_gb)GB free ==="
fi

# Full re-check — only after every account's triggered ingestion has actually
# finished (the per-account loop above is synchronous, so this always runs
# strictly after the pull). Also retries anything that errored above, since
# ingest_all()/ingest_account() never delete status='error' files.
log "Triggering full re-check (all accounts) ..."
_HTTP=$(curl -sk -o /dev/null -w "%{http_code}" -X POST -H "X-API-Key: $API_KEY" "https://localhost/api/sync" 2>/dev/null)
if [ "$_HTTP" = "200" ] || [ "$_HTTP" = "202" ]; then
    if _wait_idle 28800; then
        log "Full re-check complete"
    else
        log "WARNING: full re-check still running after 8h wait — leaving it to finish in the background"
    fi
elif [ "$_HTTP" = "409" ]; then
    log "WARNING: full re-check skipped — ingestion lock unexpectedly busy right after per-account sync finished"
else
    log "WARNING: full re-check failed to start (HTTP $_HTTP) — the 05:00 UTC scheduler fallback will still run today"
fi

log "=== Nightly sync + full re-check finished | $(free_gb)GB free ==="
