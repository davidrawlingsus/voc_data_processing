-- Migration: Modify unique constraint to allow multiple values per respondent-dimension
-- Description: Changes the unique constraint from (respondent_id, dimension_ref) to 
--              (respondent_id, dimension_ref, MD5(value)) to support multi-select questions
--              where a respondent can have multiple answer values for the same question.
--              Uses MD5 hash because value column can be very large (TEXT type).
-- Date: 2025-01-XX

-- ============================================================================
-- MODIFY UNIQUE CONSTRAINT TO INCLUDE VALUE (via MD5 hash)
-- ============================================================================
-- This allows multiple rows with the same (respondent_id, dimension_ref) 
-- as long as the value is different, which is needed for multi-select questions
-- where a respondent can select multiple answer options.
-- Uses MD5 hash of value because TEXT values can exceed index size limits.

-- Drop the existing unique constraint
ALTER TABLE process_voc 
DROP CONSTRAINT IF EXISTS fk_respondent_dimension;

-- Add a computed column for the MD5 hash of value (for indexing)
ALTER TABLE process_voc 
ADD COLUMN IF NOT EXISTS value_hash VARCHAR(32) GENERATED ALWAYS AS (MD5(COALESCE(value, ''))) STORED;

-- Create index on the hash column
CREATE INDEX IF NOT EXISTS idx_process_voc_value_hash ON process_voc(value_hash);

-- Add the new unique constraint using the hash
ALTER TABLE process_voc 
ADD CONSTRAINT fk_respondent_dimension_value 
UNIQUE (respondent_id, dimension_ref, value_hash);

-- Add a comment explaining the constraint
COMMENT ON CONSTRAINT fk_respondent_dimension_value ON process_voc IS 
'Ensures uniqueness per respondent-dimension-value combination. Allows multiple answer values per respondent for the same question (e.g., multi-select questions). Uses MD5 hash of value because TEXT values can be very large.';
COMMENT ON COLUMN process_voc.value_hash IS 'MD5 hash of value column, used for unique constraint to support multi-select questions';
