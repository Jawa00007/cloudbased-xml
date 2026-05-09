"""
Deploy latest code to the DigitalOcean server.

Usage:
    python deploy.py           # upload backend files and rebuild API container
    python deploy.py --full    # also upload frontend/dist and reload nginx
"""
import sys, paramiko
from pathlib import Path

HOST = "104.248.32.23"
USER = "root"
KEY  = r"C:\Users\jawad\.ssh\do_sii"
PROJECT_ROOT = Path(__file__).parent

EXCLUDE = {
    ".env", ".git", "__pycache__", ".pytest_cache",
    "node_modules", "data", "reports", "graphify-out",
    "setup_server.py", "deploy.py", "check_server.py",
    "migrate_new_tables.py", "seed_data.py",
    "migrate_dispatch_nullable.py", "backend.log",
    "frontend.log", "backend_err.log", "frontend_err.log",
}


def upload_dir(sftp, local: Path, remote: str, *, backend_only: bool = True):
    try:
        sftp.mkdir(remote)
    except OSError:
        pass
    for item in local.iterdir():
        if item.name in EXCLUDE or item.name.endswith(".pyc"):
            continue
        if backend_only and item.name == "frontend":
            continue
        remote_path = f"{remote}/{item.name}"
        if item.is_dir():
            upload_dir(sftp, item, remote_path, backend_only=backend_only)
        else:
            sftp.put(str(item), remote_path)
            print(f"  {item.relative_to(PROJECT_ROOT)}")


def run(client, cmd, timeout=120):
    print(f">>> {cmd}")
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    code = stdout.channel.recv_exit_status()
    if out:
        print(out)
    if err and code != 0:
        print("[err]", err)
    return code


full = "--full" in sys.argv

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print(f"Connecting to {HOST}...")
client.connect(HOST, username=USER, key_filename=KEY, timeout=15)
print("Connected.\n")

print("--- Uploading backend files ---")
sftp = client.open_sftp()
upload_dir(sftp, PROJECT_ROOT, "/opt/sii", backend_only=not full)
sftp.close()

# Ensure server .env has POSTGRES_PASSWORD (one-time migration from hardcoded docker-compose)
print("\n--- Ensuring server .env has POSTGRES_PASSWORD ---")
run(client, "grep -q '^POSTGRES_PASSWORD=' /opt/sii/.env "
            "|| echo 'POSTGRES_PASSWORD=sii_db_2024' >> /opt/sii/.env")
run(client, "grep -q '^POSTGRES_DB=' /opt/sii/.env "
            "|| echo 'POSTGRES_DB=sii' >> /opt/sii/.env")
run(client, "grep -q '^POSTGRES_USER=' /opt/sii/.env "
            "|| echo 'POSTGRES_USER=sii' >> /opt/sii/.env")

print("\n--- Rebuilding and restarting API container ---")
run(client, "cd /opt/sii && docker compose up -d --build api")

if full:
    print("\n--- Reloading nginx (new frontend/dist) ---")
    run(client, "docker compose -f /opt/sii/docker-compose.yml up -d --force-recreate nginx")

print("\n--- Status ---")
run(client, "docker compose -f /opt/sii/docker-compose.yml ps")
run(client, "curl -sk https://forecast.dinamoservice.it/api/health")

print(f"\nDone. App: https://forecast.dinamoservice.it")
client.close()
