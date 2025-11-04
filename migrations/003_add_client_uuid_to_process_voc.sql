-- Migration: Add client_uuid to process_voc for proper RLS linking
-- Description: Adds UUID column to link process_voc to clients table for RLS policies
-- Date: 2025-11-03

-- ============================================================================
-- ADD CLIENT_UUID COLUMN TO PROCESS_VOC
-- ============================================================================
-- The existing client_id (VARCHAR) is kept for compatibility (may be Caplena API ID)
-- We add client_uuid (UUID) to properly link with clients.id for RLS

ALTER TABLE process_voc 
ADD COLUMN IF NOT EXISTS client_uuid UUID REFERENCES clients(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_process_voc_client_uuid ON process_voc(client_uuid);

COMMENT ON COLUMN process_voc.client_id IS 'Original client identifier (may be external API ID) - kept for compatibility';
COMMENT ON COLUMN process_voc.client_uuid IS 'UUID reference to clients.id - used for RLS and proper tenant isolation';

-- ============================================================================
-- HELPER FUNCTION FOR INSERT POLICY
-- ============================================================================
-- Create a helper function that can be called from INSERT policy to check access
CREATE OR REPLACE FUNCTION can_insert_process_voc(check_client_uuid UUID)
RETURNS BOOLEAN AS $$
DECLARE
    v_user_id UUID;
BEGIN
    v_user_id := current_setting('app.user_id', true)::UUID;
    
    -- Founder can insert
    IF EXISTS (
        SELECT 1 FROM users
        WHERE id = v_user_id AND is_founder = TRUE AND is_active = TRUE
    ) THEN
        RETURN TRUE;
    END IF;
    
    -- Regular users: check membership with edit role
    IF EXISTS (
        SELECT 1 FROM memberships m
        INNER JOIN clients c ON c.id = m.client_id
        WHERE m.user_id = v_user_id
          AND m.client_id = check_client_uuid
          AND m.status = 'active'
          AND m.role IN ('owner', 'admin', 'editor')
          AND c.is_active = TRUE
    ) THEN
        RETURN TRUE;
    END IF;
    
    RETURN FALSE;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

COMMENT ON FUNCTION can_insert_process_voc(UUID) IS 'Checks if current user can insert process_voc rows for the given client_uuid';

-- ============================================================================
-- UPDATE RLS POLICIES TO USE CLIENT_UUID
-- ============================================================================
-- Drop old policies that used client_id matching
DROP POLICY IF EXISTS process_voc_select_policy ON process_voc;
DROP POLICY IF EXISTS process_voc_insert_policy ON process_voc;
DROP POLICY IF EXISTS process_voc_update_policy ON process_voc;
DROP POLICY IF EXISTS process_voc_delete_policy ON process_voc;

-- Recreate policies using client_uuid for proper RLS

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
        -- Regular users: check membership via client_uuid
        client_uuid IS NOT NULL
        AND EXISTS (
            SELECT 1 FROM memberships
            WHERE user_id = current_setting('app.user_id', true)::UUID
              AND client_id = process_voc.client_uuid
              AND status = 'active'
        )
    );

-- Note: INSERT policy with NEW.client_uuid has issues in some PostgreSQL versions
-- Using a trigger instead for INSERT validation
CREATE POLICY process_voc_insert_policy ON process_voc
    FOR INSERT
    WITH CHECK (true);  -- RLS allows, trigger enforces

-- Create trigger function for INSERT validation
CREATE OR REPLACE FUNCTION check_process_voc_insert()
RETURNS TRIGGER AS $$
BEGIN
    IF NOT can_insert_process_voc(NEW.client_uuid) THEN
        RAISE EXCEPTION 'User does not have permission to insert process_voc rows for this client';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER process_voc_insert_check
    BEFORE INSERT ON process_voc
    FOR EACH ROW
    EXECUTE FUNCTION check_process_voc_insert();

COMMENT ON FUNCTION check_process_voc_insert() IS 'Trigger function to validate INSERT permissions on process_voc using RLS-style checks';

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
        client_uuid IS NOT NULL
        AND EXISTS (
            SELECT 1 FROM memberships
            WHERE user_id = current_setting('app.user_id', true)::UUID
              AND client_id = process_voc.client_uuid
              AND status = 'active'
              AND role IN ('owner', 'admin', 'editor')
        )
    );

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
        client_uuid IS NOT NULL
        AND EXISTS (
            SELECT 1 FROM memberships
            WHERE user_id = current_setting('app.user_id', true)::UUID
              AND client_id = process_voc.client_uuid
              AND status = 'active'
              AND role IN ('owner', 'admin')
        )
    );
