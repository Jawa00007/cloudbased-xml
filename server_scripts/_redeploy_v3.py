"""Final redeploy — pull fix, rebuild, restart."""
import paramiko, time

HOST = "104.248.32.23"
USER = "root"
PASS = "Din@mo5055Trade"

def run(cmd, timeout=30):
    print(f">>> {cmd[:90]}")
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if out: print(out[:600])
    if err and "warning" not in err.lower()[:50]: print(f"[err] {err[:400]}")
    return out

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=30)
print(f"Connected to {HOST}")

# Pull
run("cd /opt/sii && git pull origin feat/admin-panel")

# Build in background
run("cd /opt/sii && nohup docker compose build api > /tmp/build2.log 2>&1 &")
print("Build started, waiting...")
for i in range(30):
    time.sleep(3)
    tail = run("tail -2 /tmp/build2.log 2>/dev/null")
    if "Built" in tail or "error" in tail.lower():
        print(f"Build done: {tail}")
        break

# Restart
run("cd /opt/sii && docker compose up -d --no-deps api", timeout=30)

# Wait for healthy
print("\nWaiting for API...")
for i in range(20):
    time.sleep(4)
    out = run("curl -sf http://localhost:8000/api/health 2>/dev/null | python3 -c \"import sys,json; d=json.load(sys.stdin); print('OK DB:', d['database']['status'])\" 2>/dev/null")
    if "OK" in out:
        print(out)
        break
    # Check if still crashing
    status = run("docker inspect sii-api-1 --format '{{.State.Status}}'")
    if "restarting" in status.lower():
        logs = run("docker logs sii-api-1 --tail=20 2>&1")
        print(f"Still crashing: {logs[-500:]}")
        break
    print(f"  waiting ({i+1}/20) status={status}...")

# Verify
api_key = run("grep '^API_KEY=' /opt/sii/.env | cut -d= -f2 | tr -d '\\r'")
users = run(f"curl -sf -H 'X-API-Key: {api_key}' http://localhost:8000/api/admin/users 2>/dev/null")
print(f"\n/admin/users: {users[:200] if users else '(empty)'}")

table = run("docker exec sii-db-1 psql -U sii -d sii -c \"SELECT COUNT(*) FROM public.users\" 2>&1")
print(f"\nUsers table: {table}")

ssh.close()
print("\nDone.")
