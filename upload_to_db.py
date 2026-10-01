#!/usr/bin/env python3
"""
Script to upload flattened JSON data to the process_voc table in PostgreSQL.
Reads database credentials from .env file and uploads data from flattened JSON.
"""

import json
import os
import re
import sys
import uuid
from datetime import datetime
from typing import Optional, Dict, List
import psycopg2
from psycopg2.extras import execute_values
from tenant_context import TenantContext

# Try to load dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Get database credentials from environment
DATABASE_URL = os.getenv('DATABASE_PUBLIC_URL') or os.getenv('DATABASE_URL')
if not DATABASE_URL:
    print("❌ Error: DATABASE_PUBLIC_URL or DATABASE_URL not found in environment!")
    sys.exit(1)

# Default JSON file path
JSON_FILE = os.getenv('FLATTENED_JSON_FILE', 'outputs/all_projects_flattened.json')


def get_founder_user_id(conn) -> Optional[uuid.UUID]:
    """Get the founder user ID from the database."""
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id FROM users 
            WHERE is_founder = TRUE AND is_active = TRUE 
            LIMIT 1
        """)
        result = cursor.fetchone()
        return uuid.UUID(result[0]) if result else None
    finally:
        cursor.close()


def get_or_create_client(conn, client_uuid_str: Optional[str], client_name: Optional[str], founder_user_id: Optional[uuid.UUID]) -> Optional[str]:
    """Get or create a client and return its UUID as string."""
    if not client_uuid_str and not client_name:
        return None
    
    cursor = conn.cursor()
    try:
        # First, try to find existing client by UUID
        if client_uuid_str:
            try:
                test_uuid = uuid.UUID(client_uuid_str)
                cursor.execute("""
                    SELECT id FROM clients 
                    WHERE id = %s AND is_active = TRUE
                    LIMIT 1
                """, (str(test_uuid),))
                result = cursor.fetchone()
                if result:
                    return str(result[0])
            except (ValueError, TypeError):
                pass
        
        # Try to find by name
        if client_name:
            cursor.execute("""
                SELECT id FROM clients 
                WHERE name = %s AND is_active = TRUE
                LIMIT 1
            """, (client_name,))
            result = cursor.fetchone()
            if result:
                return str(result[0])
            
            # Create new client if not found and we have founder access
            if founder_user_id:
                new_client_id = uuid.uuid4()
                # Generate slug from name
                slug = client_name.lower().replace(' ', '-').replace('_', '-')[:50]
                # Remove special characters from slug
                slug = re.sub(r'[^a-z0-9-]', '', slug)
                
                cursor.execute("""
                    INSERT INTO clients (id, name, slug, is_active, founder_user_id, settings)
                    VALUES (%s, %s, %s, TRUE, %s, %s)
                    ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id
                """, (
                    str(new_client_id),
                    client_name,
                    slug,
                    str(founder_user_id),
                    json.dumps({'external_client_id': client_uuid_str} if client_uuid_str else {})
                ))
                result = cursor.fetchone()
                conn.commit()
                if result:
                    print(f"   ✅ Created new client: {client_name} ({result[0]})")
                    return str(result[0])
        
        return None
    finally:
        cursor.close()


def parse_datetime(date_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO format datetime string."""
    if not date_str:
        return None
    try:
        if isinstance(date_str, str):
            # Handle ISO format with or without timezone
            if 'T' in date_str:
                # Try to parse ISO format
                try:
                    # Handle timezone offset like +00:00
                    if '+' in date_str and date_str.count('+') == 1:
                        return datetime.fromisoformat(date_str)
                    # Handle Z suffix
                    elif date_str.endswith('Z'):
                        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    else:
                        return datetime.fromisoformat(date_str)
                except ValueError:
                    # Try without microseconds
                    date_str_clean = date_str.split('.')[0] if '.' in date_str else date_str
                    if '+' in date_str_clean:
                        return datetime.fromisoformat(date_str_clean)
                    elif date_str_clean.endswith('Z'):
                        return datetime.fromisoformat(date_str_clean.replace('Z', '+00:00'))
                    return datetime.fromisoformat(date_str_clean)
            else:
                # Just a date
                return datetime.strptime(date_str, '%Y-%m-%d')
        return date_str
    except (ValueError, TypeError) as e:
        # Silently return None for invalid dates
        return None


def upload_flattened_data(json_file: str, batch_size: int = 1000):
    """Upload flattened JSON data to process_voc table."""
    
    # Load JSON data
    print(f"📖 Loading data from {json_file}...")
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ Error: File not found: {json_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON - {e}")
        sys.exit(1)
    
    flattened_results = data.get('flattened_results', [])
    if not flattened_results:
        print("❌ Error: No 'flattened_results' found in JSON file")
        sys.exit(1)
    
    print(f"✅ Loaded {len(flattened_results)} entries from JSON file")
    
    # Connect to database
    print(f"\n🔌 Connecting to database...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
    except Exception as e:
        print(f"❌ Error connecting to database: {e}")
        sys.exit(1)
    
    print("✅ Connected to database")
    
    # Get founder user ID for context
    founder_user_id = get_founder_user_id(conn)
    if not founder_user_id:
        print("⚠️  Warning: No founder user found. Upload may fail due to RLS policies.")
        print("   Proceeding anyway...")
    else:
        print(f"✅ Found founder user ID: {founder_user_id}")
    
    # Set tenant context for all operations
    # First, collect all unique clients and ensure they exist
    print(f"\n📋 Checking and creating clients...")
    client_cache = {}  # Cache client UUIDs we've already resolved
    
    unique_clients = set()
    for entry in flattened_results:
        client_uuid_str = entry.get('client_uuid')
        client_name = entry.get('client_name')
        if client_uuid_str or client_name:
            unique_clients.add((client_uuid_str, client_name))
    
    print(f"   Found {len(unique_clients)} unique clients to check")
    
    # Ensure all clients exist (within tenant context)
    with TenantContext(conn, founder_user_id):
        for client_uuid_str, client_name in unique_clients:
            cache_key = (client_uuid_str, client_name)
            if cache_key not in client_cache:
                resolved_uuid = get_or_create_client(conn, client_uuid_str, client_name, founder_user_id)
                client_cache[cache_key] = resolved_uuid
    
    print(f"   ✅ Resolved {len([v for v in client_cache.values() if v])} clients")
    
    # Prepare data for insertion
    print(f"\n📦 Preparing data for insertion...")
    rows_to_insert = []
    skipped_no_client = 0
    
    for i, entry in enumerate(flattened_results, 1):
        # Get client_uuid from cache
        client_uuid_str = entry.get('client_uuid')
        client_name = entry.get('client_name')
        cache_key = (client_uuid_str, client_name)
        client_uuid = client_cache.get(cache_key)
        
        # Skip rows without a valid client UUID (foreign key constraint)
        if not client_uuid:
            skipped_no_client += 1
            continue
        
        # Parse dates
        created_dt = parse_datetime(entry.get('created'))
        last_modified_dt = parse_datetime(entry.get('last_modified'))
        
        # Prepare row data (matching actual database schema)
        # Get survey_metadata, question_text, and question_type
        survey_metadata = entry.get('survey_metadata')
        question_text = entry.get('question_text')
        question_type = entry.get('question_type')
        
        row_data = (
            entry.get('respondent_id'),
            created_dt,
            last_modified_dt,
            entry.get('client_id'),
            entry.get('client_name'),
            entry.get('project_id'),
            entry.get('project_name'),
            entry.get('total_rows'),
            entry.get('data_source'),
            entry.get('dimension_ref'),
            entry.get('dimension_name'),
            entry.get('value'),
            entry.get('overall_sentiment'),
            json.dumps(entry.get('topics', [])) if entry.get('topics') else None,
            datetime.now(),  # created_at
            datetime.now(),  # updated_at
            client_uuid,
            json.dumps(survey_metadata) if survey_metadata else None,  # survey_metadata
            question_text,  # question_text
            question_type  # question_type
        )
        rows_to_insert.append(row_data)
        
        if i % 10000 == 0:
            print(f"   Processed {i:,} entries...")
    
    print(f"✅ Prepared {len(rows_to_insert):,} rows for insertion")
    if skipped_no_client > 0:
        print(f"   ⚠️  Skipped {skipped_no_client:,} rows without valid client UUID")
    
    # Insert data in batches
    print(f"\n💾 Uploading data to database (batch size: {batch_size})...")
    
    # Use ON CONFLICT to update existing rows based on unique constraint (respondent_id, dimension_ref, value_hash)
    # Note: value_hash is a computed column (MD5 hash of value) used for the unique constraint
    insert_query = """
        INSERT INTO process_voc (
            respondent_id, created, last_modified, client_id, client_name,
            project_id, project_name, total_rows, data_source,
            dimension_ref, dimension_name, value, overall_sentiment, topics,
            created_at, updated_at, client_uuid, survey_metadata, question_text, question_type
        ) VALUES %s
        ON CONFLICT (respondent_id, dimension_ref, value_hash) DO UPDATE SET
            created = EXCLUDED.created,
            last_modified = EXCLUDED.last_modified,
            client_id = EXCLUDED.client_id,
            client_name = EXCLUDED.client_name,
            project_id = EXCLUDED.project_id,
            project_name = EXCLUDED.project_name,
            total_rows = EXCLUDED.total_rows,
            data_source = EXCLUDED.data_source,
            dimension_name = EXCLUDED.dimension_name,
            value = EXCLUDED.value,
            overall_sentiment = EXCLUDED.overall_sentiment,
            topics = EXCLUDED.topics,
            created_at = EXCLUDED.created_at,
            updated_at = EXCLUDED.updated_at,
            client_uuid = EXCLUDED.client_uuid,
            survey_metadata = EXCLUDED.survey_metadata,
            question_text = EXCLUDED.question_text,
            question_type = EXCLUDED.question_type
    """
    
    try:
        with TenantContext(conn, founder_user_id):
            cursor = conn.cursor()
            
            total_inserted = 0
            for i in range(0, len(rows_to_insert), batch_size):
                batch = rows_to_insert[i:i + batch_size]
                try:
                    execute_values(cursor, insert_query, batch, page_size=batch_size)
                    inserted = cursor.rowcount
                    total_inserted += inserted
                    conn.commit()
                    print(f"   ✓ Inserted batch {i//batch_size + 1} ({len(batch)} rows, {inserted} new rows)")
                except Exception as e:
                    conn.rollback()
                    print(f"   ✗ Error inserting batch {i//batch_size + 1}: {e}")
                    raise
            
            cursor.close()
        
        print(f"\n✅ Successfully uploaded {total_inserted:,} rows to process_voc table")
        
    except Exception as e:
        print(f"\n❌ Error during upload: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()
        print("✅ Database connection closed")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Upload flattened JSON data to process_voc table')
    parser.add_argument('--file', '-f', default=JSON_FILE, help='Path to flattened JSON file')
    parser.add_argument('--batch-size', '-b', type=int, default=1000, help='Batch size for inserts')
    
    args = parser.parse_args()
    
    upload_flattened_data(args.file, args.batch_size)
