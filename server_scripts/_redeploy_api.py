"""Pull latest and restart API after bug fix."""
import paramiko, time

HOST = "104.248.32.23"
USER = "root"
PASS = "Din@mo5055Trade"

def run(client, cmd, timeout=60):
    print(f">>> {cmd}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if out: print(out)
    if err: print(f"[stderr] {err[:500]}")
    return out

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=30)
print(f"Connected to {HOST}")

run(ssh, "cd /opt/sii && git pull origin feat/admin-panel")
run(ssh, "cd /opt/sii && docker compose build api 2>&1 | tail -10", timeout=600)
run(ssh, "cd /opt/sii && docker compose up -d --no-deps api", timeout=60)

print("\nWaiting for API...")
for i in range(15):
    time.sleep(4)
    out = run(ssh, "curl -sf http://localhost:8000/api/health 2>/dev/null | python3 -c \"import sys,json; d=json.load(sys.stdin); print('OK - DB:', d['database']['status'])\" 2>/dev/null")
    if out.startswith("OK"):
        print(out)
        break
    print(f"  not ready yet ({i+1}/15)...")

# Verify users endpoint
api_key = run(ssh, "grep '^API_KEY=' /opt/sii/.env | cut -d= -f2 | tr -d '\\r'")
users = run(ssh, f"curl -sf -H 'X-API-Key: {api_key}' http://localhost:8000/api/admin/users")
print(f"\n/admin/users: {users[:200]}")

table = run(ssh, "docker exec sii-db-1 psql -U sii -d sii -c \"SELECT COUNT(*) FROM public.users\" 2>&1")
print(f"\nUsers table: {table}")

ssh.close()
print("\nDone.")
