#!/usr/bin/env python3
"""
Script to extract "USF - Value Map" from Caplena, process it, and upload to DB.
Enhanced extraction that includes:
- All text_to_analyze columns (as dimensions)
- All non-text columns (as dimensions)
- Location dimension from state_region
- Question mapping to standardized dimensions
- Survey metadata with human-readable keys
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


# Question mapping: Original question text -> Standardized dimension name
QUESTION_MAPPING = {
    "Thinking back to your purchases from us, which product comes to mind first?": "Most Important Product",
    "What was the primary reason or setting for this purchase?": "Purchase Type",
    "Before this purchase, did you already own a similar product?": "Incumbant Ownership",
    "Which company / brand?": "Incumbant Brand",
    "What was wrong with the previous product you replaced?": "Incumbant Failure Mode",
    "When you imagined this product in place, what needed to be true for you to feel good about the purchase?": "Success Criteria",
    "Why did you choose United-States-Flag.com for your {{field:8de2afcb-efef-468f-9cc6-dd44130ea3cc}} and not somewhere else?": "Perceived Exclusivity",
    "Why were these features important to you, in your situation?": "Feature Value",
    "What, if anything, made this purchase harder than it needed to be?": "Purchase Friction",
    "If you could wave a magic wand and create a perfectly made US flag, how would it be better than the rest?": "New Product Development",
    "What media do you trust the most?": "Trusted Media",
    "Which media personalities do you trust most when it comes to authentic patriotism?": "Trusted Personalities",
    "Will you be purchasing from us again in the future?": "Future Purchase / Repurchase Rate",
    "Please tell us why...": "Reason for leaving"
}

# Metadata label mapping: Column name/ref -> Human-readable label for survey_metadata
METADATA_LABEL_MAPPING = {
    "state_region": "State or Region",
    "Response Type": "Response Type",
    "Start Date (UTC)": "Start Date",
    "Submit Date (UTC)": "Submit Date",
    "Stage Date (UTC)": "Stage Date",
    "Network ID": "Network ID",
    # Add mappings for other common fields as needed
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

# Answer option columns (checkbox/multi-select values) - these are NOT questions, just answer values
# These should NOT be created as dimensions, only included in survey_metadata
ANSWER_OPTION_COLUMNS = {
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


def determine_question_type(col_type, dimension_name):
    """Determine question_type based on column type and dimension name.
    
    Args:
        col_type: Caplena column type (text_to_analyze, numerical, text, etc.)
        dimension_name: The standardized dimension name
    
    Returns:
        question_type string: 'open_text', 'geo', 'numeric', or 'multi_choice'
    """
    # Location dimension is always 'geo'
    if dimension_name == "Location":
        return "geo"
    
    # text_to_analyze columns are open-ended text
    if col_type == "text_to_analyze":
        return "open_text"
    
    # numerical columns are numeric
    if col_type == "numerical":
        return "numeric"
    
    # All other non-text columns are multi_choice
    return "multi_choice"


def extract_value_map_enhanced(project_id: str, output_file: str = None, output_dir: str = "outputs"):
    """Extract Value Map project with all columns (text_to_analyze and non-text).
    
    Args:
        project_id: The ID of the project to extract
        output_file: Output file name (defaults to usf_value_map_flattened.json)
        output_dir: Directory to save output files (defaults to "outputs")
    
    Returns:
        Path to the output file
    """
    # Helper function to convert non-serializable objects to strings
    def json_serializer(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Set default output file if not provided
    if output_file is None:
        output_file = os.path.join(output_dir, "usf_value_map_flattened.json")
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
    
    # Get state_region column ref for Location dimension
    state_region_ref = column_name_to_ref.get("state_region")
    
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
        survey_metadata = {}
        row_data = {}  # Store all column values for this row
        
        # Process all columns to build row_data and survey_metadata
        for col in row.columns:
            col_ref = col.ref
            col_name = column_map.get(col_ref)
            col_type = column_ref_to_type.get(col_ref, 'unknown')
            col_value = getattr(col, 'value', None)
            
            row_data[col_ref] = col_value
            
            # Add to survey_metadata if it's a non-text_to_analyze column
            # Exclude PII fields (check both ref and name)
            if col_type != 'text_to_analyze' and col_ref not in PII_FIELDS and col_name not in PII_FIELDS:
                # Use human-readable label
                metadata_key = METADATA_LABEL_MAPPING.get(col_name) or col_name or col_ref
                if metadata_key:  # Only add if we have a key
                    formatted_value = format_value_for_viz(col_value, col_type)
                    if formatted_value is not None:  # Only add non-null values
                        survey_metadata[metadata_key] = formatted_value
        
        # Process text_to_analyze columns (as before)
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
                
                # Determine question_type
                question_type = determine_question_type("text_to_analyze", dimension_name)
                
                # Create flattened entry
                flattened_entry = {
                    "respondent_id": row.id,
                    "created": row_created,
                    "last_modified": row_last_modified,
                    "client_id": client_id,
                    "client_name": "Online Stores",
                    "project_id": project.id,
                    "project_name": "United States Flag",
                    "total_rows": row_count,  # Will be updated after processing
                    "data_source": "Value map",
                    "dimension_ref": col_ref,
                    "dimension_name": dimension_name,
                    "question_text": col_name,  # Original question text
                    "question_type": question_type,
                    "value": col.value if col.value else "",
                    "overall_sentiment": getattr(col, 'sentiment_overall', None),
                    "topics": topics,
                    "survey_metadata": survey_metadata.copy()  # Copy metadata for each dimension
                }
                
                flattened_results.append(flattened_entry)
        
        # Create Location dimension from state_region if it exists
        if state_region_ref and state_region_ref in row_data:
            state_region_value = row_data[state_region_ref]
            if state_region_value:
                location_entry = {
                    "respondent_id": row.id,
                    "created": row_created,
                    "last_modified": row_last_modified,
                    "client_id": client_id,
                    "client_name": "Online Stores",
                    "project_id": project.id,
                    "project_name": "United States Flag",
                    "total_rows": row_count,
                    "data_source": "Value map",
                    "dimension_ref": f"location_{state_region_ref}",
                    "dimension_name": "Location",
                    "question_text": "Where are you in the US?",
                    "question_type": "geo",
                    "value": str(state_region_value),  # State name for geo charts
                    "overall_sentiment": None,
                    "topics": [],
                    "survey_metadata": survey_metadata.copy()
                }
                flattened_results.append(location_entry)
        
        # Process non-text columns as dimensions (skip system fields - they're only in metadata)
        for col in row.columns:
            col_ref = col.ref
            col_name = column_map.get(col_ref)
            col_type = column_ref_to_type.get(col_ref, 'unknown')
            
            # Skip text_to_analyze columns (already processed)
            # Skip PII fields (check both ref and name)
            # Skip system fields (these are metadata only, not dimensions)
            # Skip answer option columns (checkbox values - these are NOT questions, just answer values)
            # Skip if no name (internal/system fields)
            if col_type == 'text_to_analyze':
                continue
            if col_ref in PII_FIELDS or col_name in PII_FIELDS:
                continue
            if col_name in SYSTEM_FIELDS:
                continue  # System fields are in metadata only, not dimensions
            if col_name in ANSWER_OPTION_COLUMNS:
                continue  # Answer option columns are values, not questions - exclude from dimensions
            if not col_name:
                continue
            
            col_value = getattr(col, 'value', None)
            
            # Skip empty/null values for non-text columns (optional - could include them too)
            # Actually, we should include them so we can see all questions
            # But skip if it's truly empty (None, empty string, empty list)
            if col_value is None or col_value == "" or (isinstance(col_value, list) and len(col_value) == 0):
                continue  # Skip empty values for now
            
            # Get dimension name (mapped or original)
            dimension_name = QUESTION_MAPPING.get(col_name, col_name)
            
            # Determine question_type
            question_type = determine_question_type(col_type, dimension_name)
            
            # Format value for visualization
            formatted_value = format_value_for_viz(col_value, col_type)
            
            # Create flattened entry for non-text column
            non_text_entry = {
                "respondent_id": row.id,
                "created": row_created,
                "last_modified": row_last_modified,
                "client_id": client_id,
                "client_name": "Online Stores",
                "project_id": project.id,
                "project_name": "United States Flag",
                "total_rows": row_count,
                "data_source": "Value map",
                "dimension_ref": col_ref,
                "dimension_name": dimension_name,
                "question_text": col_name,  # Original question text
                "question_type": question_type,
                "value": formatted_value if formatted_value is not None else "",
                "overall_sentiment": None,  # Not applicable for non-text
                "topics": [],  # Not applicable for non-text
                "survey_metadata": survey_metadata.copy()
            }
            
            flattened_results.append(non_text_entry)
    
    # Update total_rows for all entries from this project
    for i in range(len(flattened_results)):
        flattened_results[i]["total_rows"] = row_count
    
    entries_added = len(flattened_results)
    print(f"✓ Complete! ({row_count} rows, {entries_added} flattened entries)")
    
    # Write flattened results to JSON file
    print(f"\n💾 Writing {len(flattened_results)} entries to {output_file}...", end=" ", flush=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "flattened_results": flattened_results
        }, f, indent=2, ensure_ascii=False, default=json_serializer)
    
    print("✓ Complete!")
    
    file_size = os.path.getsize(output_file) / (1024 * 1024)  # Size in MB
    print(f"\n✅ Successfully extracted {len(flattened_results):,} flattened entries")
    print(f"   📁 Output file: {output_file}")
    print(f"   📊 File size: {file_size:.2f} MB")
    
    return output_file


def main():
    """Main function to extract, process, and upload USF - Value Map."""
    
    # Search terms - try different variations
    search_terms = [
        "USF - Value Map",
        "USF Value Map",
        "US Flag Value Map",
        "Value Map"
    ]
    
    project_id = None
    project_name = None
    
    # Try to find the project
    print("🔍 Searching for project...")
    client = Client(api_key=Config.API_KEY)
    projects = client.projects.list()
    
    for term in search_terms:
        for proj in projects:
            if term.lower() in proj.name.lower():
                project_id = proj.id
                project_name = proj.name
                print(f"✅ Found project: {project_name} (ID: {project_id})")
                break
        if project_id:
            break
    
    if not project_id:
        print("❌ Could not find project. Available projects:")
        for i, proj in enumerate(list(projects)[:20], 1):
            print(f"   {i}. {proj.name} (ID: {proj.id})")
        sys.exit(1)
    
    # Extract the project with enhanced extraction
    print(f"\n📥 Extracting project: {project_name}...")
    output_file = extract_value_map_enhanced(
        project_id=project_id,
        output_file="usf_value_map_flattened.json",
        output_dir="outputs"
    )
    
    # Upload to database
    print(f"\n📤 Uploading to database...")
    upload_flattened_data(output_file, batch_size=1000)
    
    print(f"\n✅ Complete! Data extracted and uploaded successfully.")
    print(f"   📁 JSON file: {output_file}")


if __name__ == "__main__":
    main()
