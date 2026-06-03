"""Deploy chunked engine.py fix and re-trigger CH4 04/2026 forecast."""
import sys, paramiko, time, json
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HOST   = "104.248.32.23"
USER   = "root"
BRANCH = "fix/forecast-weights-flat-curve"

def run(ssh, cmd, timeout=60):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode('utf-8', errors='replace').strip()
    err = e.read().decode('utf-8', errors='replace').strip()
    if err and 'warning' not in err.lower():
        print(f"  STDERR: {err[:300]}")
    return out

def fire(ssh, cmd):
    """Fire-and-forget: don't read stdout (background & commands hang on read)."""
    ssh.exec_command(cmd)

def main():
    pw = __import__('os').environ.get('SII_SSH_PWD', '')
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=pw, timeout=15)
    print("Connected")

    print("=== git pull ===")
    out = run(ssh, f"cd /opt/sii && git pull origin {BRANCH}")
    print(out)

    print("=== launching build ===")
    fire(ssh, "cd /opt/sii && docker compose build api > /tmp/build.log 2>&1 &")
    print("build kicked off")

    start = time.time()
    last_size = 0
    while True:
        elapsed = int(time.time() - start)
        size_out = run(ssh, "wc -c /tmp/build.log 2>/dev/null | awk '{print $1}'", timeout=10)
        size = int(size_out) if size_out.isdigit() else 0
        done_check = run(ssh, "grep -c 'exporting to image\\|FINISHED\\|ERROR' /tmp/build.log 2>/dev/null || echo 0", timeout=10)

        done_count = sum(int(x) for x in done_check.split() if x.isdigit())
        if done_count > 0:
            tail = run(ssh, "tail -5 /tmp/build.log", timeout=10)
            print(f"[{elapsed}s] Build done:\n{tail}")
            break

        if size != last_size:
            last_size = size
            tail = run(ssh, "tail -3 /tmp/build.log 2>/dev/null", timeout=10)
            last_line = tail.splitlines()[-1] if tail else ''
            print(f"[{elapsed}s] building... ({size} bytes): {last_line}")
        else:
            print(f"[{elapsed}s] waiting...")

        if elapsed > 720:
            print("Build timeout — check /tmp/build.log on server")
            break
        time.sleep(20)

    print("=== restart API ===")
    print(run(ssh, "cd /opt/sii && docker compose up -d api", timeout=30))
    time.sleep(10)

    print("=== health check ===")
    health = run(ssh, "curl -sk https://localhost/api/health", timeout=15)
    print(health)

    print("=== trigger CH4 04/2026 forecast ===")
    token_resp = run(ssh, """curl -sk -X POST https://localhost/api/auth/token \
      -H 'Content-Type: application/json' \
      -d '{"username":"admin","password":"Din@mo5055Trade"}' """, timeout=15)
    try:
        token = json.loads(token_resp).get('access_token', '')
    except Exception:
        print(f"Token parse error: {token_resp[:200]}")
        token = ''

    if token:
        trig = run(ssh, f"""curl -sk -X POST https://localhost/api/forecast/generate \
          -H 'Authorization: Bearer {token}' \
          -H 'Content-Type: application/json' \
          -d '{{"account_id":"CH4","mese_anno":"04/2026"}}' """, timeout=20)
        print(f"Trigger response: {trig}")
    else:
        print("No token — skipping forecast trigger")

    print("=== container status ===")
    print(run(ssh, 'docker ps --format "{{.Names}} {{.Status}}" | grep sii-api'))

    ssh.close()
    print("Deploy done — monitor CH4 forecast in logs")

if __name__ == '__main__':
    main()
