"""
Prune build cache, git pull, rebuild lean API image (no docker.io), prune old image.
Usage: SII_SSH_PWD=xxx python server_scripts/_rebuild_lean.py
"""
import os, sys, time
import paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HOST = "104.248.32.23"
USER = "root"
PW = os.environ.get("SII_SSH_PWD", "")


def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=15)
    ssh.get_transport().set_keepalive(20)
    return ssh


def run(ssh, cmd, timeout=60):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", errors="replace").strip()
    err = e.read().decode("utf-8", errors="replace").strip()
    if err and not any(w in err.lower() for w in ("warning", "notice", "deprecated", "hint", "stash")):
        print(f"  stderr: {err[:400]}")
    return out


def df_free_gb(ssh):
    out = run(ssh, "df / | tail -1", 10)
    parts = out.split()
    return int(parts[3]) / 1_048_576 if len(parts) >= 4 and parts[3].isdigit() else 0.0


def build_running(ssh):
    out = run(ssh, "cat /tmp/build_lean.done 2>/dev/null || echo missing", 10)
    if "missing" in out:
        # check if build process still alive
        pid = run(ssh, "cat /tmp/build_lean.pid 2>/dev/null", 10)
        if pid and pid.isdigit():
            alive = run(ssh, f"kill -0 {pid} 2>/dev/null && echo alive || echo dead", 10)
            return "dead" not in alive
        return False
    return False


def main():
    if not PW:
        print("ERROR: SII_SSH_PWD not set")
        sys.exit(1)

    ssh = connect()
    print(f"Connected to {HOST}")
    free0 = df_free_gb(ssh)
    print(f"Disk free before: {free0:.1f} GB\n")

    # --- Step 1: Prune build cache ---
    print("=== Step 1: docker builder prune -f ===")
    out = run(ssh, "docker builder prune -f 2>&1 | tail -5", 120)
    print(out)
    free1 = df_free_gb(ssh)
    print(f"Disk free after prune: {free1:.1f} GB  (+{free1 - free0:.1f} GB)\n")

    # --- Step 2: Git stash + pull ---
    print("=== Step 2: git stash + pull ===")
    out = run(ssh, "cd /opt/sii && git stash 2>&1", 30)
    print(f"  stash: {out}")
    out = run(ssh, "cd /opt/sii && git pull 2>&1", 30)
    print(f"  pull:  {out}")

    # Verify Dockerfile no longer has docker.io
    out = run(ssh, "grep docker.io /opt/sii/Dockerfile 2>/dev/null || echo 'OK: docker.io not in Dockerfile'", 10)
    print(f"  Dockerfile check: {out}")

    # Verify docker-compose.yml has binary mount
    out = run(ssh, "grep 'usr/bin/docker' /opt/sii/docker-compose.yml 2>/dev/null || echo 'MISSING binary mount'", 10)
    print(f"  Compose check: {out}\n")

    # --- Step 3: Build lean image (background) ---
    print("=== Step 3: Building lean API image (background) ===")
    build_script = (
        "#!/bin/bash\n"
        "cd /opt/sii\n"
        "docker compose build api > /tmp/build_lean.log 2>&1\n"
        "echo $? > /tmp/build_lean.done\n"
    )
    sftp = ssh.open_sftp()
    with sftp.file("/tmp/build_lean.sh", "w") as f:
        f.write(build_script)
    sftp.chmod("/tmp/build_lean.sh", 0o755)
    sftp.close()

    # Clear any old done file
    run(ssh, "rm -f /tmp/build_lean.done /tmp/build_lean.pid", 10)
    run(ssh, "nohup /tmp/build_lean.sh > /dev/null 2>&1 & echo $! > /tmp/build_lean.pid", 15)
    pid = run(ssh, "cat /tmp/build_lean.pid", 10)
    print(f"  Build started (PID {pid})")

    t0 = time.time()
    last_log_line = ""
    while True:
        time.sleep(20)
        try:
            ssh.close()
        except Exception:
            pass
        try:
            ssh = connect()
        except Exception as e:
            print(f"  [reconnect failed: {e}]")
            time.sleep(10)
            continue

        done = run(ssh, "cat /tmp/build_lean.done 2>/dev/null", 10)
        elapsed = int(time.time() - t0)

        # Show last log line for progress feedback
        log_tail = run(ssh, "tail -2 /tmp/build_lean.log 2>/dev/null", 10)
        if log_tail and log_tail != last_log_line:
            last_log_line = log_tail
            for line in log_tail.splitlines():
                print(f"  [{elapsed}s] {line}")

        if done.strip():
            rc = done.strip()
            print(f"\n  Build finished in {elapsed}s  (exit code: {rc})")
            if rc != "0":
                log = run(ssh, "tail -30 /tmp/build_lean.log", 30)
                print("  Build log (last 30 lines):")
                print(log)
                sys.exit(1)
            break

    # --- Step 4: Restart API + prune old image ---
    print("\n=== Step 4: Restart API container ===")
    out = run(ssh, "cd /opt/sii && docker compose up -d api 2>&1", 30)
    print(out)
    time.sleep(5)

    print("\n=== Step 4b: Prune dangling/old images ===")
    out = run(ssh, "docker image prune -f 2>&1", 60)
    print(out)
    free2 = df_free_gb(ssh)
    print(f"Disk free after image prune: {free2:.1f} GB  (+{free2 - free1:.1f} GB)\n")

    # --- Step 5: Verify ---
    print("=== Step 5: Health check ===")
    health = run(ssh, "curl -sk https://localhost/api/health | head -c 200", 15)
    print(f"  API health: {health}")

    containers = run(ssh, "docker ps --format 'table {{.Names}}\\t{{.Status}}' 2>/dev/null", 15)
    print(f"\n  Containers:\n{containers}")

    df = run(ssh, "df -h / | tail -1", 10)
    print(f"\n  Root disk: {df}")

    image_size = run(ssh, "docker images sii-api --format '{{.Size}}' | head -1", 10)
    print(f"  sii-api image size: {image_size}")

    print("\nDONE")
    ssh.close()


if __name__ == "__main__":
    main()
