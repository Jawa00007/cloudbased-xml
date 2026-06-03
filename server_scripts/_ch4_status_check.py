"""Quick status check: is the CH4 04/2026 forecast done? How many rows? Disk?"""
import sys, os, json
import paramiko
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HOST = "104.248.32.23"; USER = "root"

def run(ssh, cmd, timeout=20):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    return o.read().decode('utf-8', errors='replace').strip()

def main():
    pw = os.environ.get('SII_SSH_PWD', '')
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=pw, timeout=15)
    ssh.get_transport().set_keepalive(30)
    print("Connected")

    # Row count + distinct values
    rows_q = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SET search_path TO ch4; SELECT COUNT(*), COUNT(DISTINCT pod) FROM forecast_periods WHERE mese_anno='04/2026';" """, timeout=60)
    print(f"CH4 04/2026 — total rows | distinct pods: {rows_q.strip()}")

    # ANAGRAFICA pod count for 04/2026 (to know expected pod count)
    ana_q = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SET search_path TO ch4; SELECT COUNT(DISTINCT pod) FROM anagrafica WHERE mese_anno='04/2026';" """, timeout=20)
    print(f"ANAGRAFICA pods for 04/2026: {ana_q.strip()}")

    # API memory + container status
    mem = run(ssh, "docker stats sii-api-1 --no-stream --format '{{.MemUsage}} CPU:{{.CPUPerc}}'", timeout=10)
    print(f"API: {mem}")

    disk = run(ssh, "df -h / | tail -1", timeout=10)
    print(f"Disk: {disk}")

    # DB size
    db_size = run(ssh, """docker exec sii-db-1 psql -U sii -d sii -t -c \
      "SELECT pg_size_pretty(pg_database_size('sii'));" """, timeout=10)
    print(f"DB size: {db_size.strip()}")

    ssh.close()

if __name__ == "__main__":
    main()
