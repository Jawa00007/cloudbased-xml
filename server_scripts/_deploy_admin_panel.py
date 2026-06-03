"""
Deploy feat/admin-panel to the server.
Pulls the branch, runs Alembic migration in existing container, rebuilds, restarts.
"""
import paramiko
import time

HOST = "104.248.32.23"
USER = "root"
PASS = "Din@mo5055Trade"

def run(client, cmd, timeout=180):
    print(f"\n>>> {cmd}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if out:
        print(out)
    if err and "[stderr]" not in err:
        print(f"[stderr] {err}")
    return out

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=30)
print(f"Connected to {HOST}")

# 1. Run Alembic migration in the currently running API container
print("\n=== Running Alembic migration ===")
out = run(ssh, "docker exec sii-api-1 alembic upgrade head", timeout=60)

# 2. Build the API image (slow — needs large timeout)
print("\n=== Building API image ===")
run(ssh, "cd /opt/sii && docker compose build api 2>&1 | tail -20", timeout=600)

# 3. Restart the API container with the new image
print("\n=== Restarting API ===")
run(ssh, "cd /opt/sii && docker compose up -d --no-deps api", timeout=60)

# 4. Wait and verify
time.sleep(10)
print("\n=== Verifying ===")
out = run(ssh, "docker ps --format '{{.Names}}\\t{{.Status}}' | grep api")
print(f"Container: {out}")

health = run(ssh, (
    "curl -sf http://localhost:8000/api/health | "
    "python3 -c \"import sys,json; d=json.load(sys.stdin); "
    "print('DB:', d['database']['status'], '| ENV:', d['environment'])\""
))
print(f"Health: {health}")

# 5. Verify users endpoint is registered
users_check = run(ssh, (
    "curl -sf -H 'X-API-Key: '\"$(grep API_KEY /opt/sii/.env | cut -d= -f2)\"'' "
    "http://localhost:8000/api/admin/users | python3 -c \"import sys,json; d=json.load(sys.stdin); print(type(d).__name__, 'len=', len(d))\""
))
print(f"Users endpoint: {users_check}")

ssh.close()
print("\nDone.")
