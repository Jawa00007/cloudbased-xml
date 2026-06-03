import paramiko

HOST = "104.248.32.23"
USER = "root"
PASS = "Din@mo5055Trade"

def run(cmd, timeout=20):
    _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    return (stdout.read() + stderr.read()).decode("utf-8", errors="replace").strip()

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=30)

# Check what tables exist in public schema
print("=== Tables in public schema ===")
print(run("""docker exec sii-db-1 psql -U sii -d sii -c "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name" """))

# Check alembic_version for public schema
print("\n=== Alembic version for public schema ===")
print(run("""docker exec sii-db-1 psql -U sii -d sii -c "SELECT version_num FROM public.alembic_version" """))

# Try running migration manually directly in psql
print("\n=== Create table manually if missing ===")
result = run("""docker exec sii-db-1 psql -U sii -d sii -c "SELECT current_schema()" """)
print(f"current_schema: {result}")

# Check if users table exists anywhere
print("\n=== Search all schemas for users table ===")
print(run("""docker exec sii-db-1 psql -U sii -d sii -c "SELECT table_schema, table_name FROM information_schema.tables WHERE table_name = 'users'" """))

# If not there, create it manually
print("\n=== Creating users table manually ===")
create_sql = """
docker exec sii-db-1 psql -U sii -d sii -c "
CREATE TABLE IF NOT EXISTS public.users (
    id               SERIAL PRIMARY KEY,
    username         TEXT NOT NULL UNIQUE,
    password_hash    TEXT NOT NULL,
    is_admin         BOOLEAN NOT NULL DEFAULT false,
    allowed_accounts TEXT[] DEFAULT NULL,
    is_active        BOOLEAN NOT NULL DEFAULT true,
    created_at       TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
)
"
"""
print(run(create_sql.strip()))

# Verify
print("\n=== Verify users table ===")
print(run("""docker exec sii-db-1 psql -U sii -d sii -c "SELECT COUNT(*) FROM public.users" """))

ssh.close()
