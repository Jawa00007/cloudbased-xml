"""Hot-patch sync.py into running container + investigate disk growth."""
import os, sys, json, time, paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HOST = "104.248.32.23"; USER = "root"
PW = os.environ.get('SII_SSH_PWD', '')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PW, timeout=15)
ssh.get_transport().set_keepalive(20)

def run(cmd, t=30):
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return o.read().decode('utf-8', errors='replace').strip()

def ok(label, good, detail=''):
    print(f"  [{'OK  ' if good else 'FAIL'}] {label}" + (f"  ->  {detail}" if detail else ''))

# ── Disk investigation ─────────────────────────────────────────────────────
print("=== DISK BREAKDOWN ===")
print(run("df -h / | tail -1"))
print()
print(run("docker exec sii-db-1 du -sh /var/lib/postgresql/data/ 2>/dev/null", 20))
print("WAL size:", run("docker exec sii-db-1 du -sh /var/lib/postgresql/data/pg_wal/ 2>/dev/null", 15))
db_size = run("docker exec sii-db-1 psql -U sii -d sii -t -c \"SELECT pg_size_pretty(pg_database_size('sii'));\"", 15)
print("DB (psql):", db_size.strip())
print("\nTop schemas:")
sizes = run(
    'docker exec sii-db-1 psql -U sii -d sii -t -c '
    '"SELECT schemaname, pg_size_pretty(SUM(pg_total_relation_size'
    "(schemaname||'.'||tablename))::bigint) "
    "FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') "
    "GROUP BY schemaname ORDER BY SUM(pg_total_relation_size(schemaname||'.'||tablename)) DESC LIMIT 8;\"",
    25
)
for line in sizes.splitlines():
    if line.strip():
        print(f"  {line.strip()}")

# ── Hot-patch sync.py ──────────────────────────────────────────────────────
print("\n=== HOT-PATCHING sync.py INTO CONTAINER ===")
grep = run("grep -n 'db_utc\\|mem_utc' /opt/sii/backend/api/routes/sync.py", 10)
ok("Fix present on server disk", bool(grep), grep if grep else "FIX NOT FOUND")

if grep:
    cp = run("docker cp /opt/sii/backend/api/routes/sync.py sii-api-1:/app/backend/api/routes/sync.py 2>&1", 10)
    print(f"  docker cp: {cp if cp else 'ok'}")
    print("  Restarting container...")
    restart = run("docker restart sii-api-1 2>&1", 30)
    print(f"  restart: {restart}")
    print("  Waiting 12s for uvicorn...")
    time.sleep(12)
else:
    print("  Skipping — fix not on server disk yet")

# ── Verify ─────────────────────────────────────────────────────────────────
print("\n=== VERIFY ===")
health = run("curl -s https://localhost/api/health --insecure", 10)
try:
    h = json.loads(health)
    ok("API health", h.get('status') == 'ok')
except Exception:
    ok("API health", False, health[:80])

token_raw = run(
    'curl -s -X POST https://localhost/api/auth/token --insecure '
    '-H "Content-Type: application/json" '
    '-d \'{"username":"admin","password":"Din@mo5055Trade"}\'', 10
)
token = json.loads(token_raw).get('access_token', '') if token_raw else ''
ok("Auth", bool(token))

if token:
    for path, label in [
        ('/sync/status',                    'GET /sync/status  (was 500)'),
        ('/accounts',                       'GET /accounts'),
        ('/admin/users',                    'GET /admin/users'),
        ('/admin/system/status',            'GET /admin/system/status'),
        ('/admin/loss-config',              'GET /admin/loss-config'),
        ('/admin/dispatching-config',       'GET /admin/dispatching-config'),
        ('/admin/anagrafica/months?account_id=CH4', 'GET /admin/anagrafica/months'),
        ('/admin/retention/log',            'GET /admin/retention/log'),
        ('/forecast/CH4/04%2F2026?limit=3', 'GET /forecast/CH4/04/2026'),
        ('/monitoring/corrections?account=CH4', 'GET /monitoring/corrections'),
    ]:
        code = run(
            f'curl -s -o /dev/null -w "%{{http_code}}" '
            f'-H "Authorization: Bearer {token}" '
            f'https://localhost/api{path} --insecure', 15
        )
        ok(label, code in ('200', '201', '204'), f"HTTP {code}")

print("\n=== FINAL DISK ===")
print(run("df -h / | tail -1"))
ssh.close()
print("\nDone.")
