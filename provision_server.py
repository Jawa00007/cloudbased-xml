"""
Full production server setup for SII Energy Platform on DigitalOcean.

What this does:
  1. Complete Supabase -> local PostgreSQL data migration (per-account schemas)
  2. Deploy updated docker-compose (Adminer, SSL-ready nginx)
  3. Create automated daily backup with 14-day retention
  4. Create systemd service for auto-start on reboot
  5. Create monitoring cron (restart API if unhealthy)
  6. Create rsync data-sync script (for XML data files from Nextcloud)
  7. Create Adminer password protection via nginx basic auth

Run: py provision_server.py
"""
import paramiko, time, sys, os

HOST = "104.248.32.23"
KEY  = r"C:\Users\jawad\.ssh\do_sii"
LOCAL_ROOT = r"C:\Users\jawad\Documents\CloudBased XML"


def run(client, cmd, timeout=120, show=True):
    label = cmd[:100] + ("..." if len(cmd) > 100 else "")
    print(f">>> {label}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    code = stdout.channel.recv_exit_status()
    if out and show:
        print(out)
    if err and code != 0 and show:
        print("[err]", err[:600])
    return code, out


def upload(sftp, local_path, remote_path):
    sftp.put(local_path, remote_path)
    print(f"    Uploaded {os.path.basename(local_path)} -> {remote_path}")


client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print(f"Connecting to {HOST}...")
client.connect(HOST, username="root", key_filename=KEY, timeout=15)
print("Connected.\n")


# ── Step 1: Upload updated docker-compose + nginx ─────────────────────────────
print("=" * 60)
print("Step 1: Upload updated config files")
print("=" * 60)
sftp = client.open_sftp()
upload(sftp, os.path.join(LOCAL_ROOT, "docker-compose.yml"), "/opt/sii/docker-compose.yml")
upload(sftp, os.path.join(LOCAL_ROOT, "nginx.conf"), "/opt/sii/nginx.conf")
sftp.close()

# Create ssl directory (empty, ready for certs)
run(client, "mkdir -p /opt/sii/ssl /opt/sii/backups /opt/sii/logs")

# Restart stack with new services
print("\nRestarting stack with updated config...")
run(client, "cd /opt/sii && docker compose up -d --remove-orphans", timeout=120)
time.sleep(5)
rc, health = run(client, "curl -s http://localhost/health")
print(f"API health: {health}")


# ── Step 2: Data migration — per-account schemas ──────────────────────────────
print("\n" + "=" * 60)
print("Step 2: Complete Supabase -> local PostgreSQL migration")
print("=" * 60)

# Upload and inject fix_schemas.py into the api container
sftp = client.open_sftp()
upload(sftp, os.path.join(LOCAL_ROOT, "fix_schemas.py"), "/opt/sii/fix_schemas.py")
sftp.close()

rc, container_id = run(client,
    "docker compose -f /opt/sii/docker-compose.yml ps -q api", timeout=15)
container_id = container_id.strip()
print(f"API container: {container_id[:12]}")

run(client, f"docker cp /opt/sii/fix_schemas.py {container_id}:/fix_schemas.py")

# Start migration in background inside container
run(client,
    f'docker exec {container_id} sh -c '
    f'"python /fix_schemas.py > /tmp/fix_schemas.log 2>&1 &"',
    timeout=30, show=True)

print("Migration started in background. Polling progress every 30s...")
for attempt in range(40):  # up to 20 minutes
    time.sleep(30)
    rc2, log = run(client, f"docker exec {container_id} tail -5 /tmp/fix_schemas.log",
                   timeout=15, show=False)
    rc_running, ps = run(client,
        f"docker exec {container_id} sh -c 'ps aux | grep fix_schemas | grep -v grep'",
        timeout=10, show=False)
    still_running = rc_running == 0 and ps.strip()
    print(f"  [{attempt+1:2d}] {log.split(chr(10))[-1] if log else '(no output yet)'}")
    if not still_running and log.strip().endswith("Done."):
        print("Migration finished!")
        break
    if not still_running and attempt > 0:
        print("Process ended — checking full log:")
        run(client, f"docker exec {container_id} cat /tmp/fix_schemas.log",
            timeout=30, show=True)
        break

# Show final log tail
run(client, f"docker exec {container_id} tail -20 /tmp/fix_schemas.log", timeout=15)


# ── Step 3: Daily backup ──────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Step 3: Configure automated daily backup")
print("=" * 60)

backup_script = r"""#!/bin/bash
set -e
BACKUP_DIR=/opt/sii/backups
COMPOSE=/opt/sii/docker-compose.yml
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG=$BACKUP_DIR/backup.log

echo "$(date): Starting backup..." >> $LOG

# pg_dumpall from inside db container
docker compose -f $COMPOSE exec -T db \
    pg_dumpall -U sii \
    | gzip > $BACKUP_DIR/sii_${TIMESTAMP}.sql.gz

SIZE=$(du -sh $BACKUP_DIR/sii_${TIMESTAMP}.sql.gz | cut -f1)
echo "$(date): Backup saved: sii_${TIMESTAMP}.sql.gz ($SIZE)" >> $LOG

# Rotate: keep only the 14 most recent backups
ls -t $BACKUP_DIR/sii_*.sql.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
echo "$(date): Rotation complete." >> $LOG
"""

restore_script = r"""#!/bin/bash
# Usage: restore.sh <backup_file.sql.gz>
# Example: restore.sh /opt/sii/backups/sii_20250101_030000.sql.gz
if [ -z "$1" ]; then
    echo "Usage: $0 <backup_file.sql.gz>"
    ls /opt/sii/backups/sii_*.sql.gz 2>/dev/null | sort -r | head -5
    exit 1
fi
echo "WARNING: This will overwrite the current database. Press Ctrl+C to cancel..."
sleep 5
gunzip -c "$1" | docker compose -f /opt/sii/docker-compose.yml exec -T db psql -U sii
echo "Restore complete."
"""

sftp = client.open_sftp()
with sftp.open("/opt/sii/backup.sh", "w") as f:
    f.write(backup_script)
with sftp.open("/opt/sii/restore.sh", "w") as f:
    f.write(restore_script)
sftp.close()

run(client, "chmod +x /opt/sii/backup.sh /opt/sii/restore.sh")

# Add cron job: daily at 03:00
cron_line = "0 3 * * * root /opt/sii/backup.sh\n"
run(client, f"echo '{cron_line.strip()}' > /etc/cron.d/sii-backup")
run(client, "chmod 644 /etc/cron.d/sii-backup")
print("Daily backup cron set for 03:00.")

# Run one backup immediately to verify
print("Running initial backup to verify...")
rc, _ = run(client, "/opt/sii/backup.sh", timeout=120)
if rc == 0:
    run(client, "ls -lh /opt/sii/backups/")
else:
    print("Backup had issues — check /opt/sii/backups/backup.log")


# ── Step 4: systemd service ───────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Step 4: Configure systemd service for auto-start")
print("=" * 60)

systemd_service = """[Unit]
Description=SII Energy Platform (Docker Compose)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/sii
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=180
Restart=on-failure
RestartSec=10s

[Install]
WantedBy=multi-user.target
"""

sftp = client.open_sftp()
with sftp.open("/etc/systemd/system/sii.service", "w") as f:
    f.write(systemd_service)
sftp.close()

run(client, "systemctl daemon-reload")
run(client, "systemctl enable sii.service")
print("systemd service enabled — stack will auto-start on reboot.")


# ── Step 5: Monitoring cron ───────────────────────────────────────────────────
print("\n" + "=" * 60)
print("Step 5: Configure health monitoring")
print("=" * 60)

monitor_script = r"""#!/bin/bash
COMPOSE=/opt/sii/docker-compose.yml
LOG=/opt/sii/logs/monitor.log
MAX_LOG=50000  # bytes

# Rotate log if too large
if [ -f $LOG ] && [ $(stat -c%s $LOG) -gt $MAX_LOG ]; then
    mv $LOG ${LOG}.1
fi

API_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/health 2>/dev/null)
if [ "$API_CODE" != "200" ]; then
    echo "$(date): API unhealthy (HTTP $API_CODE) — restarting api..." >> $LOG
    docker compose -f $COMPOSE restart api >> $LOG 2>&1
    sleep 10
    API_CODE2=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/health 2>/dev/null)
    echo "$(date): API after restart: HTTP $API_CODE2" >> $LOG
fi

DB_READY=$(docker compose -f $COMPOSE exec -T db pg_isready -U sii -d sii 2>/dev/null)
if ! echo "$DB_READY" | grep -q "accepting connections"; then
    echo "$(date): DB not ready — restarting db..." >> $LOG
    docker compose -f $COMPOSE restart db >> $LOG 2>&1
fi
"""

sftp = client.open_sftp()
with sftp.open("/opt/sii/monitor.sh", "w") as f:
    f.write(monitor_script)
sftp.close()
run(client, "chmod +x /opt/sii/monitor.sh")

# Check every 5 minutes
run(client, "echo '*/5 * * * * root /opt/sii/monitor.sh' > /etc/cron.d/sii-monitor")
run(client, "chmod 644 /etc/cron.d/sii-monitor")
print("Monitoring cron set: every 5 minutes.")


# ── Step 6: rsync script for XML data files ───────────────────────────────────
print("\n" + "=" * 60)
print("Step 6: rsync script for XML data sync")
print("=" * 60)

rsync_script = """#!/bin/bash
# rsync-data.sh — Sync XML data files from a remote source to /opt/sii/data/
#
# Usage: rsync-data.sh [source_host]
# Example: rsync-data.sh user@nextcloud-server:/path/to/data/
#
# Set SOURCE below or pass it as the first argument.
# This runs on the DO server after VPN is connected.
#
SOURCE="${1:-}"  # e.g. user@host:/remote/data/
DEST=/opt/sii/data/
LOG=/opt/sii/logs/rsync.log

if [ -z "$SOURCE" ]; then
    echo "Usage: $0 <user@host:/path/to/data/>"
    echo "Example: $0 root@nas:/mnt/sii_data/"
    exit 1
fi

echo "$(date): Starting rsync from $SOURCE" >> $LOG
rsync -avz --progress \\
    --include='*/' \\
    --include='*.xml' \\
    --include='*.xml.zip' \\
    --include='*.csv' \\
    --exclude='*' \\
    "$SOURCE" "$DEST" >> $LOG 2>&1

echo "$(date): rsync complete (exit $?)" >> $LOG
"""

sftp = client.open_sftp()
with sftp.open("/opt/sii/rsync-data.sh", "w") as f:
    f.write(rsync_script)
sftp.close()
run(client, "chmod +x /opt/sii/rsync-data.sh")
print("rsync script created at /opt/sii/rsync-data.sh")


# ── Step 7: Adminer basic-auth password protection ───────────────────────────
print("\n" + "=" * 60)
print("Step 7: Protect Adminer with HTTP basic auth")
print("=" * 60)

# Install apache2-utils for htpasswd
run(client, "apt-get install -y -qq apache2-utils 2>/dev/null")
# Create credentials: admin / Din@mo5055Trade
run(client, "htpasswd -bc /opt/sii/.htpasswd admin 'Din@mo5055Trade'")

# Update nginx.conf to add auth_basic for /adminer/
nginx_with_auth = r"""server {
    listen 80;
    server_name _;

    # Let's Encrypt ACME challenge
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    proxy_read_timeout 180s;
    proxy_send_timeout 180s;

    # Adminer — password protected
    location /adminer/ {
        auth_basic           "SII Database Admin";
        auth_basic_user_file /etc/nginx/.htpasswd;
        proxy_pass           http://adminer:8080/;
        proxy_set_header     Host $host;
        proxy_set_header     X-Real-IP $remote_addr;
        proxy_set_header     X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header     X-Forwarded-Proto $scheme;
    }

    # FastAPI backend
    location / {
        proxy_pass         http://api:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_buffering    off;
    }
}
"""

sftp = client.open_sftp()
with sftp.open("/opt/sii/nginx.conf", "w") as f:
    f.write(nginx_with_auth)
sftp.close()

# Mount .htpasswd into nginx container — update docker-compose
# (done by adding it to nginx volumes)
print("Updating docker-compose to mount .htpasswd into nginx...")

docker_compose_final = """services:
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: sii
      POSTGRES_USER: sii
      POSTGRES_PASSWORD: sii_db_2024
    volumes:
      - pgdata:/var/lib/postgresql/data
    networks:
      - internal
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sii -d sii"]
      interval: 5s
      timeout: 5s
      retries: 10

  api:
    build: .
    restart: unless-stopped
    env_file: .env
    expose:
      - "8000"
    volumes:
      - ./data:/app/data
    networks:
      - internal
    depends_on:
      db:
        condition: service_healthy

  nginx:
    image: nginx:alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./.htpasswd:/etc/nginx/.htpasswd:ro
      - ./ssl:/etc/nginx/ssl:ro
      - certbot_webroot:/var/www/certbot:ro
    depends_on:
      - api
      - adminer
    networks:
      - internal

  adminer:
    image: adminer:latest
    restart: unless-stopped
    environment:
      ADMINER_DEFAULT_SERVER: db
      ADMINER_DESIGN: pepa-linha
    networks:
      - internal

networks:
  internal:

volumes:
  pgdata:
  certbot_webroot:
"""

with sftp.open("/opt/sii/docker-compose.yml", "w") as f:
    f.write(docker_compose_final)
sftp.close()

# Update local docker-compose too
local_dc_path = os.path.join(LOCAL_ROOT, "docker-compose.yml")
with open(local_dc_path, "w", encoding="utf-8") as f:
    f.write(docker_compose_final)
print("docker-compose.yml updated with .htpasswd mount.")

# Update local nginx.conf too
local_nginx_path = os.path.join(LOCAL_ROOT, "nginx.conf")
with open(local_nginx_path, "w", encoding="utf-8") as f:
    f.write(nginx_with_auth)

# Restart nginx to pick up new config
run(client, "cd /opt/sii && docker compose up -d --remove-orphans nginx", timeout=60)
time.sleep(3)
rc, health = run(client, "curl -s http://localhost/health")
print(f"API health after nginx restart: {health}")


# ── Final summary ─────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("PROVISIONING COMPLETE")
print("=" * 60)
print(f"""
Services running:
  API       http://{HOST}/health
  Adminer   http://{HOST}/adminer/  (login: admin / Din@mo5055Trade)

Automation:
  Backups   daily at 03:00 -> /opt/sii/backups/ (14-day retention)
  Restore   /opt/sii/restore.sh <backup_file.sql.gz>
  Monitor   every 5 min -> /opt/sii/logs/monitor.log
  Rsync     /opt/sii/rsync-data.sh <user@host:/path/>

Auto-start:
  systemctl status sii  (starts docker compose on reboot)

SSL (when you attach a domain):
  1. Point DNS A record to {HOST}
  2. apt install certbot python3-certbot-nginx
  3. certbot --nginx -d yourdomain.com
  4. Uncomment SSL block in nginx.conf and docker compose up -d nginx
""")

client.close()
