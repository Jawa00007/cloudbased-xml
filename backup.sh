#!/bin/bash
set -e
BACKUP_DIR=/opt/sii/backups
COMPOSE=/opt/sii/docker-compose.yml
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG=$BACKUP_DIR/backup.log

echo "$(date): Starting backup..." >> $LOG

docker compose -f $COMPOSE exec -T db \
    pg_dumpall -U sii \
    | gzip > $BACKUP_DIR/sii_${TIMESTAMP}.sql.gz

SIZE=$(du -sh $BACKUP_DIR/sii_${TIMESTAMP}.sql.gz | cut -f1)
echo "$(date): Backup saved: sii_${TIMESTAMP}.sql.gz ($SIZE)" >> $LOG

# Rotate: keep only the 5 most recent backups (DB now ~700 GB+; each dump ~18 GB compressed)
ls -t $BACKUP_DIR/sii_*.sql.gz 2>/dev/null | tail -n +6 | xargs -r rm -f
echo "$(date): Rotation complete." >> $LOG
