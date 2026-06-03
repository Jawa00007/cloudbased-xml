import paramiko, sys, time

host = '104.248.32.23'
user = 'root'
pwd = 'Din@mo5055Trade'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pwd, timeout=30, allow_agent=False, look_for_keys=False)

def run(cmd, desc='', timeout=60):
    if desc:
        print(f'\n=== {desc} ===')
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out: print(out.rstrip())
    if err and err.strip(): print('[STDERR]', err.rstrip())
    return out

# Check container statuses
run('docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"', 'Container statuses')

# Check DB container health
run('docker logs sii-db-1 --tail=20 2>&1', 'DB logs (last 20 lines)')

# Check API logs
run('docker logs sii-api-1 --tail=30 2>&1', 'API logs (last 30 lines)')

# Restart the API container (DB should recover on its own once disk has space)
run('docker restart sii-api-1 2>&1', 'Restarting API container')

time.sleep(8)

# Check health again
run('curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/health 2>&1', 'API health after restart')
run('curl -s http://localhost:8000/api/health 2>&1', 'API health response')

# Check disk one more time
run('df -h /', 'Final disk status')

client.close()
print('\nDone.')
