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

# Check what image DB is using
run('docker inspect sii-db-1 --format "Image: {{.Config.Image}}"', 'DB image')
run('docker inspect sii-api-1 --format "Image: {{.Config.Image}}"', 'API image')

# Check docker images
run('docker images', 'All images')

# Re-pull postgres image
print('\nRe-pulling postgres:16 image...')
run('docker pull postgres:16 2>&1', 'Pull postgres:16', timeout=300)

# Check disk after pull
run('df -h /', 'Disk after pull')

# Try docker compose up again
run('cd /opt/sii && docker compose up -d --no-recreate 2>&1', 'docker compose up (no-recreate)', timeout=120)

time.sleep(12)

# Check statuses
run('docker ps --format "table {{.Names}}\t{{.Status}}"', 'Container statuses')

# Check DB logs
run('docker logs sii-db-1 --tail=20 2>&1', 'DB logs')

client.close()
print('\nDone.')
