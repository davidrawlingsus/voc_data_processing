# Multi-Tenant System - Quick Start

This system adds multi-tenant capability with Row-Level Security (RLS) for automatic tenant isolation.

## Quick Setup

1. **Edit seed data** (important!):
   ```bash
   # Edit migrations/004_seed_data.sql
   # Replace 'founder@example.com' with your email
   # Replace 'Founder User' with your name
   ```

2. **Run migrations**:
   ```bash
   export DATABASE_URL="postgresql://user:pass@host:port/dbname"
   
   for file in migrations/*.sql; do
       echo "Running $file..."
       psql $DATABASE_URL -f "$file"
   done
   ```

3. **Use in your code**:
   ```python
   from tenant_context import TenantContext
   import uuid
   
   user_id = uuid.UUID('your-user-id')
   with TenantContext(conn, user_id):
       # All queries automatically filtered by RLS
       cursor.execute("SELECT * FROM process_voc")
   ```

## Files Overview

- **migrations/** - SQL migration files (run in order)
- **tenant_context.py** - Python helper for setting session context
- **MULTI_TENANT_SETUP.md** - Full documentation

## Key Concepts

- **Founder users** (`is_founder = TRUE`) can access ALL clients
- **Regular users** only see clients they have active memberships for
- **Roles**: `owner`, `admin`, `editor`, `viewer`
- **RLS automatically filters** all queries based on user memberships

## Next Steps

1. Link your existing `process_voc` data to clients (see MULTI_TENANT_SETUP.md)
2. Integrate `tenant_context.py` into your web framework middleware
3. Create memberships for users using your admin interface

See `MULTI_TENANT_SETUP.md` for full documentation.
