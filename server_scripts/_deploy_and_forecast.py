"""
1. git pull latest on server (gets .dockerignore fix + forecast.py search_path fix)
2. Hot-patch forecast.py into running container (no rebuild needed)
3. Verify missing_data.py fix is still in container
4. docker compose restart api
5. alembic upgrade head
6. Trigger CH4 04/2026 forecast + poll to completion
7. Verify row counts
8. (Optional) docker compose build api in background for future restarts
"""
import sys, json, os, time
import paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HOST = "104.248.32.23"
USER = "root"


def run(ssh, cmd, timeout=30):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode('utf-8', errors='replace').strip()
    err = e.read().decode('utf-8', errors='replace').strip()
    if err and not any(w in err.lower() for w in ('warning', 'notice', 'deprecated')):
        print(f"  STDERR: {err[:400]}")
    return out


def run_streaming(ssh, cmd, max_wait=900, prefix="  "):
    transport = ssh.get_transport()
    chan = transport.open_session()
    chan.set_combine_stderr(True)
    chan.exec_command(cmd)
    chan.settimeout(5)
    lines = []
    start = time.time()
    last_line = ""
    while True:
        elapsed = int(time.time() - start)
        if elapsed > max_wait:
            print(f"\n{prefix}[timeout after {max_wait}s]")
            break
        try:
            chunk = chan.recv(4096)
            if chunk:
                text = chunk.decode('utf-8', errors='replace')
                lines.append(text)
                for line in text.splitlines():
                    if line.strip() and line.strip() != last_line:
                        print(f"{prefix}{line.rstrip()}")
                        last_line = line.strip()
            else:
                break
        except Exception:
            pass
        if chan.exit_status_ready() and not chan.recv_ready():
            break
    chan.close()
    return ''.join(lines)


def main():
    pw = os.environ.get('SII_SSH_PWD', '')
    if not pw:
        print("ERROR: SII_SSH_PWD not set")
        return

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=pw, timeout=15)
    ssh.get_transport().set_keepalive(30)
    print("Connected")

    # ── 1. git pull ──────────────────────────────────────────────────────────
    print("\n=== git pull ===")
    pull = run(ssh, "cd /opt/sii && git pull origin fix/forecast-weights-flat-curve 2>&1", timeout=60)
    print(pull)

    # ── 2. Hot-patch forecast.py ─────────────────────────────────────────────
    print("\n=== Hot-patch forecast.py ===")
    local_forecast = r"c:\Users\jawad\Documents\CloudBased XML\backend\api\routes\forecast.py"
    sftp = ssh.open_sftp()
    sftp.put(local_forecast, "/tmp/forecast_patch.py")
    sftp.close()
    cp = run(ssh, "docker cp /tmp/forecast_patch.py sii-api-1:/app/backend/api/routes/forecast.py", timeout=15)
    print(f"docker cp forecast.py: {cp or 'ok'}")

    check_fp = run(ssh, "docker exec sii-api-1 grep -c 'fresh write session per chunk' /app/backend/api/routes/forecast.py", timeout=10)
    print(f"search_path fix in container: {check_fp} (expect 1)")

    # ── 3. Verify missing_data.py fix ────────────────────────────────────────
    check_md = run(ssh, "docker exec sii-api-1 grep -c 'continue.*day_num beyond month end' /app/backend/forecast/missing_data.py 2>/dev/null || echo 0", timeout=10)
    print(f"missing_data.py April-30-dup fix: {check_md} (expect 1)")
    if check_md.strip() == "0":
        print("  Re-applying missing_data.py fix...")
        local_md = r"c:\Users\jawad\Documents\CloudBased XML\backend\forecast\missing_data.py"
        sftp2 = ssh.open_sftp()
        sftp2.put(local_md, "/tmp/missing_data_patch.py")
        sftp2.close()
        run(ssh, "docker cp /tmp/missing_data_patch.py sii-api-1:/app/backend/forecast/missing_data.py", timeout=15)
        chk2 = run(ssh, "docker exec sii-api-1 grep -c 'continue.*day_num beyond month end' /app/backend/forecast/missing_data.py", timeout=10)
        print(f"  After re-patch: {chk2} (expect 1)")

    # ── 4. Restart API ───────────────────────────────────────────────────────
    print("\n=== docker compose restart api ===")
    restart = run(ssh, "cd /opt/sii && docker compose restart api 2>&1", timeout=90)
    print(restart)

    print("Waiting for API healthy...")
    for i in range(30):
        time.sleep(5)
        code = run(ssh, 'curl -sk -o /dev/null -w "%{http_code}" https://localhost/api/health', timeout=10)
        print(f"  [{(i+1)*5}s] HTTP {code}")
        if code == "200":
            print("  API healthy!")
            break
    else:
        print("  WARNING: API not healthy after 150s")

    # Verify patches survived restart
    check_fp2 = run(ssh, "docker exec sii-api-1 grep -c 'fresh write session per chunk' /app/backend/api/routes/forecast.py", timeout=10)
    check_md2 = run(ssh, "docker exec sii-api-1 grep -c 'continue.*day_num beyond month end' /app/backend/forecast/missing_data.py", timeout=10)
    print(f"Patches after restart — forecast.py: {check_fp2}, missing_data.py: {check_md2}")

    # ── 5. alembic upgrade head ──────────────────────────────────────────────
    print("\n=== alembic upgrade head ===")
    alembic_out = run(ssh, "docker exec sii-api-1 alembic upgrade head 2>&1", timeout=120)
    for line in alembic_out.splitlines():
        if any(w in line.lower() for w in ('running', 'error', 'head', 'up', 'done', 'already')):
            print(f"  {line}")

    # Check archive_catalog exists
    cat_check = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT to_regclass('public.archive_catalog');" 2>&1""", timeout=15)
    print(f"archive_catalog: {cat_check.strip()}")

    # ── 6. Get auth token ────────────────────────────────────────────────────
    token_resp = run(ssh, """curl -sk -X POST https://localhost/api/auth/token \
      -H 'Content-Type: application/json' \
      -d '{"username":"admin","password":"Din@mo5055Trade"}' """, timeout=15)
    try:
        token = json.loads(token_resp).get('access_token', '')
        print(f"\nToken: {token[:40]}...")
    except Exception:
        print(f"Token error: {token_resp[:200]}")
        ssh.close()
        return

    # ── 7. Clean up any partial CH4 data ────────────────────────────────────
    print("\n=== Delete any partial CH4 04/2026 data ===")
    del_out = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SET search_path TO ch4; DELETE FROM forecast_periods WHERE mese_anno='04/2026';" 2>&1""", timeout=30)
    print(f"  {del_out.strip()[:100]}")

    # ── 8. Trigger CH4 04/2026 forecast ─────────────────────────────────────
    print("\n=== Trigger CH4 04/2026 forecast ===")
    resp = run(ssh, f"""curl -sk -X POST https://localhost/api/forecast/generate \
      -H 'Authorization: Bearer {token}' \
      -H 'Content-Type: application/json' \
      -d '{{"account_id":"CH4","mese_anno":"04/2026"}}' """, timeout=15)
    print(f"Response: {resp}")
    try:
        job_id = json.loads(resp)['job_id']
        print(f"Job ID: {job_id}")
    except Exception:
        print("Could not parse job_id — aborting")
        ssh.close()
        return

    # ── 9. Poll until done ───────────────────────────────────────────────────
    print("Polling (expect 10-15 min for 3,449 pods)...")
    start = time.time()
    final_status = None
    for i in range(60):
        time.sleep(30)
        elapsed = int(time.time() - start)
        sr = run(ssh, f"""curl -sk https://localhost/api/forecast/status/{job_id} \
          -H 'Authorization: Bearer {token}' """, timeout=15)
        try:
            j = json.loads(sr)
            status = j.get('status', '?')
            error = j.get('error') or ''
            rows = (j.get('result') or {}).get('periods_written', '')
        except Exception:
            status = '?'; error = sr[:100]; rows = ''
        print(f"[{elapsed}s] {status} | rows={rows} | {error[:80] if error else ''}")
        if status in ('done', 'error'):
            final_status = status
            break

    # ── 10. Verify ───────────────────────────────────────────────────────────
    print("\n=== Final verification ===")
    mem = run(ssh, "docker stats sii-api-1 --no-stream --format '{{.MemUsage}}'", timeout=10)
    print(f"Memory: {mem}")

    rows_q = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SET search_path TO ch4; SELECT COUNT(*), COUNT(DISTINCT ea_kwh), COUNT(DISTINCT ea_kwh_with_loss) FROM forecast_periods WHERE mese_anno='04/2026';" """, timeout=30)
    print(f"Rows | distinct ea_kwh | distinct loss: {rows_q.strip()}")

    sample = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SET search_path TO ch4; SELECT pod, COUNT(*) FROM forecast_periods WHERE mese_anno='04/2026' GROUP BY pod ORDER BY pod LIMIT 3;" """, timeout=30)
    print(f"Sample pods (expect 2880 rows each for April):\n{sample}")

    disk = run(ssh, "df -h / | tail -1", timeout=10)
    print(f"Disk: {disk}")

    # ── 11. Background rebuild (now with fixed .dockerignore) ────────────────
    if final_status == 'done':
        print("\n=== Starting background docker rebuild with fixed .dockerignore ===")
        run(ssh, "cd /opt/sii && nohup docker compose build api > /tmp/rebuild.log 2>&1 &", timeout=15)
        print("Build started in background — check /tmp/rebuild.log on server")

    ssh.close()
    print(f"\nDone. Final forecast status: {final_status}")


if __name__ == "__main__":
    main()
