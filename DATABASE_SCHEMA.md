# Database Schema Documentation

This document describes the complete database schema for the Caplena Extractor application.

## Tables Overview

1. **users** - User accounts with authentication
2. **clients** - Client organizations (multi-tenant)
3. **memberships** - User-to-client relationships with roles
4. **process_voc** - Processed Voice of Customer data (main data table)
5. **data_sources** - Data source definitions
6. **dimension_names** - Custom dimension name mappings
7. **dimension_summaries** - AI-generated summaries of dimensions
8. **insights** - Business insights derived from data
9. **authorized_domains** - Domain authorization for clients
10. **authorized_domain_clients** - Many-to-many relationship between domains and clients
11. **alembic_version** - Database migration version tracking

---

## Table: `users`

User accounts with authentication and profile information.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NOT NULL | `gen_random_uuid()` | Primary key |
| `email` | VARCHAR(255) | NOT NULL | - | Unique email address |
| `name` | VARCHAR(255) | NULL | - | User's full name |
| `is_founder` | BOOLEAN | NOT NULL | `false` | Founder users have access to all clients |
| `is_active` | BOOLEAN | NOT NULL | `true` | Account active status |
| `email_verified_at` | TIMESTAMP WITH TIME ZONE | NULL | - | Email verification timestamp |
| `last_login_at` | TIMESTAMP WITH TIME ZONE | NULL | - | Last login timestamp |
| `metadata` | JSONB | NULL | - | Additional user metadata |
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `CURRENT_TIMESTAMP` | Account creation timestamp |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `CURRENT_TIMESTAMP` | Last update timestamp |
| `hashed_password` | VARCHAR(255) | NULL | - | Hashed password (if using password auth) |
| `last_magic_link_sent_at` | TIMESTAMP WITH TIME ZONE | NULL | - | Last magic link sent timestamp |
| `magic_link_token` | VARCHAR(255) | NULL | - | Current magic link token |
| `magic_link_expires_at` | TIMESTAMP WITH TIME ZONE | NULL | - | Magic link expiration |

**Constraints:**
- Primary Key: `users_pkey` on `id`
- Unique: `users_email_key` on `email`

---

## Table: `clients`

Client organizations (multi-tenant isolation).

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NOT NULL | - | Primary key |
| `name` | VARCHAR(255) | NOT NULL | - | Client name (unique) |
| `slug` | VARCHAR(255) | NOT NULL | - | URL-friendly identifier (unique) |
| `is_active` | BOOLEAN | NULL | - | Client active status |
| `settings` | JSONB | NULL | - | Client-specific settings |
| `created_at` | TIMESTAMP WITH TIME ZONE | NULL | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NULL | - | Last update timestamp |
| `founder_user_id` | UUID | NULL | - | User who created this client (FK to users.id) |
| `business_context` | JSONB | NULL | - | Business context information |

**Constraints:**
- Primary Key: `clients_pkey` on `id`
- Unique: `clients_name_key` on `name`
- Unique: `clients_slug_key` on `slug`
- Foreign Key: `clients_founder_user_id_fkey` → `users(id)`

---

## Table: `memberships`

Many-to-many relationship between users and clients with role-based access control.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NOT NULL | `gen_random_uuid()` | Primary key |
| `user_id` | UUID | NOT NULL | - | User ID (FK to users.id) |
| `client_id` | UUID | NOT NULL | - | Client ID (FK to clients.id) |
| `role` | VARCHAR(50) | NOT NULL | `'viewer'` | Role: `owner`, `admin`, `editor`, `viewer` |
| `status` | VARCHAR(50) | NOT NULL | `'active'` | Status: `active`, `inactive`, `pending`, `suspended` |
| `invited_by` | UUID | NULL | - | User who sent invitation (FK to users.id) |
| `invited_at` | TIMESTAMP WITH TIME ZONE | NULL | - | Invitation timestamp |
| `joined_at` | TIMESTAMP WITH TIME ZONE | NULL | - | Join timestamp |
| `metadata` | JSONB | NULL | - | Additional membership metadata |
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `CURRENT_TIMESTAMP` | Creation timestamp |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `CURRENT_TIMESTAMP` | Last update timestamp |
| `provisioned_at` | TIMESTAMP WITH TIME ZONE | NULL | - | Provisioning timestamp |
| `provisioned_by` | UUID | NULL | - | User who provisioned (FK to users.id) |
| `provisioning_method` | VARCHAR(50) | NULL | - | Provisioning method |

**Constraints:**
- Primary Key: `memberships_pkey` on `id`
- Unique: `memberships_user_client_unique` on `(user_id, client_id)`
- Foreign Key: `memberships_user_id_fkey` → `users(id)`
- Foreign Key: `memberships_client_id_fkey` → `clients(id)`
- Foreign Key: `memberships_invited_by_fkey` → `users(id)`
- Foreign Key: `fk_memberships_provisioned_by_users` → `users(id)`
- Check: `memberships_role_check` - role must be in `('owner', 'admin', 'editor', 'viewer')`
- Check: `memberships_status_check` - status must be in `('active', 'inactive', 'pending', 'suspended')`

---

## Table: `process_voc`

**Main data table** - Processed Voice of Customer data from Caplena.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | NOT NULL | `nextval('process_voc_id_seq')` | Primary key (auto-increment) |
| `respondent_id` | VARCHAR(50) | NOT NULL | - | Respondent identifier from source |
| `created` | TIMESTAMP WITH TIME ZONE | NULL | - | Original creation timestamp |
| `last_modified` | TIMESTAMP WITH TIME ZONE | NULL | - | Last modification timestamp |
| `client_id` | VARCHAR(50) | NULL | - | Client identifier (legacy, may be external API ID) |
| `client_name` | VARCHAR(255) | NULL | - | Client name |
| `project_id` | VARCHAR(50) | NULL | - | Project identifier from Caplena |
| `project_name` | VARCHAR(255) | NULL | - | Project name |
| `total_rows` | INTEGER | NULL | - | Total rows in the project |
| `data_source` | VARCHAR(255) | NULL | - | Data source (e.g., "Reviews", "Gorgias", etc.) |
| `dimension_ref` | VARCHAR(50) | NOT NULL | - | Dimension reference identifier |
| `dimension_name` | TEXT | NULL | - | Human-readable dimension name (e.g., "Site Jabber") |
| `value` | TEXT | NULL | - | The actual text/value being analyzed |
| `overall_sentiment` | VARCHAR(50) | NULL | - | Overall sentiment (e.g., "positive", "negative", "neutral") |
| `topics` | JSONB | NULL | - | Extracted topics as JSON array |
| `created_at` | TIMESTAMP WITH TIME ZONE | NULL | `CURRENT_TIMESTAMP` | Record creation timestamp |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NULL | `CURRENT_TIMESTAMP` | Last update timestamp |
| `client_uuid` | UUID | NULL | - | **UUID reference to clients.id** (for RLS and tenant isolation) |
| `is_favourite` | BOOLEAN | NULL | `false` | Favorite flag |
| `survey_metadata` | JSONB | NULL | - | Additional survey metadata |
| `question_text` | TEXT | NULL | - | Original question text |
| `processed` | BOOLEAN | NOT NULL | `false` | Processing status flag |

**Constraints:**
- Primary Key: `process_voc_pkey` on `id`
- Unique: `fk_respondent_dimension` on `(respondent_id, dimension_ref)` - **Prevents duplicates**
- Foreign Key: `process_voc_client_uuid_fkey` → `clients(id)` ON DELETE SET NULL

**Important Notes:**
- The `(respondent_id, dimension_ref)` unique constraint prevents duplicate entries
- `client_uuid` is used for Row-Level Security (RLS) and proper tenant isolation
- `client_id` is kept for backward compatibility (may contain external API IDs)

---

## Table: `data_sources`

Data source definitions and metadata.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NOT NULL | - | Primary key |
| `name` | VARCHAR(255) | NOT NULL | - | Data source name |
| `client_id` | UUID | NULL | - | Client ID (FK to clients.id) |
| `source_name` | VARCHAR(255) | NULL | - | Source name |
| `source_type` | VARCHAR(50) | NULL | - | Source type |
| `source_format` | VARCHAR(50) | NULL | - | Source format |
| `raw_data` | JSONB | NOT NULL | - | Raw data |
| `normalized_data` | JSONB | NULL | - | Normalized data |
| `is_normalized` | BOOLEAN | NULL | - | Normalization status |
| `created_at` | TIMESTAMP WITH TIME ZONE | NULL | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NULL | - | Last update timestamp |

**Constraints:**
- Primary Key: `data_sources_pkey` on `id`
- Foreign Key: `data_sources_client_id_fkey` → `clients(id)`

---

## Table: `dimension_names`

Custom dimension name mappings.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NOT NULL | - | Primary key |
| `data_source_id` | UUID | NOT NULL | - | Data source ID (FK to data_sources.id) |
| `ref_key` | VARCHAR(100) | NOT NULL | - | Reference key |
| `custom_name` | VARCHAR(255) | NOT NULL | - | Custom dimension name |
| `created_at` | TIMESTAMP WITH TIME ZONE | NULL | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NULL | - | Last update timestamp |

**Constraints:**
- Primary Key: `dimension_names_pkey` on `id`
- Unique: `uq_data_source_ref_key` on `(data_source_id, ref_key)`
- Foreign Key: `dimension_names_data_source_id_fkey` → `data_sources(id)`

---

## Table: `dimension_summaries`

AI-generated summaries of dimensions.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NOT NULL | - | Primary key |
| `client_uuid` | UUID | NOT NULL | - | Client UUID (FK to clients.id) |
| `data_source` | VARCHAR(255) | NOT NULL | - | Data source name |
| `dimension_ref` | VARCHAR(50) | NOT NULL | - | Dimension reference |
| `dimension_name` | TEXT | NULL | - | Dimension name |
| `summary_text` | TEXT | NOT NULL | - | Summary text |
| `key_insights` | JSONB | NULL | - | Key insights as JSON |
| `category_snapshot` | JSONB | NULL | - | Category snapshot |
| `patterns` | TEXT | NULL | - | Patterns identified |
| `sample_size` | INTEGER | NOT NULL | - | Sample size used |
| `total_responses` | INTEGER | NOT NULL | - | Total responses |
| `model_used` | VARCHAR(50) | NULL | - | AI model used |
| `tokens_used` | INTEGER | NULL | - | Tokens consumed |
| `topic_distribution` | JSONB | NULL | - | Topic distribution |
| `generation_duration_ms` | INTEGER | NULL | - | Generation duration in milliseconds |
| `created_at` | TIMESTAMP WITH TIME ZONE | NULL | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NULL | - | Last update timestamp |

**Constraints:**
- Primary Key: `dimension_summaries_pkey` on `id`
- Unique: `uq_client_source_dimension_summary` on `(client_uuid, data_source, dimension_ref)`
- Foreign Key: `dimension_summaries_client_uuid_fkey` → `clients(id)`

---

## Table: `insights`

Business insights derived from data.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NOT NULL | - | Primary key |
| `client_id` | UUID | NOT NULL | - | Client ID (FK to clients.id) |
| `name` | VARCHAR(255) | NOT NULL | - | Insight name |
| `type` | VARCHAR(100) | NOT NULL | - | Insight type |
| `application` | TEXT | NULL | - | Application/use case |
| `description` | TEXT | NULL | - | Description |
| `origins` | JSONB | NOT NULL | - | Origins data |
| `metadata` | JSONB | NULL | - | Additional metadata |
| `created_at` | TIMESTAMP WITH TIME ZONE | NULL | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NULL | - | Last update timestamp |
| `created_by` | UUID | NULL | - | Creator user ID (FK to users.id) |
| `notes` | TEXT | NULL | - | Notes |

**Constraints:**
- Primary Key: `insights_pkey` on `id`
- Foreign Key: `insights_client_id_fkey` → `clients(id)`
- Foreign Key: `insights_created_by_fkey` → `users(id)`

---

## Table: `authorized_domains`

Domain authorization for clients.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NOT NULL | `gen_random_uuid()` | Primary key |
| `domain` | VARCHAR(255) | NOT NULL | - | Domain name (unique) |
| `description` | VARCHAR(255) | NULL | - | Description |
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `CURRENT_TIMESTAMP` | Creation timestamp |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `CURRENT_TIMESTAMP` | Last update timestamp |

**Constraints:**
- Primary Key: `authorized_domains_pkey` on `id`
- Unique: `authorized_domains_domain_key` on `domain`

---

## Table: `authorized_domain_clients`

Many-to-many relationship between domains and clients.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `domain_id` | UUID | NOT NULL | - | Domain ID (FK to authorized_domains.id) |
| `client_id` | UUID | NOT NULL | - | Client ID (FK to clients.id) |
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `CURRENT_TIMESTAMP` | Creation timestamp |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `CURRENT_TIMESTAMP` | Last update timestamp |

**Constraints:**
- Primary Key: `authorized_domain_clients_pkey` on `(domain_id, client_id)`
- Foreign Key: `authorized_domain_clients_domain_id_fkey` → `authorized_domains(id)`
- Foreign Key: `authorized_domain_clients_client_id_fkey` → `clients(id)`

---

## Row-Level Security (RLS)

The following tables have RLS enabled for multi-tenant isolation:

- `clients`
- `process_voc`
- `data_sources` (if it has `client_id`)
- `dimension_definitions` (if it has `client_id`)

RLS policies ensure that:
- **Founder users** (`is_founder = TRUE`) can access all data
- **Regular users** can only access data for clients where they have active memberships
- Access is controlled via the `app.user_id` session variable set by `TenantContext`

---

## Key Relationships

```
users (founder_user_id) → clients
users (id) → memberships (user_id)
clients (id) → memberships (client_id)
clients (id) → process_voc (client_uuid)
clients (id) → data_sources (client_id)
clients (id) → dimension_summaries (client_uuid)
clients (id) → insights (client_id)
data_sources (id) → dimension_names (data_source_id)
```

---

## Notes

1. **Multi-Tenant Architecture**: The system uses Row-Level Security (RLS) for tenant isolation
2. **Founder Users**: Users with `is_founder = TRUE` have access to all clients
3. **Membership Roles**: `owner` > `admin` > `editor` > `viewer`
4. **Duplicate Prevention**: `process_voc` uses `(respondent_id, dimension_ref)` unique constraint
5. **Client Linking**: `process_voc.client_uuid` links to `clients.id` for proper RLS enforcement
