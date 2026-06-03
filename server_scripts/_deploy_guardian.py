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

# Upload the guardian script
with open('server_scripts/disk_guardian.sh', 'rb') as f:
    content = f.read()

sftp = client.open_sftp()
with sftp.open('/opt/sii/disk_guardian.sh', 'wb') as f:
    f.write(content)
sftp.chmod('/opt/sii/disk_guardian.sh', 0o755)
sftp.close()
print('Guardian script uploaded.')

# Set permanent journal log limit
run(r"""
sed -i '/^SystemMaxUse=/d; /^SystemKeepFree=/d; /^RuntimeMaxUse=/d' /etc/systemd/journald.conf
echo 'SystemMaxUse=100M' >> /etc/systemd/journald.conf
echo 'SystemKeepFree=2G' >> /etc/systemd/journald.conf
systemctl restart systemd-journald
""", 'Set permanent journal size limit (100MB)')

# Create systemd service unit
service = """[Unit]
Description=SII Disk Guardian
After=docker.service

[Service]
Type=oneshot
ExecStart=/opt/sii/disk_guardian.sh
StandardOutput=append:/opt/sii/logs/disk_monitor.log
StandardError=append:/opt/sii/logs/disk_monitor.log
"""

# Create systemd timer unit
timer = """[Unit]
Description=SII Disk Guardian (every 15 minutes)

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min
Persistent=true

[Install]
WantedBy=timers.target
"""

sftp = client.open_sftp()
with sftp.open('/etc/systemd/system/sii-disk-guardian.service', 'w') as f:
    f.write(service)
with sftp.open('/etc/systemd/system/sii-disk-guardian.timer', 'w') as f:
    f.write(timer)
sftp.close()
print('Systemd units created.')

# Enable and start the timer
run('systemctl daemon-reload && systemctl enable --now sii-disk-guardian.timer', 'Enable disk guardian timer')

# Verify timer is active
run('systemctl status sii-disk-guardian.timer --no-pager', 'Timer status')

# Run it once now to confirm it works
run('/opt/sii/disk_guardian.sh', 'Run guardian now (disk is 96% — should trigger)')

# Show final log
run('tail -20 /opt/sii/logs/disk_monitor.log', 'Guardian log')

# Final disk status
run('df -h /', 'Final disk status')

client.close()
print('\nDisk guardian deployed.')
