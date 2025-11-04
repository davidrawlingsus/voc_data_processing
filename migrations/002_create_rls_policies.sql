-- Migration: Create Row-Level Security (RLS) Policies
-- Description: Enables RLS and creates policies for tenant isolation
-- Date: 2025-11-03

-- ============================================================================
-- HELPER FUNCTION: Get accessible client IDs for current user
-- ============================================================================
-- This function returns an array of client_ids the current user can access
-- It checks: 1) if user is founder (all clients), 2) active memberships
CREATE OR REPLACE FUNCTION get_accessible_client_ids()
RETURNS UUID[] AS $$
DECLARE
    v_user_id UUID;
    v_is_founder BOOLEAN;
    v_client_ids UUID[];
BEGIN
    -- Get current user_id from session variable
    v_user_id := current_setting('app.user_id', true)::UUID;
    
    -- If no user_id set, return empty array (no access)
    IF v_user_id IS NULL THEN
        RETURN ARRAY[]::UUID[];
    END IF;
    
    -- Check if user is founder
    SELECT is_founder INTO v_is_founder
    FROM users
    WHERE id = v_user_id AND is_active = TRUE;
    
    -- Founder users can access all active clients
    IF v_is_founder = TRUE THEN
        SELECT ARRAY_AGG(id) INTO v_client_ids
        FROM clients
        WHERE is_active = TRUE;
        
        RETURN COALESCE(v_client_ids, ARRAY[]::UUID[]);
    END IF;
    
    -- Regular users: get client_ids from active memberships
    SELECT ARRAY_AGG(DISTINCT client_id) INTO v_client_ids
    FROM memberships
    WHERE user_id = v_user_id
      AND status = 'active'
      AND client_id IN (SELECT id FROM clients WHERE is_active = TRUE);
    
    RETURN COALESCE(v_client_ids, ARRAY[]::UUID[]);
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

COMMENT ON FUNCTION get_accessible_client_ids() IS 'Returns array of client IDs accessible by the current user (from app.user_id session variable). Founders get all active clients, others get their active memberships.';

-- ============================================================================
-- HELPER FUNCTION: Check if current user can access a specific client
-- ============================================================================
CREATE OR REPLACE FUNCTION can_access_client(check_client_id UUID)
RETURNS BOOLEAN AS $$
DECLARE
    v_accessible_ids UUID[];
BEGIN
    v_accessible_ids := get_accessible_client_ids();
    RETURN check_client_id = ANY(v_accessible_ids);
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

COMMENT ON FUNCTION can_access_client(UUID) IS 'Returns TRUE if current user can access the specified client_id';

-- ============================================================================
-- HELPER FUNCTION: Get user role for a specific client
-- ============================================================================
CREATE OR REPLACE FUNCTION get_user_role_for_client(check_client_id UUID)
RETURNS VARCHAR AS $$
DECLARE
    v_user_id UUID;
    v_is_founder BOOLEAN;
    v_role VARCHAR;
BEGIN
    v_user_id := current_setting('app.user_id', true)::UUID;
    
    IF v_user_id IS NULL THEN
        RETURN NULL;
    END IF;
    
    -- Founders have 'owner' role for all clients
    SELECT is_founder INTO v_is_founder
    FROM users
    WHERE id = v_user_id AND is_active = TRUE;
    
    IF v_is_founder = TRUE THEN
        RETURN 'owner';
    END IF;
    
    -- Get role from active membership
    SELECT role INTO v_role
    FROM memberships
    WHERE user_id = v_user_id
      AND client_id = check_client_id
      AND status = 'active';
    
    RETURN v_role;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

COMMENT ON FUNCTION get_user_role_for_client(UUID) IS 'Returns the role of current user for specified client (owner/admin/editor/viewer)';

-- ============================================================================
-- ENABLE RLS ON CLIENT-SCOPED TABLES
-- ============================================================================

-- Enable RLS on clients table
ALTER TABLE clients ENABLE ROW LEVEL SECURITY;

-- Enable RLS on process_voc table
ALTER TABLE process_voc ENABLE ROW LEVEL SECURITY;

-- Enable RLS on data_sources table (if it has client_id)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns 
               WHERE table_name = 'data_sources' AND column_name = 'client_id') THEN
        ALTER TABLE data_sources ENABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- Enable RLS on dimension_definitions if it has client_id
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns 
               WHERE table_name = 'dimension_definitions' AND column_name = 'client_id') THEN
        ALTER TABLE dimension_definitions ENABLE ROW LEVEL SECURITY;
    END IF;
END $$;

-- ============================================================================
-- RLS POLICIES FOR CLIENTS TABLE
-- ============================================================================

-- Drop existing policies if they exist (for idempotency)
DROP POLICY IF EXISTS clients_select_policy ON clients;
DROP POLICY IF EXISTS clients_insert_policy ON clients;
DROP POLICY IF EXISTS clients_update_policy ON clients;

-- Policy: Users can SELECT clients they have access to
CREATE POLICY clients_select_policy ON clients
    FOR SELECT
    USING (
        -- Founder can see all active clients
        EXISTS (
            SELECT 1 FROM users
            WHERE id = current_setting('app.user_id', true)::UUID
              AND is_founder = TRUE
              AND is_active = TRUE
        )
        OR
        -- Regular users can see clients they have active membership in
        EXISTS (
            SELECT 1 FROM memberships
            WHERE user_id = current_setting('app.user_id', true)::UUID
              AND client_id = clients.id
              AND status = 'active'
        )
    );

-- Policy: Only founders and client owners/admins can INSERT clients
-- (Assuming only founders create new clients for now)
CREATE POLICY clients_insert_policy ON clients
    FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM users
            WHERE id = current_setting('app.user_id', true)::UUID
              AND is_founder = TRUE
              AND is_active = TRUE
        )
    );

-- Policy: Only founders and client owners/admins can UPDATE clients
CREATE POLICY clients_update_policy ON clients
    FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM users
            WHERE id = current_setting('app.user_id', true)::UUID
              AND is_founder = TRUE
              AND is_active = TRUE
        )
        OR
        get_user_role_for_client(clients.id) IN ('owner', 'admin')
    );

-- ============================================================================
-- RLS POLICIES FOR PROCESS_VOC TABLE
-- ============================================================================
-- Note: process_voc.client_id is VARCHAR, so we need to handle the type mismatch
-- We'll need to join with clients table or use a lookup

-- Helper function to get UUID client_id from VARCHAR client_id in process_voc
-- This assumes client_id in process_voc might reference clients by a different identifier
-- For now, we'll create a policy that works if client_id matches clients.id
-- If process_voc.client_id is actually a different identifier, we may need to add a mapping

-- Policy: Users can SELECT process_voc rows for accessible clients
-- Since process_voc has VARCHAR client_id and clients has UUID id, we need to check both
-- Let's assume process_voc.client_id might need to be mapped or we add a UUID column
-- For now, create a flexible policy

-- Drop existing policies if they exist (for idempotency)
DROP POLICY IF EXISTS process_voc_select_policy ON process_voc;
DROP POLICY IF EXISTS process_voc_insert_policy ON process_voc;
DROP POLICY IF EXISTS process_voc_update_policy ON process_voc;
DROP POLICY IF EXISTS process_voc_delete_policy ON process_voc;

-- Policy: Users can SELECT process_voc rows for accessible clients
-- Note: This policy is basic and will be replaced by migration 003 with client_uuid-based logic
CREATE POLICY process_voc_select_policy ON process_voc
    FOR SELECT
    USING (
        -- Founder can see all rows
        EXISTS (
            SELECT 1 FROM users
            WHERE id = current_setting('app.user_id', true)::UUID
              AND is_founder = TRUE
              AND is_active = TRUE
        )
        OR
        -- Regular users: Allow if they have any active membership
        -- More precise checking based on client_id will be done in migration 003
        EXISTS (
            SELECT 1 FROM memberships
            WHERE user_id = current_setting('app.user_id', true)::UUID
              AND status = 'active'
        )
    );

-- Policy: Users can INSERT process_voc rows for clients they can edit
-- Note: This policy is basic and will be replaced by migration 003 with client_uuid-based logic
CREATE POLICY process_voc_insert_policy ON process_voc
    FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM users
            WHERE id = current_setting('app.user_id', true)::UUID
              AND is_founder = TRUE
              AND is_active = TRUE
        )
        OR
        -- Allow if user has any active membership with edit role
        -- More precise checking will be done in migration 003
        EXISTS (
            SELECT 1 FROM memberships
            WHERE user_id = current_setting('app.user_id', true)::UUID
              AND status = 'active'
              AND role IN ('owner', 'admin', 'editor')
        )
    );

-- Policy: Users can UPDATE process_voc rows for clients they can edit
-- Note: This policy is basic and will be replaced by migration 003 with client_uuid-based logic
CREATE POLICY process_voc_update_policy ON process_voc
    FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM users
            WHERE id = current_setting('app.user_id', true)::UUID
              AND is_founder = TRUE
              AND is_active = TRUE
        )
        OR
        -- Allow if user has any active membership with edit role
        -- More precise checking will be done in migration 003
        EXISTS (
            SELECT 1 FROM memberships
            WHERE user_id = current_setting('app.user_id', true)::UUID
              AND status = 'active'
              AND role IN ('owner', 'admin', 'editor')
        )
    );

-- Policy: Users can DELETE process_voc rows for clients they can manage
-- Note: This policy is basic and will be replaced by migration 003 with client_uuid-based logic
CREATE POLICY process_voc_delete_policy ON process_voc
    FOR DELETE
    USING (
        EXISTS (
            SELECT 1 FROM users
            WHERE id = current_setting('app.user_id', true)::UUID
              AND is_founder = TRUE
              AND is_active = TRUE
        )
        OR
        -- Allow if user has any active membership with manage role
        -- More precise checking will be done in migration 003
        EXISTS (
            SELECT 1 FROM memberships
            WHERE user_id = current_setting('app.user_id', true)::UUID
              AND status = 'active'
              AND role IN ('owner', 'admin')
        )
    );

-- ============================================================================
-- RLS POLICIES FOR MEMBERSHIPS TABLE
-- ============================================================================

-- Drop existing policies if they exist (for idempotency)
DROP POLICY IF EXISTS memberships_select_policy ON memberships;
DROP POLICY IF EXISTS memberships_insert_policy ON memberships;
DROP POLICY IF EXISTS memberships_update_policy ON memberships;
DROP POLICY IF EXISTS memberships_delete_policy ON memberships;

-- Users can view their own memberships or memberships for clients they manage
CREATE POLICY memberships_select_policy ON memberships
    FOR SELECT
    USING (
        -- Can see own memberships
        user_id = current_setting('app.user_id', true)::UUID
        OR
        -- Founders can see all
        EXISTS (
            SELECT 1 FROM users
            WHERE id = current_setting('app.user_id', true)::UUID
              AND is_founder = TRUE
              AND is_active = TRUE
        )
        OR
        -- Admins/owners can see memberships for their clients
        EXISTS (
            SELECT 1 FROM memberships m
            WHERE m.user_id = current_setting('app.user_id', true)::UUID
              AND m.client_id = memberships.client_id
              AND m.status = 'active'
              AND m.role IN ('owner', 'admin')
        )
    );

-- Only founders and client owners/admins can create memberships
CREATE POLICY memberships_insert_policy ON memberships
    FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM users
            WHERE id = current_setting('app.user_id', true)::UUID
              AND is_founder = TRUE
              AND is_active = TRUE
        )
        OR
        get_user_role_for_client(client_id) IN ('owner', 'admin')
    );

-- Similar for UPDATE and DELETE
CREATE POLICY memberships_update_policy ON memberships
    FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM users
            WHERE id = current_setting('app.user_id', true)::UUID
              AND is_founder = TRUE
              AND is_active = TRUE
        )
        OR
        get_user_role_for_client(client_id) IN ('owner', 'admin')
    );

CREATE POLICY memberships_delete_policy ON memberships
    FOR DELETE
    USING (
        EXISTS (
            SELECT 1 FROM users
            WHERE id = current_setting('app.user_id', true)::UUID
              AND is_founder = TRUE
              AND is_active = TRUE
        )
        OR
        get_user_role_for_client(client_id) IN ('owner', 'admin')
    );
