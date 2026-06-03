import paramiko, sys

host = '104.248.32.23'
user = 'root'
pwd = 'Din@mo5055Trade'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pwd, timeout=20, allow_agent=False, look_for_keys=False)

def run(cmd, desc='', timeout=30):
    if desc:
        print(f'\n=== {desc} ===')
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    if out: print(out.rstrip())
    if err and err.strip(): print('[STDERR]', err.rstrip())
    return out

SSH_KEY = '/root/.ssh/italian_server'
OPTS = f'-i {SSH_KEY} -o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=yes'
IT = 'ubuntu@57.131.24.23'
BASE = '/home/ubuntu/SII_CLOUD'

# 1. Can we connect at all?
run(f'ssh {OPTS} {IT} "echo connected && ls {BASE}/" 2>&1', 'Italian server connection + root listing')

# 2. What's in BAT? (first 10 entries, any level)
run(f'ssh {OPTS} {IT} "ls {BASE}/BAT/ | head -10" 2>&1', 'BAT directory listing')
run(f'ssh {OPTS} {IT} "ls {BASE}/BAT/ | head -3 | xargs -I{{}} ls {BASE}/BAT/{{}}/ | head -5" 2>&1', 'BAT subfolders')

# 3. Find ZIPs in BAT — count only, with error output visible
run(f'ssh {OPTS} {IT} "find {BASE}/BAT -name \'*.zip\' | wc -l" 2>&1', 'BAT ZIP count (verbose)')

# 4. Check what files are on the DigitalOcean server locally right now
run('du -sh /opt/sii/data/*/ 2>/dev/null | sort -rh', 'Local data dirs on DigitalOcean server')
run('find /opt/sii/data -name "*.zip" | wc -l', 'Local ZIP count (DigitalOcean)')
run('find /opt/sii/data -name "*.zip" | head -5', 'Sample local ZIPs')

client.close()
