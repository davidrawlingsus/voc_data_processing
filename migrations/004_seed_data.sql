-- Migration: Seed Data for Multi-Tenant System
-- Description: Creates founder user and sample clients/memberships for testing
-- Date: 2025-11-03

-- ============================================================================
-- SEED FOUNDER USER
-- ============================================================================
-- Create the founder user (you - the user who requested this feature)
-- Replace email and name with your actual details
INSERT INTO users (id, email, name, is_founder, is_active, email_verified_at, metadata)
VALUES (
    gen_random_uuid(),
    'david@rawlings.us',
    'David Rawlings',
    TRUE,
    TRUE,
    CURRENT_TIMESTAMP,
    '{"source": "seed_data", "created_by": "migration"}'::jsonb
)
ON CONFLICT (email) DO UPDATE SET
    is_founder = TRUE,
    is_active = TRUE,
    updated_at = CURRENT_TIMESTAMP;

-- Store founder user ID in a variable for later use
DO $$
DECLARE
    v_founder_id UUID;
    v_client_1_id UUID;
    v_client_2_id UUID;
    v_regular_user_id UUID;
BEGIN
    -- Get founder user ID
    SELECT id INTO v_founder_id FROM users WHERE email = 'david@rawlings.us' AND is_founder = TRUE LIMIT 1;
    
    -- ============================================================================
    -- SEED SAMPLE CLIENTS
    -- ============================================================================
    -- Create sample clients that the founder can manage
    
    -- Client 1: Ancient & Brave (from your existing data)
    INSERT INTO clients (id, name, slug, is_active, founder_user_id, settings, created_at, updated_at)
    VALUES (
        gen_random_uuid(),
        'Ancient & Brave',
        'ancient-brave',
        TRUE,
        v_founder_id,
        '{"source": "seed_data", "external_client_id": "cl_658e8f6a7a"}'::jsonb,
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
    )
    ON CONFLICT (slug) DO UPDATE SET
        founder_user_id = v_founder_id,
        updated_at = CURRENT_TIMESTAMP
    RETURNING id INTO v_client_1_id;
    
    -- If conflict, get existing ID
    IF v_client_1_id IS NULL THEN
        SELECT id INTO v_client_1_id FROM clients WHERE slug = 'ancient-brave';
    END IF;
    
    -- Client 2: Sample Client
    INSERT INTO clients (id, name, slug, is_active, founder_user_id, settings, created_at, updated_at)
    VALUES (
        gen_random_uuid(),
        'Sample Client Co',
        'sample-client',
        TRUE,
        v_founder_id,
        '{"source": "seed_data"}'::jsonb,
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
    )
    ON CONFLICT (slug) DO UPDATE SET
        founder_user_id = v_founder_id,
        updated_at = CURRENT_TIMESTAMP
    RETURNING id INTO v_client_2_id;
    
    -- If conflict, get existing ID
    IF v_client_2_id IS NULL THEN
        SELECT id INTO v_client_2_id FROM clients WHERE slug = 'sample-client';
    END IF;
    
    -- ============================================================================
    -- SEED REGULAR USER (non-founder)
    -- ============================================================================
    INSERT INTO users (id, email, name, is_founder, is_active, email_verified_at, metadata)
    VALUES (
        gen_random_uuid(),
        'user@example.com',
        'Regular User',
        FALSE,
        TRUE,
        CURRENT_TIMESTAMP,
        '{"source": "seed_data"}'::jsonb
    )
    ON CONFLICT (email) DO NOTHING
    RETURNING id INTO v_regular_user_id;
    
    -- If conflict, get existing ID
    IF v_regular_user_id IS NULL THEN
        SELECT id INTO v_regular_user_id FROM users WHERE email = 'user@example.com';
    END IF;
    
    -- ============================================================================
    -- SEED MEMBERSHIPS
    -- ============================================================================
    
    -- Founder automatically has access to all clients via is_founder flag,
    -- but we can create explicit memberships for clarity/consistency
    -- (Optional - founders don't strictly need memberships)
    
    -- Regular user: owner of Client 1
    INSERT INTO memberships (user_id, client_id, role, status, invited_by, invited_at, joined_at, metadata)
    VALUES (
        v_regular_user_id,
        v_client_1_id,
        'owner',
        'active',
        v_founder_id,
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP,
        '{"source": "seed_data"}'::jsonb
    )
    ON CONFLICT (user_id, client_id) DO UPDATE SET
        role = 'owner',
        status = 'active',
        updated_at = CURRENT_TIMESTAMP;
    
    -- Regular user: editor of Client 2
    INSERT INTO memberships (user_id, client_id, role, status, invited_by, invited_at, joined_at, metadata)
    VALUES (
        v_regular_user_id,
        v_client_2_id,
        'editor',
        'active',
        v_founder_id,
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP,
        '{"source": "seed_data"}'::jsonb
    )
    ON CONFLICT (user_id, client_id) DO UPDATE SET
        role = 'editor',
        status = 'active',
        updated_at = CURRENT_TIMESTAMP;
    
    RAISE NOTICE 'Seed data created successfully:';
    RAISE NOTICE '  Founder user ID: %', v_founder_id;
    RAISE NOTICE '  Client 1 (Ancient & Brave) ID: %', v_client_1_id;
    RAISE NOTICE '  Client 2 (Sample Client) ID: %', v_client_2_id;
    RAISE NOTICE '  Regular user ID: %', v_regular_user_id;
    
END $$;

-- ============================================================================
-- UPDATE EXISTING PROCESS_VOC DATA (if applicable)
-- ============================================================================
-- If you have existing process_voc rows with client_id = 'cl_658e8f6a7a',
-- you can link them to the new client_uuid column
-- This is optional and can be run separately if needed

-- Uncomment and adjust if you want to auto-link existing data:
/*
UPDATE process_voc pv
SET client_uuid = c.id
FROM clients c
WHERE pv.client_id = 'cl_658e8f6a7a'
  AND c.settings->>'external_client_id' = pv.client_id
  AND pv.client_uuid IS NULL;
*/
