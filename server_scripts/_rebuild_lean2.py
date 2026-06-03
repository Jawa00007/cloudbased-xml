"""
Pull latest commit (backups/ in .dockerignore), rebuild lean image, restart, prune old image.
Usage: SII_SSH_PWD=xxx py server_scripts/_rebuild_lean2.py
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


def main():
    if not PW:
        print("ERROR: SII_SSH_PWD not set")
        sys.exit(1)

    ssh = connect()
    free0 = df_free_gb(ssh)
    print(f"Connected  |  disk free: {free0:.1f} GB\n")

    # Step 1: git pull to get .dockerignore fix
    print("=== Step 1: git pull ===")
    out = run(ssh, "cd /opt/sii && git pull 2>&1", 30)
    print(out)
    out = run(ssh, "grep backups /opt/sii/.dockerignore && echo 'backups/ excluded OK' || echo 'MISSING backups/ in .dockerignore'", 10)
    print(f"  .dockerignore check: {out}\n")

    # Step 2: Prune build cache before rebuild (free 22 GB reclaimable)
    print("=== Step 2: docker builder prune -f ===")
    out = run(ssh, "docker builder prune -f 2>&1 | tail -3", 120)
    print(out)
    free1 = df_free_gb(ssh)
    print(f"  Disk free after prune: {free1:.1f} GB  (+{free1 - free0:.1f} GB)\n")

    # Step 3: Build lean image (background)
    print("=== Step 3: docker compose build api (background) ===")
    build_script = (
        "#!/bin/bash\n"
        "cd /opt/sii\n"
        "docker compose build api > /tmp/build_lean2.log 2>&1\n"
        "echo $? > /tmp/build_lean2.done\n"
    )
    sftp = ssh.open_sftp()
    with sftp.file("/tmp/build_lean2.sh", "w") as f:
        f.write(build_script)
    sftp.chmod("/tmp/build_lean2.sh", 0o755)
    sftp.close()

    run(ssh, "rm -f /tmp/build_lean2.done", 10)
    run(ssh, "nohup /tmp/build_lean2.sh > /dev/null 2>&1 & echo $! > /tmp/build_lean2.pid", 15)
    pid = run(ssh, "cat /tmp/build_lean2.pid", 10)
    print(f"  Build started (PID {pid})")

    t0 = time.time()
    last_log = ""
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

        done = run(ssh, "cat /tmp/build_lean2.done 2>/dev/null", 10)
        elapsed = int(time.time() - t0)

        log_tail = run(ssh, "tail -2 /tmp/build_lean2.log 2>/dev/null", 10)
        if log_tail and log_tail != last_log:
            last_log = log_tail
            for line in log_tail.splitlines():
                print(f"  [{elapsed}s] {line}")

        if done.strip():
            rc = done.strip()
            print(f"\n  Build finished in {elapsed}s  (exit code: {rc})")
            if rc != "0":
                print(run(ssh, "tail -30 /tmp/build_lean2.log", 30))
                sys.exit(1)
            break

    # Step 4: Show new image size
    img_size = run(ssh, "docker images sii-api --format '{{.Size}}' | head -1", 10)
    print(f"  New image size: {img_size}")

    # Step 5: Restart API
    print("\n=== Step 4: Restart API container ===")
    out = run(ssh, "cd /opt/sii && docker compose up -d api 2>&1", 30)
    print(out)
    time.sleep(5)

    # Step 6: Prune old image
    print("\n=== Step 5: Prune old/dangling images ===")
    out = run(ssh, "docker image prune -f 2>&1", 60)
    print(out)

    # Step 7: Final state
    print("\n=== Final state ===")
    health = run(ssh, "curl -sk https://localhost/api/health | python3 -c \"import sys,json; d=json.load(sys.stdin); print(d.get('status'), 'db:', d['database']['status'])\" 2>/dev/null || curl -sk https://localhost/api/health | head -c 100", 15)
    print(f"  API health: {health}")

    containers = run(ssh, "docker ps --format 'table {{.Names}}\\t{{.Status}}'", 15)
    print(f"\n  Containers:\n{containers}")

    df = run(ssh, "df -h / | tail -1", 10)
    print(f"\n  Root disk: {df}")

    print("\n  Docker disk usage:")
    print(run(ssh, "docker system df", 15))

    images = run(ssh, "docker images --format 'table {{.Repository}}\\t{{.Tag}}\\t{{.Size}}'", 10)
    print(f"\n  Images:\n{images}")

    print("\nDONE")
    ssh.close()


if __name__ == "__main__":
    main()
