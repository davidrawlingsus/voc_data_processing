#!/usr/bin/env python3
"""
Script to extract "USF - Brand Survey" from Caplena, process it, and upload to DB.
Enhanced extraction that includes:
- All text_to_analyze columns (as dimensions) mapped to standardized names
- All non-text columns (as dimensions where appropriate)
- Question mapping to standardized dimensions
- Survey metadata with human-readable keys (including PII)
- Proper question_type classification (open_text, multi_choice, numeric, geo)
"""

import json
import os
import sys
from datetime import datetime
from caplena import Client
from upload_to_db import upload_flattened_data

# Try to load dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from config import Config


# Question mapping: Original question text -> Standardized dimension name (with numbers)
QUESTION_MAPPING = {
    "Where does your U.S. flag live?": "01. Flag Placement",
    "What do you remember about flags from when you were younger?": "02. Early Memory",
    "How has what the flag means to you changed over time?": "03. Meaning Evolution",
    "When you see your flag flying, what goes through your mind?": "04. Emotional Response",
    "Why do you fly your flag? What are you saying by displaying it?": "05. Intentional Expression",
    "If your flag could tell others about you, what would it say?": "06. Projected Identity",
    "How confident do you feel about proper flag etiquette?": "07. Etiquette Confidence",
    "Which three values does your flag most represent for you?": "08. Core Values",
    "How can we serve you better? What would make you trust us more or come back again? Check all that feel true.": "09. Trust Drivers",
    "How would you like your story to be shared?": "10. Sharing Preference",
    "What makes your story worth telling?": "11. Story Significance"
}

# Metadata label mapping: Column name/ref -> Human-readable label for survey_metadata
METADATA_LABEL_MAPPING = {
    "state_region": "State or Region",
    "Response Type": "Response Type",
    "Start Date (UTC)": "Start Date",
    "Submit Date (UTC)": "Submit Date",
    "Stage Date (UTC)": "Stage Date",
    "Network ID": "Network ID",
}

# Note: PII fields are NOT excluded from survey_metadata (user requested to include PII)
# We'll include all fields except system fields in metadata

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


def determine_question_type(col_type, dimension_name, col_name=None):
    """Determine question_type based on column type and dimension name.
    
    Args:
        col_type: Caplena column type (text_to_analyze, numerical, text, etc.)
        dimension_name: The standardized dimension name
        col_name: The original column name (for special cases)
    
    Returns:
        question_type string: 'open_text', 'geo', 'numeric', or 'multi_choice'
    """
    # Location dimension is always 'geo'
    if dimension_name == "Location" or "Location" in dimension_name:
        return "geo"
    
    # Flag Placement is multi_choice (structured choices, not open text)
    if dimension_name == "01. Flag Placement" or col_name == "Where does your U.S. flag live?":
        return "multi_choice"
    
    # Sharing Preference is multi_choice
    if dimension_name == "10. Sharing Preference" or (col_name and "sharing" in col_name.lower() and "preference" in col_name.lower()):
        return "multi_choice"
    
    # numerical columns are numeric
    if col_type == "numerical":
        return "numeric"
    
    # text_to_analyze columns are typically open-ended text
    # But check if the dimension name suggests it should be multi_choice
    if col_type == "text_to_analyze":
        # Some text_to_analyze columns have structured answers that should be multi_choice
        if dimension_name in ["01. Flag Placement", "10. Sharing Preference"]:
            return "multi_choice"
        return "open_text"
    
    # All other non-text columns are multi_choice
    return "multi_choice"


def extract_brand_survey_enhanced(project_id: str, output_file: str = None, output_dir: str = "outputs"):
    """Extract Brand Survey data with enhanced processing.
    
    Args:
        project_id: The ID of the project to extract from
        output_file: Output file name (defaults to usf_brand_survey_flattened.json)
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
        output_file = os.path.join(output_dir, "usf_brand_survey_flattened.json")
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
        # NOTE: Including PII this time (as requested)
        survey_metadata = {}
        row_data = {}  # Store all column values for this row
        
        # Identify answer option columns by examining the data
        # Answer options are typically checkbox values that appear as columns
        # We'll identify them as columns that are NOT in QUESTION_MAPPING
        # and are NOT system fields, and are not text_to_analyze
        
        # First pass: collect all column data
        for col in row.columns:
            col_ref = col.ref
            col_name = column_map.get(col_ref)
            col_type = column_ref_to_type.get(col_ref, 'unknown')
            col_value = getattr(col, 'value', None)
            
            row_data[col_ref] = col_value
        
        # Second pass: identify answer option columns
        # These are columns that have boolean-like values (indicating selection)
        # and are not in our question mapping
        answer_option_columns = set()
        question_columns = set()
        
        for col in row.columns:
            col_name = column_map.get(col.ref)
            if col_name in QUESTION_MAPPING:
                question_columns.add(col_name)
        
        # Build survey_metadata (including PII, excluding only system fields)
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
        
        # Process text_to_analyze columns (as dimensions)
        for col in row.columns:
            if col.type == "text_to_analyze":
                col_ref = col.ref
                col_name = column_map.get(col_ref)
                
                # Extract topics
                topics = []
                for topic in col.topics:
                    topic_data = {
                        "category": topic.category,
                        "label": topic.label,
                    }
                    topics.append(topic_data)
                
                # Get dimension name (mapped or original)
                dimension_name = QUESTION_MAPPING.get(col_name, col_name)
                
                # Determine question_type (pass col_name for special handling)
                question_type = determine_question_type("text_to_analyze", dimension_name, col_name)
                
                # Create flattened entry
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
                    "dimension_ref": col_ref,
                    "dimension_name": dimension_name,
                    "question_text": col_name,
                    "question_type": question_type,
                    "value": getattr(col, 'value', None),
                    "overall_sentiment": getattr(col, 'overall_sentiment', None),
                    "topics": topics,
                    "survey_metadata": survey_metadata.copy()
                }
                
                flattened_results.append(entry)
        
        # Process non-text columns (as dimensions ONLY if they're in QUESTION_MAPPING)
        # Everything else (PII, answer options, unmapped fields) goes in metadata only
        for col in row.columns:
            col_ref = col.ref
            col_name = column_map.get(col_ref)
            col_type = column_ref_to_type.get(col_ref, 'unknown')
            col_value = getattr(col, 'value', None)
            
            # Skip if it's text_to_analyze (already processed)
            if col_type == 'text_to_analyze':
                continue
            
            # Skip system fields
            if col_name in SYSTEM_FIELDS:
                continue
            
            # Skip PII fields (they're in metadata, but not dimensions)
            if col_name in PII_FIELDS or col_ref in PII_FIELDS:
                continue
            
            # ONLY create dimensions for columns that are explicitly in QUESTION_MAPPING
            # Everything else is just metadata (answer options, unmapped fields, etc.)
            if col_name not in QUESTION_MAPPING:
                continue  # Skip - this is metadata only, not a dimension
            
            # This column is in QUESTION_MAPPING, so create a dimension entry
            dimension_name = QUESTION_MAPPING[col_name]
            
            # Determine question_type (pass col_name for special handling)
            question_type = determine_question_type(col_type, dimension_name, col_name)
            
            # Format value for visualization
            formatted_value = format_value_for_viz(col_value, col_type)
            
            # Skip if value is empty/null (optional - could include them too)
            if formatted_value is None or formatted_value == "":
                continue
            
            # Create flattened entry
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
                "dimension_ref": col_ref,
                "dimension_name": dimension_name,
                "question_text": col_name,
                "question_type": question_type,
                "value": formatted_value,
                "overall_sentiment": None,
                "topics": [],
                "survey_metadata": survey_metadata.copy()
            }
            
            flattened_results.append(entry)
    
    # Update total_rows for all entries
    for i in range(len(flattened_results)):
        flattened_results[i]["total_rows"] = row_count
    
    print(f"✓ Complete! ({row_count} rows, {len(flattened_results)} entries)")
    
    # Write flattened results to JSON file
    print(f"\n💾 Writing {len(flattened_results)} entries to {output_file}...", end=" ", flush=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "flattened_results": flattened_results
        }, f, indent=2, ensure_ascii=False, default=json_serializer)
    
    print("✓ Complete!")
    
    file_size = os.path.getsize(output_file) / (1024 * 1024)  # Size in MB
    print(f"\n✅ Successfully extracted {len(flattened_results):,} entries")
    print(f"   📁 Output file: {output_file}")
    print(f"   📊 File size: {file_size:.2f} MB")
    
    return output_file


def main():
    """Main function to extract, process, and upload USF - Brand Survey."""
    
    project_id = "pj_wggvm"  # USF - Brand Survey
    
    # Extract the project with enhanced extraction
    print(f"\n📥 Extracting project: USF - Brand Survey...")
    output_file = extract_brand_survey_enhanced(
        project_id=project_id,
        output_file="usf_brand_survey_flattened.json",
        output_dir="outputs"
    )
    
    # Upload to database
    print(f"\n📤 Uploading to database...")
    upload_flattened_data(output_file, batch_size=1000)
    
    print(f"\n✅ Complete! Data extracted and uploaded successfully.")
    print(f"   📁 JSON file: {output_file}")


if __name__ == "__main__":
    main()
