"""Upload frontend/dist to server and restart nginx."""
import os, sys, paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HOST = "104.248.32.23"; USER = "root"
PW = os.environ.get("SII_SSH_PWD", "")

LOCAL_DIST = "frontend/dist"
REMOTE_DIST = "/opt/sii/frontend/dist"


def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=15)
    ssh.get_transport().set_keepalive(20)
    return ssh


def run(ssh, cmd, timeout=30):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", errors="replace").strip()
    err = e.read().decode("utf-8", errors="replace").strip()
    if out:
        print(out)
    if err and "warning" not in err.lower():
        print(f"  ERR: {err[:200]}")


def main():
    if not PW:
        print("ERROR: SII_SSH_PWD not set"); sys.exit(1)

    ssh = connect()
    sftp = ssh.open_sftp()

    count = 0
    for root, dirs, files in os.walk(LOCAL_DIST):
        rel = os.path.relpath(root, LOCAL_DIST).replace("\\", "/")
        remote_dir = REMOTE_DIST if rel == "." else f"{REMOTE_DIST}/{rel}"
        try:
            sftp.mkdir(remote_dir)
        except Exception:
            pass
        for f in files:
            local_f = os.path.join(root, f)
            remote_f = f"{remote_dir}/{f}"
            sftp.put(local_f, remote_f)
            count += 1

    sftp.close()
    print(f"Uploaded {count} files")
    run(ssh, "docker compose -f /opt/sii/docker-compose.yml restart nginx", 20)
    print("Frontend deployed")
    ssh.close()


if __name__ == "__main__":
    main()
