#!/bin/bash
COMPOSE=/opt/sii/docker-compose.yml
LOG=/opt/sii/logs/monitor.log
MAX_LOG=50000  # bytes

# Rotate log if too large
if [ -f $LOG ] && [ $(stat -c%s $LOG) -gt $MAX_LOG ]; then
    mv $LOG ${LOG}.1
fi

API_CODE=$(curl -sk -o /dev/null -w "%{http_code}" https://localhost/api/health 2>/dev/null)
if [ "$API_CODE" != "200" ]; then
    echo "$(date): API unhealthy (HTTP $API_CODE) — restarting api..." >> $LOG
    docker compose -f $COMPOSE restart api >> $LOG 2>&1
    sleep 10
    API_CODE2=$(curl -sk -o /dev/null -w "%{http_code}" https://localhost/api/health 2>/dev/null)
    echo "$(date): API after restart: HTTP $API_CODE2" >> $LOG
fi

DB_READY=$(docker compose -f $COMPOSE exec -T db pg_isready -U sii -d sii 2>/dev/null)
if ! echo "$DB_READY" | grep -q "accepting connections"; then
    echo "$(date): DB not ready — restarting db..." >> $LOG
    docker compose -f $COMPOSE restart db >> $LOG 2>&1
fi
