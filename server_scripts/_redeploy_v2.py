"""Redeploy API — runs docker build in background to avoid SSH timeout."""
import paramiko, time

HOST = "104.248.32.23"
USER = "root"
PASS = "Din@mo5055Trade"

def run(ssh, cmd, timeout=60):
    print(f">>> {cmd[:80]}...")
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if out: print(out[:800])
    if err: print(f"[err] {err[:400]}")
    return out

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=30)
print(f"Connected to {HOST}")

# Run build in background — writes output to file
print("\n=== Starting build in background ===")
run(ssh, "cd /opt/sii && nohup docker compose build api > /tmp/api_build.log 2>&1 &")
time.sleep(3)

# Poll until build completes
print("Waiting for build...")
for i in range(60):
    status = run(ssh, "jobs -l 2>/dev/null || true")
    done = run(ssh, "grep -c 'Image sii-api Built\\|ERROR\\|error' /tmp/api_build.log 2>/dev/null || echo 0")
    tail = run(ssh, "tail -3 /tmp/api_build.log 2>/dev/null")
    print(f"  [{i*5}s] last: {tail}")
    if "Built" in tail or "DONE" in tail or "error" in tail.lower():
        break
    time.sleep(5)

print("\n=== Build log tail ===")
print(run(ssh, "tail -15 /tmp/api_build.log"))

# Restart API
print("\n=== Restarting API ===")
run(ssh, "cd /opt/sii && docker compose up -d --no-deps api", timeout=60)

# Wait for healthy
print("\nWaiting for API to be ready...")
for i in range(20):
    time.sleep(4)
    out = run(ssh, (
        "curl -sf http://localhost:8000/api/health 2>/dev/null | "
        "python3 -c \"import sys,json; d=json.load(sys.stdin); "
        "print('OK DB:', d['database']['status'])\" 2>/dev/null"
    ))
    if "OK" in out:
        print(out)
        break
    print(f"  not ready ({i+1}/20)...")

# Verify users endpoint
api_key = run(ssh, "grep '^API_KEY=' /opt/sii/.env | cut -d= -f2 | tr -d '\\r'")
users = run(ssh, f"curl -sf -H 'X-API-Key: {api_key}' http://localhost:8000/api/admin/users 2>/dev/null")
print(f"\n/admin/users response: {users[:200] if users else '(empty)'}")

table = run(ssh, "docker exec sii-db-1 psql -U sii -d sii -c \"SELECT COUNT(*) FROM public.users\" 2>&1")
print(f"\nUsers table: {table}")

ssh.close()
print("\nDone.")
