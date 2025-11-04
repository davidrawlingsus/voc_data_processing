-- Migration: Create Multi-Tenant Tables
-- Description: Creates users and memberships tables for multi-tenant access control
-- Date: 2025-11-03

-- ============================================================================
-- USERS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255),
    is_founder BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    email_verified_at TIMESTAMP WITH TIME ZONE,
    last_login_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_is_founder ON users(is_founder);
CREATE INDEX idx_users_is_active ON users(is_active);

-- ============================================================================
-- MEMBERSHIPS TABLE
-- ============================================================================
-- Links users to clients with role-based access control
CREATE TABLE IF NOT EXISTS memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL DEFAULT 'viewer',
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    invited_by UUID REFERENCES users(id),
    invited_at TIMESTAMP WITH TIME ZONE,
    joined_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT memberships_user_client_unique UNIQUE (user_id, client_id),
    CONSTRAINT memberships_role_check CHECK (role IN ('owner', 'admin', 'editor', 'viewer')),
    CONSTRAINT memberships_status_check CHECK (status IN ('active', 'inactive', 'pending', 'suspended'))
);

CREATE INDEX idx_memberships_user_id ON memberships(user_id);
CREATE INDEX idx_memberships_client_id ON memberships(client_id);
CREATE INDEX idx_memberships_status ON memberships(status);
CREATE INDEX idx_memberships_role ON memberships(role);
CREATE INDEX idx_memberships_user_status ON memberships(user_id, status);

-- ============================================================================
-- UPDATE CLIENTS TABLE (if needed)
-- ============================================================================
-- Ensure clients table has all necessary fields
DO $$
BEGIN
    -- Add founder_user_id if it doesn't exist (for tracking which user created the client)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'clients' AND column_name = 'founder_user_id'
    ) THEN
        ALTER TABLE clients ADD COLUMN founder_user_id UUID REFERENCES users(id);
    END IF;
END $$;

-- ============================================================================
-- COMMENTS FOR DOCUMENTATION
-- ============================================================================
COMMENT ON TABLE users IS 'User accounts with authentication and profile information';
COMMENT ON TABLE memberships IS 'Many-to-many relationship between users and clients with role-based access';
COMMENT ON COLUMN users.is_founder IS 'Founder users have access to all clients regardless of memberships';
COMMENT ON COLUMN memberships.role IS 'Access level: owner (full control), admin (manage users), editor (edit data), viewer (read-only)';
COMMENT ON COLUMN memberships.status IS 'Membership state: active (can access), inactive (disabled), pending (invitation sent), suspended (temporarily blocked)';
