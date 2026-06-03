"""Comprehensive feature check — SSHs in and tests all major system components."""
import os, sys, json, paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HOST = "104.248.32.23"; USER = "root"
PW = os.environ.get('SII_SSH_PWD', '')


def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=15)
    ssh.get_transport().set_keepalive(20)
    return ssh


def run(ssh, cmd, timeout=20):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode('utf-8', errors='replace').strip()
    return out


def section(title):
    print(f"\n{'='*52}")
    print(f"  {title}")
    print('='*52)


def check(label, ok, detail=''):
    status = 'OK  ' if ok else 'FAIL'
    line = f"  [{status}] {label}"
    if detail:
        line += f"  ->  {detail}"
    print(line)


def main():
    if not PW:
        print("ERROR: SII_SSH_PWD not set"); return

    ssh = connect()
    print("Connected to server")

    # ── Git / deployment state ─────────────────────────────────────────────
    section("GIT — DEPLOYED CODE")
    git_log = run(ssh, "cd /opt/sii && git log --oneline -6")
    print(git_log)
    branch = run(ssh, "cd /opt/sii && git branch --show-current")
    print(f"\nBranch: {branch}")
    af = run(ssh, "cd /opt/sii && git log --oneline | grep -i 'anagrafica\\|auto.*forecast'")
    check("Auto-forecast-after-upload commit", bool(af), af[:80] if af else "NOT DEPLOYED")

    # ── Docker containers ──────────────────────────────────────────────────
    section("DOCKER CONTAINERS")
    containers = run(ssh, 'docker ps --format "{{.Names}}|{{.Status}}"')
    for line in containers.splitlines():
        if '|' not in line:
            continue
        name, status = line.split('|', 1)
        ok = 'Up' in status and 'unhealthy' not in status.lower()
        check(name.strip(), ok, status.strip())

    # ── Disk ──────────────────────────────────────────────────────────────
    section("DISK")
    disk = run(ssh, "df -h / | tail -1")
    print(f"  {disk}")
    parts = disk.split()
    pct = int(parts[4].replace('%', '')) if len(parts) >= 5 else 100
    check("Disk usage safe (<90%)", pct < 90, f"{pct}% used")

    # ── API health ─────────────────────────────────────────────────────────
    section("API HEALTH")
    health_raw = run(ssh, 'curl -s https://localhost/api/health --insecure', timeout=15)
    try:
        h = json.loads(health_raw)
        check("GET /health", True, health_raw[:120])
        check("DB connected", h.get('database') == 'ok', h.get('database', '?'))
        check("Scheduler running", h.get('scheduler') == 'running', h.get('scheduler', '?'))
    except Exception:
        check("GET /health", False, health_raw[:120])

    # ── Auth ───────────────────────────────────────────────────────────────
    section("AUTH")
    token_resp = run(ssh, (
        'curl -s -X POST https://localhost/api/auth/token --insecure '
        '-H "Content-Type: application/json" '
        '-d \'{"username":"admin","password":"Din@mo5055Trade"}\''
    ), timeout=15)
    try:
        token = json.loads(token_resp).get('access_token', '')
    except Exception:
        token = ''
    check("POST /auth/token (admin login)", bool(token), "token OK" if token else token_resp[:100])

    # ── Endpoint checks ────────────────────────────────────────────────────
    if not token:
        print("  Skipping endpoint checks — no token")
        ssh.close()
        return

    def api_code(path, label):
        code = run(ssh, (
            f'curl -s -o /dev/null -w "%{{http_code}}" '
            f'-H "Authorization: Bearer {token}" '
            f'https://localhost/api{path} --insecure'
        ), timeout=15)
        ok = code in ('200', '201', '204')
        check(label, ok, f"HTTP {code}")
        return code

    def api_json(path, label):
        body = run(ssh, (
            f'curl -s -H "Authorization: Bearer {token}" '
            f'https://localhost/api{path} --insecure'
        ), timeout=15)
        try:
            parsed = json.loads(body)
            ok = parsed is not None
            detail = f"{len(parsed)} items" if isinstance(parsed, list) else str(parsed)[:80]
        except Exception:
            ok = False
            detail = body[:80]
        check(label, ok, detail)
        return body

    section("CORE ENDPOINTS")
    api_json('/accounts', 'GET /accounts')
    api_code('/sync/status', 'GET /sync/status')
    api_code('/files?account=CH4', 'GET /files?account=CH4')

    section("ADMIN ENDPOINTS")
    api_code('/admin/users', 'GET /admin/users')
    api_code('/admin/system/status', 'GET /admin/system/status')
    api_code('/admin/loss-config', 'GET /admin/loss-config')
    api_code('/admin/dispatching-config', 'GET /admin/dispatching-config')
    api_code('/admin/anagrafica/months?account_id=CH4', 'GET /admin/anagrafica/months (CH4)')

    section("FORECAST ENDPOINTS")
    fc_raw = run(ssh, (
        f'curl -s -H "Authorization: Bearer {token}" '
        '"https://localhost/api/forecast/CH4/04%2F2026?limit=5" --insecure'
    ), timeout=20)
    try:
        fc = json.loads(fc_raw)
        check("GET /forecast/CH4/04/2026", isinstance(fc, list) and len(fc) > 0,
              f"{len(fc)} rows" if isinstance(fc, list) else fc_raw[:80])
    except Exception:
        check("GET /forecast/CH4/04/2026", False, fc_raw[:80])

    api_code('/forecast/measurements/months?account_id=CH4', 'GET /forecast/measurements/months')

    section("RETENTION")
    api_code('/admin/retention/log', 'GET /admin/retention/log')

    # ── DB schema sizes ────────────────────────────────────────────────────
    section("DATABASE SCHEMA SIZES")
    sizes = run(ssh, (
        'docker exec sii-db-1 psql -U sii -d sii -t -c '
        '"SELECT schemaname, pg_size_pretty(SUM(pg_total_relation_size'
        "(schemaname||'.'||tablename))::bigint) "
        'FROM pg_tables WHERE schemaname NOT IN (\'pg_catalog\',\'information_schema\') '
        'GROUP BY schemaname ORDER BY SUM(pg_total_relation_size'
        "(schemaname||'.'||tablename)) DESC LIMIT 12;\""
    ), timeout=25)
    for line in sizes.splitlines():
        if line.strip():
            print(f"  {line.strip()}")

    # ── Nginx / frontend ───────────────────────────────────────────────────
    section("NGINX / FRONTEND")
    fe = run(ssh, 'curl -s -o /dev/null -w "%{http_code}" https://localhost/ --insecure', timeout=10)
    check("Frontend served over HTTPS", fe == '200', f"HTTP {fe}")
    login_page = run(ssh, 'curl -s https://localhost/login --insecure | grep -o "<title>.*</title>"', timeout=10)
    check("Login page has title", bool(login_page), login_page)

    ssh.close()
    section("CHECK COMPLETE")


if __name__ == "__main__":
    main()
