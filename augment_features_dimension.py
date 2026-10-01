#!/usr/bin/env python3
"""
Script to augment existing Value Map data with the missing "Most Important Features" dimension.
This creates entries for the question "Which three features mattered most when choosing your [product]?"
by processing the answer option columns (checkbox values) that were excluded from dimension creation.
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

# PII fields to exclude from survey_metadata (column refs and names)
PII_FIELDS = {
    'first_name', 'last_name', 'email',
    'email_14bf7ffc', 'first_name_95e98350', 'last_name_72be0a38'
}

# System fields to exclude from being dimensions (but include in survey_metadata)
SYSTEM_FIELDS = {
    '#', 'Network ID', 'zip_code', 'state_region', 'Response Type',
    'Start Date (UTC)', 'Submit Date (UTC)', 'Stage Date (UTC)', 'Tags', 'Ending'
}

# Answer option columns that represent selected features
FEATURE_ANSWER_OPTIONS = {
    'Made in the USA', 'Made in the USA.1', 'Made in the USA.2', 'Made in the USA.3', 'Made in the USA.4',
    'Durability', 'Durability of stick and attachment', 'Durability and longevity', 'Durability.1', 'Durability.2',
    'Stitching quality',
    'Fade resistance',
    'Correct proportions',
    'Weather rating', 'Weather resistance',
    'Grommet or heading quality',
    'Star quality',
    'Size and portability',
    'Fabric quality',
    'Price',
    'Height options',
    'Material quality',
    'Wind rating',
    'Warranty',
    'Automatic on/off functionality',
    'Power source (solar, wired, etc.)',
    'Ease of installation', 'Ease of installation.1', 'Ease of installation.2',
    'Ease of handling',
    'Compatibility with existing flagpoles', 'Compatibility with existing setup',
    'Build quality',
    'Clear product descriptions',
    'Availability of the right size or type',
    'Included hardware',
    'Quantity or bulk options',
    'Brightness',
    'Other', 'Other.1', 'Other.2', 'Other.3', 'Other.4', 'Other.5'
}

# Question text for the features dimension
FEATURES_QUESTION_TEXT = "Which three features mattered most when choosing your [product]?"
FEATURES_DIMENSION_NAME = "09 - Important Features"


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
        # Already a string, return as-is
        return value
    
    # For numerical, return as number or string depending on context
    if col_type == 'numerical':
        try:
            # Try to convert to number
            return float(value) if '.' in str(value) else int(value)
        except (ValueError, TypeError):
            # If conversion fails, return as string
            return str(value) if value else None
    
    # For text/any types, return as string
    # For multi-select (comma-separated or arrays), return as string
    if isinstance(value, list):
        return ', '.join(str(v) for v in value if v)
    
    return str(value) if value else None


def augment_features_dimension(project_id: str, output_file: str = None, output_dir: str = "outputs"):
    """Extract feature selections and create dimension entries with product in metadata.
    
    Args:
        project_id: The ID of the project to extract from
        output_file: Output file name (defaults to usf_value_map_features_augment.json)
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
        output_file = os.path.join(output_dir, "usf_value_map_features_augment.json")
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
    column_name_to_ref = {}  # name -> ref
    if hasattr(project, 'columns') and project.columns:
        for col in project.columns:
            if hasattr(col, 'ref'):
                col_ref = col.ref
                col_name = getattr(col, 'name', None)
                col_type = getattr(col, 'type', None)
                
                column_map[col_ref] = col_name
                column_ref_to_type[col_ref] = col_type
                if col_name:
                    column_name_to_ref[col_name] = col_ref
    
    # Find product selection question ref
    product_question_name = "Thinking back to your purchases from us, which product comes to mind first?"
    product_question_ref = column_name_to_ref.get(product_question_name)
    
    # List all rows
    print("Loading rows...", end=" ", flush=True)
    rows = project.list_rows()
    row_count = 0
    flattened_results = []
    
    # Process each row
    rows_processed = 0
    for row in rows:
        row_count += 1
        rows_processed += 1
        
        # Show progress every 500 rows
        if rows_processed % 500 == 0:
            print(f"row {rows_processed}...", end=" ", flush=True)
        
        # Extract row-level timestamps
        row_created = getattr(row, 'created', None)
        row_last_modified = getattr(row, 'last_modified', None)
        
        # Convert datetime objects to ISO format strings
        if row_created and isinstance(row_created, datetime):
            row_created = row_created.isoformat()
        if row_last_modified and isinstance(row_last_modified, datetime):
            row_last_modified = row_last_modified.isoformat()
        
        # Build survey_metadata for this respondent (all non-text columns)
        # This should match what extract_and_upload_usf_value_map.py does
        survey_metadata = {}
        
        # Process all columns to build survey_metadata
        for col in row.columns:
            col_ref = col.ref
            col_name = column_map.get(col_ref)
            col_type = column_ref_to_type.get(col_ref, 'unknown')
            col_value = getattr(col, 'value', None)
            
            # Add to survey_metadata if it's a non-text_to_analyze column
            # Exclude PII fields, system fields, and answer option columns (check both ref and name)
            if (col_type != 'text_to_analyze' and 
                col_ref not in PII_FIELDS and 
                col_name not in PII_FIELDS and
                col_name not in SYSTEM_FIELDS and
                col_name not in FEATURE_ANSWER_OPTIONS):
                # Use human-readable label
                metadata_key = METADATA_LABEL_MAPPING.get(col_name) or col_name or col_ref
                if metadata_key:  # Only add if we have a key
                    formatted_value = format_value_for_viz(col_value, col_type)
                    if formatted_value is not None:  # Only add non-null values
                        survey_metadata[metadata_key] = formatted_value
        
        # Find all selected features (answer option columns with values)
        selected_features = []
        for col in row.columns:
            col_name = column_map.get(col.ref)
            col_value = getattr(col, 'value', None)
            
            # Check if it's a feature answer option column and has a value (was selected)
            if col_name in FEATURE_ANSWER_OPTIONS:
                # If the column has a value, it means this feature was selected
                # The value might be the feature name itself, or "Yes", or similar
                if col_value and str(col_value).strip():
                    # Use the column name as the feature name (standardized)
                    feature_name = col_name
                    # Use the value if it's different from the column name, otherwise use column name
                    if str(col_value).strip() != col_name:
                        # Value might be the feature name or a selection indicator
                        feature_value = str(col_value).strip()
                    else:
                        feature_value = col_name
                    
                    selected_features.append(feature_name)
        
        # Create a dimension entry for each selected feature
        # Use the SAME dimension_ref for all entries (represents the question, not the answer)
        # The dimension_ref should be the same for all answer values to this question
        
        # Use a single consistent dimension_ref for all feature entries
        dimension_ref = "important_features_09"
        
        for feature_name in selected_features:
            feature_entry = {
                "respondent_id": row.id,
                "created": row_created,
                "last_modified": row_last_modified,
                "client_id": client_id,
                "client_name": "Online Stores",
                "project_id": project.id,
                "project_name": "United States Flag",
                "total_rows": row_count,  # Will be updated after processing
                "data_source": "Value map",
                # Use the same dimension_ref for ALL entries - represents the question, not the answer
                "dimension_ref": dimension_ref,
                "dimension_name": FEATURES_DIMENSION_NAME,
                "question_text": FEATURES_QUESTION_TEXT,
                "question_type": "multi_choice",
                "value": feature_name,  # The selected feature (individual answer value)
                "overall_sentiment": None,
                "topics": [],
                "survey_metadata": survey_metadata.copy()  # Includes product purchased
            }
            
            flattened_results.append(feature_entry)
    
    # Update total_rows for all entries
    for i in range(len(flattened_results)):
        flattened_results[i]["total_rows"] = row_count
    
    entries_added = len(flattened_results)
    print(f"✓ Complete! ({row_count} rows, {entries_added} feature entries)")
    
    # Write flattened results to JSON file
    print(f"\n💾 Writing {len(flattened_results)} entries to {output_file}...", end=" ", flush=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "flattened_results": flattened_results
        }, f, indent=2, ensure_ascii=False, default=json_serializer)
    
    print("✓ Complete!")
    
    file_size = os.path.getsize(output_file) / (1024 * 1024)  # Size in MB
    print(f"\n✅ Successfully extracted {len(flattened_results):,} feature entries")
    print(f"   📁 Output file: {output_file}")
    print(f"   📊 File size: {file_size:.2f} MB")
    
    return output_file


def main():
    """Main function to extract features and upload to database."""
    
    project_id = "pj_0vv4k"  # USF - Value Map
    
    print("🔍 Extracting feature selections...")
    
    # Extract the features
    print(f"\n📥 Extracting feature selections from project: {project_id}...")
    output_file = augment_features_dimension(
        project_id=project_id,
        output_file="usf_value_map_features_augment.json",
        output_dir="outputs"
    )
    
    # Upload to database
    print(f"\n📤 Uploading to database...")
    upload_flattened_data(output_file, batch_size=1000)
    
    print(f"\n✅ Complete! Feature dimension data extracted and uploaded successfully.")
    print(f"   📁 JSON file: {output_file}")


if __name__ == "__main__":
    main()
