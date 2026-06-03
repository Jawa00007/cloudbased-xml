"""Deploy updated retention.py to server and verify it loaded."""
import os, sys, time, json
import paramiko

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
HOST = "104.248.32.23"; USER = "root"
PW = os.environ.get('SII_SSH_PWD', '')


def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PW, timeout=15)
    ssh.get_transport().set_keepalive(20)
    return ssh


def run(ssh, cmd, t=20):
    _, o, e = ssh.exec_command(cmd, timeout=t)
    return o.read().decode('utf-8', errors='replace').strip()


def main():
    if not PW:
        print("ERROR: SII_SSH_PWD not set"); return

    ssh = connect()
    print("Connected")

    print("\n=== GIT PULL ===")
    out = run(ssh, "cd /opt/sii && git pull origin main 2>&1", 30)
    print(out)

    log = run(ssh, "cd /opt/sii && git log --oneline -3", 10)
    print(log)

    grep = run(ssh, "grep -n 'retention_policy\\|hard_cutoff' /opt/sii/backend/db/retention.py", 10)
    print(f"\nNew functions on disk:\n{grep if grep else 'NOT FOUND'}")
    if not grep:
        ssh.close(); return

    print("\n=== HOT-PATCH ===")
    cp = run(ssh, "docker cp /opt/sii/backend/db/retention.py sii-api-1:/app/backend/db/retention.py 2>&1", 10)
    print(f"  cp: {cp if cp else 'ok'}")
    run(ssh, "docker restart sii-api-1 2>&1", 30)
    print("  Restarting... waiting 12s")
    time.sleep(12)

    health = run(ssh, "curl -s https://localhost/api/health --insecure", 10)
    try:
        h = json.loads(health)
        print(f"  API: {h.get('status')} | DB: {h.get('database', {}).get('status')}")
    except Exception:
        print(f"  Health: {health[:120]}")

    ssh.close()
    print("\nDone — retention.py deployed.")


if __name__ == "__main__":
    main()
