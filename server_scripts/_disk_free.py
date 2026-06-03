"""Check disk usage, prune Docker cache, restart API, verify sync/status."""
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

print("=== DISK BEFORE ===")
print(run("df -h / | tail -1"))

print("\n=== DOCKER DISK USAGE ===")
print(run("docker system df", 20))

print("\n=== TOP DIRECTORIES ===")
print(run("du -sh /opt/sii/data/ /var/lib/docker/ 2>/dev/null", 20))

print("\n=== PRUNING DOCKER BUILD CACHE ===")
out = run("docker builder prune -f 2>&1", 60)
print(out[-400:] if len(out) > 400 else out)

print("\n=== PRUNING DANGLING IMAGES ===")
out = run("docker image prune -f 2>&1", 30)
print(out)

print("\n=== DISK AFTER PRUNE ===")
print(run("df -h / | tail -1"))

print("\n=== RESTARTING API CONTAINER ===")
out = run("cd /opt/sii && docker compose up -d api 2>&1", 30)
print(out)
print("Waiting 15s for API to start...")
time.sleep(15)

print("\n=== VERIFYING SYNC/STATUS FIX ===")
health = run("curl -s https://localhost/api/health --insecure", 10)
try:
    h = json.loads(health)
    ok("API health", h.get('status') == 'ok', health[:80])
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
    code = run(
        f'curl -s -o /dev/null -w "%{{http_code}}" '
        f'-H "Authorization: Bearer {token}" '
        'https://localhost/api/sync/status --insecure', 15
    )
    ok("GET /sync/status", code == '200', f"HTTP {code}")

    code2 = run(
        f'curl -s -o /dev/null -w "%{{http_code}}" '
        f'-H "Authorization: Bearer {token}" '
        '"https://localhost/api/monitoring/missing?account=CH4&mese_anno=04/2026" --insecure', 30
    )
    ok("GET /monitoring/missing", code2 == '200', f"HTTP {code2}")

print("\n=== FINAL DISK ===")
print(run("df -h / | tail -1"))

ssh.close()
print("\nDone.")
