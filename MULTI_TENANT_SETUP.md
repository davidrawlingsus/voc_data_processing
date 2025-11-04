# Multi-Tenant System Documentation

This document describes the multi-tenant architecture implemented for row-level security (RLS) and tenant isolation.

## Overview

The system uses PostgreSQL Row-Level Security (RLS) to automatically filter data based on user memberships. Users belong to one or more clients (tenants) through memberships with specific roles.

## Architecture

### Core Tables

1. **`users`** - User accounts
   - `id` (UUID, primary key)
   - `email` (unique)
   - `name`
   - `is_founder` (boolean) - Founders have access to ALL clients
   - `is_active`
   - `metadata` (JSONB)

2. **`clients`** - Tenant organizations
   - `id` (UUID, primary key)
   - `name`
   - `slug` (unique)
   - `is_active`
   - `settings` (JSONB)
   - `founder_user_id` (UUID, references users)

3. **`memberships`** - Links users to clients with roles
   - `id` (UUID, primary key)
   - `user_id` (UUID, references users)
   - `client_id` (UUID, references clients)
   - `role` - One of: `owner`, `admin`, `editor`, `viewer`
   - `status` - One of: `active`, `inactive`, `pending`, `suspended`
   - `invited_by`, `invited_at`, `joined_at`
   - Unique constraint on `(user_id, client_id)`

### Role Permissions

- **Founder**: Full access to all clients (bypasses RLS via `is_founder` flag)
- **Owner**: Full control of a client (can manage members, delete data)
- **Admin**: Can manage users and edit data (no deletion)
- **Editor**: Can create and edit data (no user management)
- **Viewer**: Read-only access

## Database Setup

### Running Migrations

Run migrations in order:

```bash
psql $DATABASE_URL -f migrations/001_create_multi_tenant_tables.sql
psql $DATABASE_URL -f migrations/002_create_rls_policies.sql
psql $DATABASE_URL -f migrations/003_add_client_uuid_to_process_voc.sql
psql $DATABASE_URL -f migrations/004_seed_data.sql
```

Or run all at once:

```bash
for file in migrations/*.sql; do
    echo "Running $file..."
    psql $DATABASE_URL -f "$file"
done
```

### Important: Update Seed Data

Before running the seed data migration, edit `migrations/004_seed_data.sql` and replace:
- `'founder@example.com'` with your actual email
- `'Founder User'` with your actual name

## Backend Integration

### Basic Usage

```python
import psycopg2
from tenant_context import set_tenant_context, TenantContext
import uuid

# Connect to database
conn = psycopg2.connect(DATABASE_URL)

# Option 1: Manual context setting (for dedicated connections)
user_id = uuid.UUID('123e4567-e89b-12d3-a456-426614174000')
set_tenant_context(conn, user_id)

cursor = conn.cursor()
cursor.execute("SELECT * FROM process_voc LIMIT 10")
results = cursor.fetchall()
# RLS automatically filters results to accessible clients

# Option 2: Context manager (recommended for connection pooling)
with TenantContext(conn, user_id):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM process_voc LIMIT 10")
    results = cursor.fetchall()
```

### Web Framework Integration

#### Flask Example

```python
from flask import Flask, g, request
from tenant_context import set_tenant_context, clear_tenant_context
import psycopg2
import jwt  # or your auth library

app = Flask(__name__)

def get_db():
    if 'db' not in g:
        g.db = psycopg2.connect(DATABASE_URL)
    return g.db

def get_current_user_id():
    """Extract user_id from JWT token or session"""
    token = request.headers.get('Authorization', '').replace('Bearer ', '')
    payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
    return uuid.UUID(payload['user_id'])

@app.before_request
def setup_tenant_context():
    """Set tenant context for each request"""
    try:
        user_id = get_current_user_id()
        set_tenant_context(get_db(), user_id)
    except Exception:
        # Unauthenticated request - no tenant context
        set_tenant_context(get_db(), None)

@app.after_request
def cleanup_tenant_context(response):
    """Clean up after request"""
    clear_tenant_context(get_db())
    return response

@app.teardown_appcontext
def close_db(error):
    db = g.pop('db', None)
    if db is not None:
        db.close()

@app.route('/api/process_voc')
def get_process_voc():
    """This query is automatically filtered by RLS"""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM process_voc LIMIT 100")
    return jsonify(cursor.fetchall())
```

#### FastAPI Example

```python
from fastapi import FastAPI, Depends, Header
from tenant_context import TenantContext
import psycopg2
import uuid

app = FastAPI()

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()

def get_current_user_id(authorization: str = Header(...)) -> uuid.UUID:
    """Extract user_id from JWT token"""
    token = authorization.replace('Bearer ', '')
    # Decode JWT and return user_id
    return uuid.UUID(...)

@app.get('/api/process_voc')
def get_process_voc(
    db: psycopg2.extensions.connection = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id)
):
    """This query is automatically filtered by RLS"""
    with TenantContext(db, user_id):
        cursor = db.cursor()
        cursor.execute("SELECT * FROM process_voc LIMIT 100")
        return cursor.fetchall()
```

### Connection Pooling Considerations

If using connection pooling (e.g., SQLAlchemy, psycopg2.pool), you have two options:

**Option 1: Use transactions with SET LOCAL**
```python
def get_db_with_context(pool, user_id):
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("SET LOCAL app.user_id = %s", (str(user_id),))
        yield conn
        conn.commit()
    finally:
        pool.putconn(conn)
```

**Option 2: Set context per request (current implementation)**
- Make sure to clear context when returning connection to pool
- Or use dedicated connections per request/user

## RLS Policy Behavior

### How It Works

1. Each query automatically checks the `app.user_id` session variable
2. RLS policies use helper functions to determine access:
   - `get_accessible_client_ids()` - Returns all client UUIDs user can access
   - `can_access_client(client_id)` - Checks if user can access specific client
   - `get_user_role_for_client(client_id)` - Returns user's role for a client

3. Policies filter rows based on:
   - Founder status (all clients if `is_founder = TRUE`)
   - Active memberships (only clients with `status = 'active'`)

### Founder Access

Founder users bypass membership checks and can access ALL active clients. This is handled in the RLS policies via:

```sql
EXISTS (
    SELECT 1 FROM users
    WHERE id = current_setting('app.user_id', true)::UUID
      AND is_founder = TRUE
      AND is_active = TRUE
)
```

## Linking Existing Data

If you have existing `process_voc` rows, you need to link them to clients via the `client_uuid` column:

```sql
-- Example: Link process_voc rows to a client
UPDATE process_voc pv
SET client_uuid = (
    SELECT id FROM clients 
    WHERE settings->>'external_client_id' = pv.client_id
    LIMIT 1
)
WHERE pv.client_uuid IS NULL
  AND pv.client_id = 'cl_658e8f6a7a';
```

Or create a mapping table if client_id values don't directly map:

```sql
CREATE TABLE client_id_mapping (
    external_client_id VARCHAR(255) PRIMARY KEY,
    client_uuid UUID REFERENCES clients(id)
);

-- Then update process_voc:
UPDATE process_voc pv
SET client_uuid = cm.client_uuid
FROM client_id_mapping cm
WHERE pv.client_id = cm.external_client_id;
```

## Adding New Tenant-Scoped Tables

To add RLS to a new table:

1. **Add `client_uuid` column** (or use existing client reference):
   ```sql
   ALTER TABLE my_table ADD COLUMN client_uuid UUID REFERENCES clients(id);
   ```

2. **Enable RLS**:
   ```sql
   ALTER TABLE my_table ENABLE ROW LEVEL SECURITY;
   ```

3. **Create policies** (copy pattern from `process_voc` policies):
   ```sql
   CREATE POLICY my_table_select_policy ON my_table
       FOR SELECT
       USING (
           -- Founder access
           EXISTS (SELECT 1 FROM users WHERE id = current_setting('app.user_id', true)::UUID AND is_founder = TRUE)
           OR
           -- Membership-based access
           client_uuid IN (SELECT * FROM unnest(get_accessible_client_ids()))
       );
   ```

## Managing Memberships

### Creating a Membership

```python
from tenant_context import TenantContext

def invite_user_to_client(db, inviter_user_id, target_user_id, client_id, role):
    with TenantContext(db, inviter_user_id):
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO memberships (user_id, client_id, role, status, invited_by, invited_at)
            VALUES (%s, %s, %s, 'pending', %s, CURRENT_TIMESTAMP)
        """, (target_user_id, client_id, role, inviter_user_id))
        db.commit()
```

### Accepting an Invitation

```python
def accept_invitation(db, user_id, membership_id):
    with TenantContext(db, user_id):
        cursor = db.cursor()
        cursor.execute("""
            UPDATE memberships
            SET status = 'active', joined_at = CURRENT_TIMESTAMP
            WHERE id = %s AND user_id = %s AND status = 'pending'
        """, (membership_id, user_id))
        db.commit()
```

## Extending the System

### Future Features

The schema is designed to support:

1. **Invitations**: Already supported via `status = 'pending'` and `invited_by` fields
2. **API Keys**: Can add `api_keys` table with `user_id` and `client_id` references
3. **Audit Logs**: Can add `audit_logs` table with `user_id`, `client_id`, `action`, `metadata`
4. **Team Management**: Hierarchical roles, departments within clients

### Adding API Key Support

```sql
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    client_id UUID REFERENCES clients(id),
    key_hash VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255),
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- In tenant_context.py, add:
def set_api_key_context(connection, api_key):
    """Set context from API key"""
    cursor = connection.cursor()
    cursor.execute("""
        SELECT user_id FROM api_keys 
        WHERE key_hash = crypt(%s, key_hash) 
          AND expires_at > NOW()
    """, (api_key,))
    result = cursor.fetchone()
    if result:
        set_tenant_context(connection, result[0])
```

### Adding Audit Logs

```sql
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    client_id UUID REFERENCES clients(id),
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100),
    resource_id UUID,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_logs_client_user ON audit_logs(client_id, user_id);
CREATE INDEX idx_audit_logs_created ON audit_logs(created_at);
```

## Testing Tenant Isolation

To verify RLS is working:

```python
from tenant_context import TenantContext

# Test 1: Regular user should only see their clients
regular_user_id = uuid.UUID('...')
with TenantContext(db, regular_user_id):
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM process_voc")
    count = cursor.fetchone()[0]
    print(f"Regular user sees {count} rows")

# Test 2: Founder should see all
founder_user_id = uuid.UUID('...')
with TenantContext(db, founder_user_id):
    cursor = db.cursor()
    cursor.execute("SELECT COUNT(*) FROM process_voc")
    count = cursor.fetchone()[0]
    print(f"Founder sees {count} rows")  # Should be >= regular user's count
```

## Troubleshooting

### "No rows returned" when expecting data

- Check that `app.user_id` is set: `SELECT current_setting('app.user_id', true);`
- Verify user has active membership: `SELECT * FROM memberships WHERE user_id = '...' AND status = 'active';`
- Check if client is active: `SELECT * FROM clients WHERE id = '...' AND is_active = TRUE;`

### "Permission denied" errors

- Verify RLS is enabled: `SELECT tablename, rowsecurity FROM pg_tables WHERE tablename = 'process_voc';`
- Check policies exist: `SELECT * FROM pg_policies WHERE tablename = 'process_voc';`

### Connection pooling issues

- Ensure context is cleared when returning connections to pool
- Consider using `SET LOCAL` within transactions instead of `SET`

## Security Considerations

1. **Always set user_id from trusted source** (JWT token, session, not user input)
2. **Clear context** when returning connections to pool
3. **Audit membership changes** - log all membership create/update/delete
4. **Regular security audits** - verify RLS policies are working correctly
5. **Limit founder access** - keep `is_founder = TRUE` users minimal

## Performance

- RLS policies use indexes on `memberships(user_id, status)` and `clients(id, is_active)`
- Helper functions use `SECURITY DEFINER` for efficiency
- Consider caching accessible client IDs for high-traffic scenarios
- Monitor query performance and add indexes as needed
