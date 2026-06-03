"""Pull latest main, rebuild API, restart, then run final feature checks."""
import os, sys, json, time, paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HOST = "104.248.32.23"; USER = "root"
PW = os.environ.get('SII_SSH_PWD', '')


def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=15)
    ssh.get_transport().set_keepalive(20)
    return ssh


def run(ssh, cmd, timeout=30):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode('utf-8', errors='replace').strip()
    err = e.read().decode('utf-8', errors='replace').strip()
    return out, err


def ok(label, good, detail=''):
    print(f"  [{'OK  ' if good else 'FAIL'}] {label}" + (f"  ->  {detail}" if detail else ''))


def section(t):
    print(f"\n{'='*52}\n  {t}\n{'='*52}")


def main():
    if not PW:
        print("ERROR: SII_SSH_PWD not set"); return

    ssh = connect()
    print("Connected")

    # ── Deploy ──────────────────────────────────────────────────────────────
    section("DEPLOY — git pull + switch to main + rebuild")

    out, _ = run(ssh, "cd /opt/sii && git fetch origin 2>&1", 20)
    print(f"  fetch: {out}")

    out, _ = run(ssh, "cd /opt/sii && git checkout main 2>&1", 10)
    print(f"  checkout main: {out}")

    out, _ = run(ssh, "cd /opt/sii && git pull origin main 2>&1", 30)
    print(f"  pull: {out}")

    log, _ = run(ssh, "cd /opt/sii && git log --oneline -4", 10)
    print(f"  git log:\n{log}")

    print("\n  Building API image (this takes 2-5 min)...")
    build_out, build_err = run(ssh,
        "cd /opt/sii && docker compose build api 2>&1 | tail -5",
        timeout=480)
    print(f"  build: {build_out[-300:] if len(build_out) > 300 else build_out}")

    print("\n  Restarting API container...")
    out, _ = run(ssh, "cd /opt/sii && docker compose up -d api 2>&1", 30)
    print(f"  up -d api: {out}")

    print("  Waiting 15s for API to start...")
    time.sleep(15)

    # ── Health check ────────────────────────────────────────────────────────
    section("API HEALTH (post-deploy)")
    health_raw, _ = run(ssh, 'curl -s https://localhost/api/health --insecure', 15)
    try:
        h = json.loads(health_raw)
        ok("GET /health", True, health_raw[:100])
        db_info = h.get('database', {})
        ok("DB connected", db_info.get('status') == 'ok', str(db_info))
        sched_info = h.get('scheduler', {})
        ok("Scheduler running", sched_info.get('running') is True, str(sched_info))
    except Exception:
        ok("GET /health", False, health_raw[:120])

    # Get token
    token_raw, _ = run(ssh, (
        'curl -s -X POST https://localhost/api/auth/token --insecure '
        '-H "Content-Type: application/json" '
        '-d \'{"username":"admin","password":"Din@mo5055Trade"}\''
    ), 15)
    try:
        token = json.loads(token_raw).get('access_token', '')
    except Exception:
        token = ''
    ok("POST /auth/token", bool(token), "token OK" if token else token_raw[:100])

    if not token:
        ssh.close(); return

    def chk(path, label, timeout=15):
        code, _ = run(ssh, (
            f'curl -s -o /dev/null -w "%{{http_code}}" '
            f'-H "Authorization: Bearer {token}" '
            f'https://localhost/api{path} --insecure'
        ), timeout)
        ok(label, code in ('200','201','204'), f"HTTP {code}")
        return code

    def chk_json(path, label, timeout=15):
        body, _ = run(ssh, (
            f'curl -s -H "Authorization: Bearer {token}" '
            f'https://localhost/api{path} --insecure'
        ), timeout)
        try:
            parsed = json.loads(body)
            detail = f"{len(parsed)} items" if isinstance(parsed, list) else body[:80]
            ok(label, True, detail)
        except Exception:
            ok(label, False, body[:80])

    section("CORE ENDPOINTS")
    chk_json('/accounts', 'GET /accounts')
    chk('/sync/status', 'GET /sync/status (was 500)')
    chk('/files?account=CH4', 'GET /files?account=CH4')

    section("ADMIN ENDPOINTS")
    chk('/admin/users', 'GET /admin/users')
    chk('/admin/system/status', 'GET /admin/system/status')
    chk('/admin/loss-config', 'GET /admin/loss-config')
    chk('/admin/dispatching-config', 'GET /admin/dispatching-config')
    chk('/admin/anagrafica/months?account_id=CH4', 'GET /admin/anagrafica/months')
    chk('/admin/retention/log', 'GET /admin/retention/log')

    section("FORECAST ENDPOINTS")
    fc_body, _ = run(ssh, (
        f'curl -s -H "Authorization: Bearer {token}" '
        '"https://localhost/api/forecast/CH4/04%2F2026?limit=3" --insecure'
    ), 20)
    try:
        fc = json.loads(fc_body)
        ok("GET /forecast/CH4/04/2026", isinstance(fc, list) and len(fc) > 0,
           f"{len(fc)} rows" if isinstance(fc, list) else fc_body[:80])
    except Exception:
        ok("GET /forecast/CH4/04/2026", False, fc_body[:80])

    chk('/forecast/measurements/months?account_id=CH4', 'GET /forecast/measurements/months', timeout=30)

    section("MONITORING ENDPOINTS")
    chk('/monitoring/missing?account=CH4&mese_anno=04/2026', 'GET /monitoring/missing')
    chk('/monitoring/corrections?account=CH4', 'GET /monitoring/corrections')

    section("NGINX / FRONTEND")
    fe, _ = run(ssh, 'curl -s -o /dev/null -w "%{http_code}" https://localhost/ --insecure', 10)
    ok("Frontend served over HTTPS", fe == '200', f"HTTP {fe}")

    section("DISK + DB")
    disk, _ = run(ssh, "df -h / | tail -1", 10)
    print(f"  Disk: {disk}")
    db_size, _ = run(ssh, (
        'docker exec sii-db-1 psql -U sii -d sii -t -c '
        '"SELECT pg_size_pretty(pg_database_size(\'sii\'));"'
    ), 15)
    print(f"  DB total: {db_size.strip()}")

    ssh.close()
    section("ALL DONE")


if __name__ == "__main__":
    main()
