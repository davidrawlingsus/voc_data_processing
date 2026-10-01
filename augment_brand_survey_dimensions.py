#!/usr/bin/env python3
"""
Script to augment Brand Survey data with Core Values and Trust Drivers dimensions.
These are multi-select questions where each answer option is a separate column.
Creates dimension entries grouped under a single dimension_ref for each question.
"""

import json
import os
import sys
from datetime import datetime
from caplena import Client
from upload_to_db import upload_flattened_data
from tenant_context import TenantContext

# Try to load dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from config import Config

# Metadata label mapping: Column name/ref -> Human-readable label for survey_metadata
METADATA_LABEL_MAPPING = {
    "state_region": "State or Region",
    "Response Type": "Response Type",
    "Start Date (UTC)": "Start Date",
    "Submit Date (UTC)": "Submit Date",
    "Stage Date (UTC)": "Stage Date",
    "Network ID": "Network ID",
}

# System fields to exclude from being dimensions (but include in survey_metadata)
SYSTEM_FIELDS = {
    '#', 'Network ID', 'zip_code', 'state_region', 'Response Type',
    'Start Date (UTC)', 'Submit Date (UTC)', 'Stage Date (UTC)', 'Tags', 'Ending'
}

# PII fields - should be in metadata but NOT as dimensions
PII_FIELDS = {
    'first_name', 'last_name', 'email', 'phone', 'Phone number',
    'first_name_95e98350', 'last_name_72be0a38', 'email_14bf7ffc'
}

# Core Values answer option columns (columns starting with *)
# These are the answer options for "Which three values does your flag most represent for you?"
CORE_VALUES_OPTIONS = set()

# Trust Drivers answer option columns
# These are the answer options for "How can we serve you better? What would make you trust us more or come back again?"
TRUST_DRIVERS_OPTIONS = set()

# Question texts and dimension names (with numbers)
CORE_VALUES_QUESTION_TEXT = "Which three values does your flag most represent for you?"
CORE_VALUES_DIMENSION_NAME = "08. Core Values"
CORE_VALUES_DIMENSION_REF = "core_values"

TRUST_DRIVERS_QUESTION_TEXT = "How can we serve you better? What would make you trust us more or come back again? Check all that feel true."
TRUST_DRIVERS_DIMENSION_NAME = "09. Trust Drivers"
TRUST_DRIVERS_DIMENSION_REF = "trust_drivers"


def format_value_for_viz(value, col_type):
    """Format value appropriately for visualization (bar charts, geo charts, etc.).
    
    Args:
        value: The raw value
        col_type: Column type (text, numerical, date, any, etc.)
    
    Returns:
        Formatted value (string, number, or ISO date string)
    """
    if value is None:
        return None
    
    # For dates, convert to ISO format string
    if col_type == 'date' and isinstance(value, datetime):
        return value.isoformat()
    elif col_type == 'date' and isinstance(value, str):
        return value
    
    # For numerical, return as number or string depending on context
    if col_type == 'numerical':
        try:
            return float(value) if '.' in str(value) else int(value)
        except (ValueError, TypeError):
            return str(value) if value else None
    
    # For text/any types, return as string
    if isinstance(value, list):
        return ', '.join(str(v) for v in value if v)
    
    return str(value) if value else None


def identify_answer_option_columns(project, rows):
    """Identify Core Values and Trust Drivers answer option columns.
    
    Args:
        project: The Caplena project object
        rows: Iterator of project rows
    
    Returns:
        tuple: (core_values_options, trust_drivers_options) sets of column names
    """
    # Build column map
    column_map = {}
    column_ref_to_type = {}
    for col in project.columns:
        col_ref = col.ref
        col_name = getattr(col, 'name', None)
        col_type = getattr(col, 'type', None)
        column_map[col_ref] = col_name
        column_ref_to_type[col_ref] = col_type
    
    core_values_options = set()
    trust_drivers_options = set()
    
    # Scan all rows to identify answer option columns
    print("Scanning rows to identify answer option columns...", end=" ", flush=True)
    for row in rows:
        for col in row.columns:
            col_ref = col.ref
            col_name = column_map.get(col_ref)
            col_value = getattr(col, 'value', None)
            col_type = column_ref_to_type.get(col_ref, 'unknown')
            
            # Core Values: columns that start with * (these are value answer options)
            if col_name and col_name.startswith('*') and col_value:
                core_values_options.add(col_name)
            
            # Trust Drivers: columns with specific keywords that aren't text_to_analyze
            # and aren't system fields or PII
            if (col_name and col_value and not col_name.startswith('*') and 
                col_type != 'text_to_analyze' and
                col_name not in SYSTEM_FIELDS and
                col_name not in PII_FIELDS):
                # Check if it matches trust drivers keywords
                col_lower = col_name.lower()
                if any(keyword in col_lower for keyword in [
                    'knowing', 'loyalty', 'retire', 'affordable', 'history', 
                    'care', 'variety', 'order', 'other', 'something else',
                    'made in', 'quality', 'respectful', 'program', 'help',
                    'easier', 'more', 'included', 'bulk', 'hardware',
                    'clear', 'availability', 'size', 'material', 'portability'
                ]):
                    # Exclude mapped question columns (these are already dimensions)
                    mapped_questions = [
                        "Where does your U.S. flag live?",
                        "What do you remember about flags from when you were younger?",
                        "How has what the flag means to you changed over time?",
                        "When you see your flag flying, what goes through your mind?",
                        "Why do you fly your flag? What are you saying by displaying it?",
                        "If your flag could tell others about you, what would it say?",
                        "How confident do you feel about proper flag etiquette?",
                        "How would you like your story to be shared?",
                        "What makes your story worth telling?",
                        "First, what should we call you?"
                    ]
                    if col_name not in mapped_questions:
                        trust_drivers_options.add(col_name)
    
    print(f"✓ Found {len(core_values_options)} Core Values options, {len(trust_drivers_options)} Trust Drivers options")
    return core_values_options, trust_drivers_options


def augment_brand_survey_dimensions(project_id: str, output_file: str = None, output_dir: str = "outputs"):
    """Extract Core Values and Trust Drivers selections and create dimension entries.
    
    Args:
        project_id: The ID of the project to extract from
        output_file: Output file name (defaults to usf_brand_survey_dimensions_augment.json)
        output_dir: Directory to save output files (defaults to "outputs")
    
    Returns:
        Path to the output file
    """
    def json_serializer(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Set default output file if not provided
    if output_file is None:
        output_file = os.path.join(output_dir, "usf_brand_survey_dimensions_augment.json")
    else:
        output_file = os.path.join(output_dir, output_file)
    
    # Create client with API key
    client = Client(api_key=Config.API_KEY)
    
    # Retrieve the project
    print(f"📡 Retrieving project by ID: {project_id}...")
    project = client.projects.retrieve(id=project_id)
    project_name = project.name
    print(f"📊 Processing project: {project_name}")
    
    # Get client information
    client_id = getattr(project, 'client_id', None)
    client_name = getattr(project, 'client_name', None)
    if not client_id and hasattr(project, 'client'):
        client_obj = getattr(project, 'client', None)
        if client_obj:
            client_id = getattr(client_obj, 'id', None)
            client_name = getattr(client_obj, 'name', None)
    
    # Create column mappings
    column_map = {}  # ref -> name
    column_ref_to_type = {}  # ref -> type
    if hasattr(project, 'columns') and project.columns:
        for col in project.columns:
            if hasattr(col, 'ref'):
                col_ref = col.ref
                col_name = getattr(col, 'name', None)
                col_type = getattr(col, 'type', None)
                
                column_map[col_ref] = col_name
                column_ref_to_type[col_ref] = col_type
    
    # Identify answer option columns
    rows = project.list_rows()
    core_values_options, trust_drivers_options = identify_answer_option_columns(project, rows)
    
    # List all rows again for processing
    print("Loading rows...", end=" ", flush=True)
    rows = project.list_rows()
    row_count = 0
    flattened_results = []
    
    # Process each row
    rows_processed = 0
    for row in rows:
        row_count += 1
        rows_processed += 1
        
        # Show progress every 100 rows
        if rows_processed % 100 == 0:
            print(f"row {rows_processed}...", end=" ", flush=True)
        
        # Extract row-level timestamps
        row_created = getattr(row, 'created', None)
        row_last_modified = getattr(row, 'last_modified', None)
        
        # Convert datetime objects to ISO format strings
        if row_created and isinstance(row_created, datetime):
            row_created = row_created.isoformat()
        if row_last_modified and isinstance(row_last_modified, datetime):
            row_last_modified = row_last_modified.isoformat()
        
        # Build survey_metadata for this respondent (all non-text columns, including PII)
        survey_metadata = {}
        for col in row.columns:
            col_ref = col.ref
            col_name = column_map.get(col_ref)
            col_type = column_ref_to_type.get(col_ref, 'unknown')
            col_value = getattr(col, 'value', None)
            
            # Add to survey_metadata if it's a non-text_to_analyze column
            # Exclude only system fields (PII is included this time)
            if (col_type != 'text_to_analyze' and 
                col_name not in SYSTEM_FIELDS):
                # Use human-readable label
                metadata_key = METADATA_LABEL_MAPPING.get(col_name) or col_name or col_ref
                if metadata_key:  # Only add if we have a key
                    formatted_value = format_value_for_viz(col_value, col_type)
                    if formatted_value is not None:  # Only add non-null values
                        survey_metadata[metadata_key] = formatted_value
        
        # Process Core Values selections
        selected_core_values = []
        for col in row.columns:
            col_name = column_map.get(col.ref)
            col_value = getattr(col, 'value', None)
            
            # Check if it's a Core Values answer option and has a value (was selected)
            if col_name in core_values_options and col_value:
                # Use the column name as the value name (standardized)
                selected_core_values.append(col_name)
        
        # Create dimension entries for Core Values (one entry per selected value)
        dimension_ref = CORE_VALUES_DIMENSION_REF
        for value_name in selected_core_values:
            entry = {
                "respondent_id": row.id,
                "created": row_created,
                "last_modified": row_last_modified,
                "client_id": client_id,
                "client_name": "Online Stores",
                "project_id": project.id,
                "project_name": "United States Flag",
                "total_rows": row_count,  # Will be updated after processing
                "data_source": "Brand Survey",
                "dimension_ref": dimension_ref,
                "dimension_name": CORE_VALUES_DIMENSION_NAME,
                "question_text": CORE_VALUES_QUESTION_TEXT,
                "question_type": "multi_choice",
                "value": value_name,  # The selected value (individual answer)
                "overall_sentiment": None,
                "topics": [],
                "survey_metadata": survey_metadata.copy()
            }
            flattened_results.append(entry)
        
        # Process Trust Drivers selections
        selected_trust_drivers = []
        for col in row.columns:
            col_name = column_map.get(col.ref)
            col_value = getattr(col, 'value', None)
            
            # Check if it's a Trust Drivers answer option and has a value (was selected)
            if col_name in trust_drivers_options and col_value:
                # Use the column name as the value name (standardized)
                selected_trust_drivers.append(col_name)
        
        # Create dimension entries for Trust Drivers (one entry per selected value)
        dimension_ref = TRUST_DRIVERS_DIMENSION_REF
        for value_name in selected_trust_drivers:
            entry = {
                "respondent_id": row.id,
                "created": row_created,
                "last_modified": row_last_modified,
                "client_id": client_id,
                "client_name": "Online Stores",
                "project_id": project.id,
                "project_name": "United States Flag",
                "total_rows": row_count,  # Will be updated after processing
                "data_source": "Brand Survey",
                "dimension_ref": dimension_ref,
                "dimension_name": TRUST_DRIVERS_DIMENSION_NAME,
                "question_text": TRUST_DRIVERS_QUESTION_TEXT,
                "question_type": "multi_choice",
                "value": value_name,  # The selected value (individual answer)
                "overall_sentiment": None,
                "topics": [],
                "survey_metadata": survey_metadata.copy()
            }
            flattened_results.append(entry)
    
    # Update total_rows for all entries
    for i in range(len(flattened_results)):
        flattened_results[i]["total_rows"] = row_count
    
    entries_added = len(flattened_results)
    print(f"✓ Complete! ({row_count} rows, {entries_added} dimension entries)")
    
    # Write flattened results to JSON file
    print(f"\n💾 Writing {len(flattened_results)} entries to {output_file}...", end=" ", flush=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "flattened_results": flattened_results
        }, f, indent=2, ensure_ascii=False, default=json_serializer)
    
    print("✓ Complete!")
    
    file_size = os.path.getsize(output_file) / (1024 * 1024)  # Size in MB
    print(f"\n✅ Successfully extracted {len(flattened_results):,} dimension entries")
    print(f"   📁 Output file: {output_file}")
    print(f"   📊 File size: {file_size:.2f} MB")
    
    return output_file


def main():
    """Main function to extract dimensions and upload to database."""
    
    project_id = "pj_wggvm"  # USF - Brand Survey
    
    print("🔍 Extracting Core Values and Trust Drivers dimensions...")
    
    # Extract the dimensions
    print(f"\n📥 Extracting dimensions from project: {project_id}...")
    output_file = augment_brand_survey_dimensions(
        project_id=project_id,
        output_file="usf_brand_survey_dimensions_augment.json",
        output_dir="outputs"
    )
    
    # Upload to database
    print(f"\n📤 Uploading to database...")
    upload_flattened_data(output_file, batch_size=1000)
    
    print(f"\n✅ Complete! Dimension data extracted and uploaded successfully.")
    print(f"   📁 JSON file: {output_file}")


if __name__ == "__main__":
    main()
