"""Final redeploy — uses proper channel approach for long commands."""
import paramiko, time, select

HOST = "104.248.32.23"
USER = "root"
PASS = "Din@mo5055Trade"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=30)
print(f"Connected to {HOST}")

def run_quick(cmd, timeout=20):
    """Run a fast command."""
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if out: print(out[:600])
    if err and "warn" not in err[:30].lower(): print(f"[err] {err[:300]}")
    return out

def run_stream(cmd, timeout=300):
    """Stream output with a rolling read."""
    ch = ssh.get_transport().open_session()
    ch.settimeout(5)
    ch.exec_command(cmd)
    out = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data = ch.recv(4096)
            if not data:
                break
            chunk = data.decode("utf-8", errors="replace")
            out.append(chunk)
            last = chunk.strip().splitlines()
            if last:
                print(f"  {last[-1][:120]}")
        except Exception:
            if ch.exit_status_ready():
                break
            time.sleep(0.2)
    ch.close()
    return "".join(out)

# Pull latest
print("\n=== Git pull ===")
run_quick("cd /opt/sii && git pull origin feat/admin-panel")

# Build (stream output)
print("\n=== Building API image ===")
run_stream("cd /opt/sii && docker compose build api 2>&1", timeout=600)

# Restart
print("\n=== Restarting API ===")
run_quick("cd /opt/sii && docker compose up -d --no-deps api 2>&1")

# Wait for healthy
print("\nWaiting for API...")
healthy = False
for i in range(20):
    time.sleep(5)
    out = run_quick("curl -sf http://localhost:8000/api/health 2>/dev/null | python3 -c \"import sys,json; d=json.load(sys.stdin); print('OK DB:', d['database']['status'])\" 2>/dev/null", timeout=10)
    if "OK" in out:
        print(out)
        healthy = True
        break
    status = run_quick("docker inspect sii-api-1 --format '{{.State.Status}}' 2>/dev/null", timeout=5)
    print(f"  {i+1}/20: status={status}")
    if "restarting" in status.lower() and i >= 3:
        print("Still crashing — logs:")
        run_quick("docker logs sii-api-1 --tail=30 2>&1", timeout=10)
        break

if healthy:
    # Verify users endpoint
    api_key = run_quick("grep '^API_KEY=' /opt/sii/.env | cut -d= -f2 | tr -d '\\r'")
    users = run_quick(f"curl -sf -H 'X-API-Key: {api_key}' http://localhost:8000/api/admin/users 2>/dev/null")
    print(f"\n/admin/users: {users[:200] if users else '(empty)'}")

    table = run_quick("docker exec sii-db-1 psql -U sii -d sii -c \"SELECT COUNT(*) FROM public.users\" 2>&1")
    print(f"\nUsers table: {table}")

ssh.close()
print("\nDone.")
