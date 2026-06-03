import paramiko, sys, time

host = '104.248.32.23'
user = 'root'
pwd = 'Din@mo5055Trade'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pwd, timeout=30, allow_agent=False, look_for_keys=False)

def run(cmd, desc='', timeout=120):
    if desc:
        print(f'\n=== {desc} ===')
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out: print(out.rstrip())
    if err and err.strip(): print('[STDERR]', err.rstrip())
    return out

# 1. Restart DB container (disk now has space, it should recover)
run('docker restart sii-db-1', 'Restarting DB container')

# Wait for DB to initialize
print('Waiting 15s for DB to initialize...')
time.sleep(15)

# 2. Check DB health
run('docker logs sii-db-1 --tail=15 2>&1', 'DB logs after restart')

# 3. Use docker compose to restart the full stack properly
run('cd /opt/sii && docker compose up -d 2>&1', 'docker compose up -d', timeout=120)

print('Waiting 10s for services to start...')
time.sleep(10)

# 4. Check container statuses
run('docker ps --format "table {{.Names}}\t{{.Status}}"', 'Container statuses')

# 5. Check API health
run('curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/health', 'API health check')
run('curl -s http://localhost:8000/api/health', 'API health response')

# 6. Test accounts endpoint
run('curl -s http://localhost:8000/api/accounts | head -c 500', 'Accounts endpoint test')

# 7. Final disk
run('df -h /', 'Disk status')

client.close()
print('\nDone.')
