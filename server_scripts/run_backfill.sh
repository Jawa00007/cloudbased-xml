#!/usr/bin/env bash
# Batch-pull backfill v2 — fetches unprocessed ZIPs from Italian server in small
# batches (~BATCH_SIZE files), processes each (ingest -> delete), then continues.
# Never keeps more than BATCH_SIZE ZIPs on disk at once (~18 MB typical).
#
# Usage: nohup /opt/sii/run_backfill.sh >> /opt/sii/logs/backfill_nohup.log 2>&1 &
# Stop:  pkill -f run_backfill.sh

set -uo pipefail

LOGDIR=/opt/sii/logs
LOGFILE=$LOGDIR/backfill_$(date +%Y%m%d_%H%M%S).log
mkdir -p $LOGDIR
ln -sf $LOGFILE $LOGDIR/backfill_latest.log

ITALIAN_HOST="ubuntu@57.131.24.23"
ITALIAN_BASE="/home/ubuntu/SII_CLOUD"
SSH_KEY="/root/.ssh/italian_server"
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=30 -o ServerAliveInterval=60 -o BatchMode=yes"

HOST_DATA=/opt/sii/data
CONTAINER_DATA=/app/data
STATUS_FILE=$HOST_DATA/.backfill_status.json
ENV_FILE=/opt/sii/.env
IMAGE=sii-api:latest

BATCH_SIZE=500
MIN_FREE_GB=3

ACCOUNTS="BAT CH4 DINAMO EGOGREEN ENERGETICA ENERGIT ENJOY ONDA POWERIT ROYAL SOS TOP"

log()     { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a $LOGFILE; }
free_gb() { df -BG / | awk 'NR==2 {gsub("G","",$4); print $4}'; }

check_disk() {
    FREE=$(free_gb)
    if [ "$FREE" -lt "$MIN_FREE_GB" ]; then
        log "ABORT: ${FREE}GB free < ${MIN_FREE_GB}GB minimum"
        rm -f $STATUS_FILE
        exit 2
    fi
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

write_status() {
    ACC=$1; DONE=$2; TOTAL=$3; ACC_IDX=$4; ACC_TOTAL=$5
    printf '{"running":true,"current":"%s","started":"%s","files_done":%d,"files_total":%d,"accounts_done":%d,"accounts_total":%d}\n' \
        "$ACC" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$DONE" "$TOTAL" "$ACC_IDX" "$ACC_TOTAL" > $STATUS_FILE
}

if docker ps --format '{{.Names}}' | grep -q '^sii-backfill$'; then
    echo "ERROR: sii-backfill container already running."; exit 1
fi
rm -f $STATUS_FILE

TMPDIR_WORK=$(mktemp -d)
trap 'rm -rf "$TMPDIR_WORK"; rm -f "$STATUS_FILE"; log "=== BACKFILL EXITED ==="' EXIT

log "=== BATCH-PULL BACKFILL START | $(free_gb)GB free ==="
log "Italian: $ITALIAN_HOST:$ITALIAN_BASE  batch=$BATCH_SIZE"

ACCOUNT_LIST=($ACCOUNTS)
TOTAL_ACCOUNTS=${#ACCOUNT_LIST[@]}

for i in "${!ACCOUNT_LIST[@]}"; do
    ACC=${ACCOUNT_LIST[$i]}
    SCHEMA=$(schema_for $ACC)
    check_disk

    log "---- $ACC (schema: $SCHEMA) ----"

    # 1. List remote ZIPs as relative paths from ITALIAN_BASE/ACC/
    REMOTE_PATHS=$TMPDIR_WORK/${ACC}_remote.txt
    log "$ACC: listing Italian server..."
    if ! ssh $SSH_OPTS $ITALIAN_HOST \
        "cd '${ITALIAN_BASE}/${ACC}' 2>/dev/null && find . -name '*.xml.zip' -printf '%P\n' | sort" \
        > $REMOTE_PATHS 2>/dev/null; then
        log "$ACC: WARNING - cannot reach Italian server, skipping"
        continue
    fi
    REMOTE_TOTAL=$(wc -l < $REMOTE_PATHS)
    log "$ACC: $REMOTE_TOTAL ZIPs on Italian server"
    [ $REMOTE_TOTAL -eq 0 ] && { log "$ACC: no files on Italian server, skipping"; continue; }

    # 2. Get already-processed xml names from DB
    #    DB stores file_name = zip_stem (zip filename minus .zip extension)
    PROCESSED_LIST=$TMPDIR_WORK/${ACC}_processed.txt
    log "$ACC: querying DB..."
    docker exec sii-db-1 psql -U sii -d sii -t -A -c \
        "SELECT file_name FROM ${SCHEMA}.files WHERE status='ok'" \
        > $PROCESSED_LIST 2>/dev/null || touch $PROCESSED_LIST
    sort -o $PROCESSED_LIST $PROCESSED_LIST
    PROCESSED_COUNT=$(wc -l < $PROCESSED_LIST)
    log "$ACC: $PROCESSED_COUNT processed in DB"

    # 3. Find unprocessed: strip .zip from remote filenames, diff with DB
    #    sed extracts basename and strips .zip; result is xml_name (matches DB file_name)
    TODO_LIST=$TMPDIR_WORK/${ACC}_todo.txt
    sed 's|.*/||; s/\.zip$//' $REMOTE_PATHS | sort \
        | comm -23 - $PROCESSED_LIST > $TODO_LIST
    TODO_COUNT=$(wc -l < $TODO_LIST)
    log "$ACC: $TODO_COUNT files to process"
    [ $TODO_COUNT -eq 0 ] && { log "$ACC: all up to date"; continue; }

    # 4. Build lookup: xml_name -> relative_zip_path (sorted by xml_name for join)
    LOOKUP=$TMPDIR_WORK/${ACC}_lookup.txt
    awk -F/ '{fname=$NF; sub(/\.zip$/,"",fname); print fname" "$0}' $REMOTE_PATHS | sort -k1,1 > $LOOKUP
    log "$ACC: lookup built ($(wc -l < $LOOKUP) entries)"

    # 5. Process in batches
    DONE=0
    BATCH_NUM=0
    while [ $DONE -lt $TODO_COUNT ]; do
        check_disk
        BATCH_NUM=$((BATCH_NUM + 1))

        BATCH_NAMES=$TMPDIR_WORK/${ACC}_batch_names.txt
        tail -n +$((DONE + 1)) $TODO_LIST | head -$BATCH_SIZE | sort > $BATCH_NAMES
        BATCH_COUNT=$(wc -l < $BATCH_NAMES)
        [ $BATCH_COUNT -eq 0 ] && break

        log "$ACC: batch $BATCH_NUM - $BATCH_COUNT files ($(free_gb)GB free)"

        # Resolve xml names -> zip relative paths via join
        RSYNC_FILES=$TMPDIR_WORK/${ACC}_rsync.txt
        join $BATCH_NAMES $LOOKUP | awk '{print $2}' > $RSYNC_FILES
        RSYNC_COUNT=$(wc -l < $RSYNC_FILES)

        if [ $RSYNC_COUNT -gt 0 ]; then
            log "$ACC: downloading $RSYNC_COUNT ZIPs from Italian server..."
            mkdir -p $HOST_DATA/$ACC
            rsync -az --files-from=$RSYNC_FILES \
                -e "ssh $SSH_OPTS" \
                "${ITALIAN_HOST}:${ITALIAN_BASE}/${ACC}/" \
                "$HOST_DATA/$ACC/" 2>&1 | tail -3 | while IFS= read -r line; do log "  rsync: $line"; done

            log "$ACC: ingesting batch $BATCH_NUM..."
            docker run --rm \
                --name sii-backfill \
                --network sii_internal \
                --env-file $ENV_FILE \
                -v $HOST_DATA:$CONTAINER_DATA \
                $IMAGE \
                python -m backend.ingestion.ingest --account=$ACC 2>&1 \
                | tail -5 | while IFS= read -r line; do log "  ingest: $line"; done
        else
            log "$ACC: batch $BATCH_NUM - no paths resolved (files may be missing on Italian server)"
        fi

        DONE=$((DONE + BATCH_COUNT))
        write_status "$ACC" "$DONE" "$REMOTE_TOTAL" "$i" "$TOTAL_ACCOUNTS"
        log "$ACC: $DONE/$TODO_COUNT todo-done, $(( PROCESSED_COUNT + DONE ))/$REMOTE_TOTAL total | $(free_gb)GB free"
    done

    log "$ACC: COMPLETE"
done

rm -f $STATUS_FILE
log "=== BACKFILL COMPLETE | $(free_gb)GB free ==="
