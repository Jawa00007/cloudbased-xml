import paramiko, sys, time

host = '104.248.32.23'
user = 'root'
pwd = 'Din@mo5055Trade'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pwd, timeout=30, allow_agent=False, look_for_keys=False)

def run(cmd, desc='', timeout=300):
    if desc:
        print(f'\n=== {desc} ===')
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out: print(out.rstrip())
    if err and err.strip(): print('[STDERR]', err.rstrip())
    return out

# 1. Force remove the corrupted container (keeps volume data safe!)
run('docker rm -f sii-db-1 2>&1', 'Remove corrupted DB container')
run('docker rm -f sii-api-1 2>&1', 'Remove corrupted API container')

# 2. Re-pull postgres:16-alpine (the correct image version)
run('docker pull postgres:16-alpine 2>&1', 'Pull postgres:16-alpine', timeout=300)

# 3. Check disk
run('df -h /', 'Disk before recreate')

# 4. Recreate all containers via docker compose
run('cd /opt/sii && docker compose up -d 2>&1', 'docker compose up -d', timeout=120)

# Wait for DB to initialize (first start after crash recovery)
print('\nWaiting 20s for DB to initialize...')
time.sleep(20)

# 5. Check statuses
run('docker ps --format "table {{.Names}}\t{{.Status}}"', 'Container statuses')

# 6. DB logs
run('docker logs sii-db-1 --tail=25 2>&1', 'DB logs')

# 7. API health
run('curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/health', 'API health code')
run('curl -s http://localhost:8000/api/health', 'API health response')

client.close()
print('\nDone.')
