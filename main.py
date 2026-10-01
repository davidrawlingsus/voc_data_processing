"""Main script to connect to Caplena API and extract project list."""
import json
import os
from datetime import datetime
from caplena import Client

from config import Config


def extract_all_projects():
    """Extract all projects from Caplena and save to text file."""
    # Create client with API key
    client = Client(api_key=Config.API_KEY)
    
    # Retrieve all projects (no filter)
    projects = client.projects.list()
    
    # Write projects to text file
    output_file = "projects_list.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"Caplena Projects List\n")
        f.write(f"{'=' * 50}\n\n")
        f.write(f"Total Projects: {projects.count}\n\n")
        
        for i, project in enumerate(projects, 1):
            # Write project information
            f.write(f"{i}. {project.name}\n")
            if hasattr(project, 'id'):
                f.write(f"   ID: {project.id}\n")
            if hasattr(project, 'language') and project.language:
                f.write(f"   Language: {project.language}\n")
            if hasattr(project, 'created_at') and project.created_at:
                f.write(f"   Created: {project.created_at}\n")
            f.write("\n")
    
    print(f"✅ Successfully extracted {projects.count} projects to '{output_file}'")
    return output_file


def extract_all_projects_flattened(output_file: str = None, output_dir: str = "outputs"):
    """Extract all projects from Caplena and flatten them to match the target format.
    
    Args:
        output_file: Output file name (defaults to all_projects_flattened.json)
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
        output_file = os.path.join(output_dir, "all_projects_flattened.json")
    else:
        output_file = os.path.join(output_dir, output_file)
    
    # Create client with API key
    client = Client(api_key=Config.API_KEY)
    
    # Retrieve all projects
    print("📡 Connecting to Caplena API...")
    projects = client.projects.list()
    total_project_count = projects.count
    
    print(f"📊 Found {total_project_count} projects to process\n")
    
    flattened_results = []
    total_projects = 0
    
    for project_summary in projects:
        total_projects += 1
        project_id = project_summary.id
        
        try:
            # Retrieve full project details
            print(f"[{total_projects}/{total_project_count}] Retrieving project: {project_summary.name or project_id}...", end=" ", flush=True)
            project = client.projects.retrieve(id=project_id)
            
            # Get client information
            client_id = getattr(project, 'client_id', None)
            client_name = getattr(project, 'client_name', None)
            if not client_id and hasattr(project, 'client'):
                # Try to get from client object if it exists
                client_obj = getattr(project, 'client', None)
                if client_obj:
                    client_id = getattr(client_obj, 'id', None)
                    client_name = getattr(client_obj, 'name', None)
            
            # Get data source
            data_source = getattr(project, 'data_source', None)
            if not data_source and hasattr(project, 'source'):
                data_source = getattr(project, 'source', None)
            
            # Create a mapping from column ref to column name (question text)
            # Also create a reverse mapping from column name to ref for metadata lookup
            column_map = {}
            column_name_to_ref = {}
            if hasattr(project, 'columns') and project.columns:
                for col in project.columns:
                    if hasattr(col, 'ref') and hasattr(col, 'name'):
                        column_map[col.ref] = col.name
                        column_name_to_ref[col.name] = col.ref
            
            # Count text_to_analyze dimensions first
            dimensions_count = 0
            if hasattr(project, 'columns') and project.columns:
                dimensions = [c for c in project.columns if getattr(c, 'type', None) == 'text_to_analyze']
                dimensions_count = len(dimensions)
            
            # List all rows
            print("Loading rows...", end=" ", flush=True)
            rows = project.list_rows()
            row_count = 0
            project_start_index = len(flattened_results)
            
            # Identify text_to_analyze column refs (these are dimensions, not metadata)
            text_column_refs = set()
            if hasattr(project, 'columns') and project.columns:
                for col in project.columns:
                    if getattr(col, 'type', None) == 'text_to_analyze':
                        text_column_refs.add(col.ref)

            # Process each row
            rows_processed = 0
            for row in rows:
                row_count += 1
                rows_processed += 1

                # Show progress every 500 rows
                if rows_processed % 500 == 0:
                    print(f"row {rows_processed}...", end=" ", flush=True)

                # Get all column values and build survey_metadata from non-text columns
                row_data = {}
                survey_metadata = {}
                for col in row.columns:
                    row_data[col.ref] = col.value
                    # Collect all non-text_to_analyze columns as metadata
                    if col.ref not in text_column_refs and col.value is not None and col.value != "":
                        col_name = column_map.get(col.ref, col.ref)
                        survey_metadata[col_name] = col.value

                # Extract row-level timestamps
                row_created = getattr(row, 'created', None)
                row_last_modified = getattr(row, 'last_modified', None)

                # Convert datetime objects to ISO format strings
                if row_created and isinstance(row_created, datetime):
                    row_created = row_created.isoformat()
                if row_last_modified and isinstance(row_last_modified, datetime):
                    row_last_modified = row_last_modified.isoformat()

                # Process each text_to_analyze column (dimension) and create a flattened entry
                for col in row.columns:
                    if col.type == "text_to_analyze":
                        # Extract topics
                        topics = []
                        for topic in col.topics:
                            topic_data = {
                                "category": topic.category,
                                "label": topic.label,
                            }
                            topics.append(topic_data)

                        # Create flattened entry
                        flattened_entry = {
                            "respondent_id": row.id,
                            "created": row_created,
                            "last_modified": row_last_modified,
                            "client_id": client_id,
                            "client_name": client_name,
                            "project_id": project.id,
                            "project_name": project.name,
                            "total_rows": row_count,  # Will be updated to final count after processing
                            "data_source": data_source,
                            "survey_metadata": survey_metadata if survey_metadata else None,
                            "dimension_ref": col.ref,
                            "dimension_name": column_map.get(col.ref, None),
                            "value": col.value if col.value else "",
                            "overall_sentiment": getattr(col, 'sentiment_overall', None),
                            "topics": topics
                        }

                        flattened_results.append(flattened_entry)
            
            # Update total_rows for all entries from this project
            project_end_index = len(flattened_results)
            for i in range(project_start_index, project_end_index):
                flattened_results[i]["total_rows"] = row_count
            
            entries_added = project_end_index - project_start_index
            print(f"✓ Complete! ({row_count} rows, {dimensions_count} dimensions, {entries_added} flattened entries)")
            
        except Exception as e:
            print(f"✗ ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            continue
    
    # Write flattened results to JSON file
    print(f"\n💾 Writing {len(flattened_results)} entries to {output_file}...", end=" ", flush=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "flattened_results": flattened_results
        }, f, indent=2, ensure_ascii=False, default=json_serializer)
    
    print("✓ Complete!")
    
    file_size = os.path.getsize(output_file) / (1024 * 1024)  # Size in MB
    print(f"\n✅ Successfully extracted {len(flattened_results):,} flattened entries from {total_projects}/{total_project_count} projects")
    print(f"   📁 Output file: {output_file}")
    print(f"   📊 File size: {file_size:.2f} MB")
    
    return output_file


def extract_analyzed_results(project_id: str, output_file: str = None):
    """Extract analyzed results from a specific project.
    
    Args:
        project_id: The ID of the project to extract results from
        output_file: Optional output file name (defaults to project_{id}_results.txt)
    """
    # Create client with API key
    client = Client(api_key=Config.API_KEY)
    
    # Retrieve the project
    project = client.projects.retrieve(id=project_id)
    
    # Create a mapping from column ref to column name (question text)
    # Also create a reverse mapping from column name to ref for metadata lookup
    column_map = {}
    column_name_to_ref = {}
    if hasattr(project, 'columns') and project.columns:
        for col in project.columns:
            if hasattr(col, 'ref') and hasattr(col, 'name'):
                column_map[col.ref] = col.name
                column_name_to_ref[col.name] = col.ref
    
    if output_file is None:
        output_file = f"project_{project_id}_results.txt"
    
    # List all rows
    rows = project.list_rows()
    
    # Collect all records with analysis results
    records = []
    analysis_results = []
    
    row_count = 0
    for row in rows:
        row_count += 1
        row_data = {
            "row_id": row.id  # Include row_id in all_records
        }
        row_analysis = {
            "row_id": row.id,
            "created": getattr(row, 'created', None),
            "last_modified": getattr(row, 'last_modified', None),
            "columns": []
        }
        
        # Get all column values
        for col in row.columns:
            # Store column value
            row_data[col.ref] = col.value
            
            # Extract analysis results for text_to_analyze columns
            if col.type == "text_to_analyze":
                col_analysis = {
                    "column_ref": col.ref,
                    "column_name": column_map.get(col.ref, None),
                    "value": col.value,
                    "overall_sentiment": getattr(col, 'sentiment_overall', None),
                    "topics": []
                }
                
                # Extract topics
                for topic in col.topics:
                    topic_data = {
                        "category": topic.category,
                        "label": topic.label,
                    }
                    
                    # Add sentiment if available
                    if hasattr(topic, 'sentiment_enabled') and topic.sentiment_enabled:
                        topic_data["sentiment"] = getattr(topic, 'sentiment', None)
                    
                    # Add value if available
                    if hasattr(topic, 'value'):
                        topic_data["value"] = topic.value
                    
                    col_analysis["topics"].append(topic_data)
                
                row_analysis["columns"].append(col_analysis)
        
        # Add metadata to row_analysis (dynamically find columns by name)
        # Look up column refs by name to handle different projects with different refs
        region_ref = column_name_to_ref.get("region")
        response_type_ref = column_name_to_ref.get("Response Type")
        start_date_ref = column_name_to_ref.get("Start Date (UTC)")
        submit_date_ref = column_name_to_ref.get("Submit Date (UTC)")
        
        row_analysis["metadata"] = {
            "region": row_data.get(region_ref) if region_ref else None,
            "response_type": row_data.get(response_type_ref) if response_type_ref else None,
            "start_date": row_data.get(start_date_ref) if start_date_ref else None,
            "submit_date": row_data.get(submit_date_ref) if submit_date_ref else None,
        }
        
        records.append(row_data)
        if row_analysis["columns"]:
            analysis_results.append(row_analysis)
    
    # Write results to text file
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"Analysis Results for Project: {project.name}\n")
        f.write(f"{'=' * 70}\n\n")
        f.write(f"Project ID: {project.id}\n")
        f.write(f"Total Rows: {row_count}\n")
        f.write(f"Rows with Analysis: {len(analysis_results)}\n\n")
        f.write(f"{'=' * 70}\n\n")
        
        # Write analysis results
        for i, result in enumerate(analysis_results, 1):
            f.write(f"ROW {i} (ID: {result['row_id']})\n")
            f.write(f"{'-' * 70}\n")
            
            for col_analysis in result["columns"]:
                f.write(f"\nColumn: {col_analysis['column_ref']}\n")
                if col_analysis.get('column_name'):
                    f.write(f"Question: {col_analysis['column_name']}\n")
                f.write(f"Value: {col_analysis['value']}\n")
                f.write(f"Overall Sentiment: {col_analysis['overall_sentiment']}\n")
                f.write(f"\nTopics ({len(col_analysis['topics'])}):\n")
                
                if col_analysis['topics']:
                    for topic in col_analysis['topics']:
                        f.write(f"  - Category: {topic['category']}\n")
                        f.write(f"    Label: {topic['label']}\n")
                        if 'sentiment' in topic and topic['sentiment']:
                            f.write(f"    Sentiment: {topic['sentiment']}\n")
                        f.write("\n")
                else:
                    f.write("  (No topics found)\n")
                
                f.write("\n")
            
            f.write(f"\n{'=' * 70}\n\n")
        
        # If no analysis results, inform user
        if not analysis_results:
            f.write("No analysis results found. Analysis may not have been performed yet.\n")
    
    # Also save raw data as JSON for easier processing
    # Helper function to convert non-serializable objects to strings
    def json_serializer(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")
    
    json_output_file = output_file.replace('.txt', '.json')
    
    # Build column definitions for reference
    column_definitions = []
    if hasattr(project, 'columns') and project.columns:
        for col in project.columns:
            col_def = {
                "ref": col.ref,
                "name": getattr(col, 'name', None),
                "type": getattr(col, 'type', None)
            }
            column_definitions.append(col_def)
    
    with open(json_output_file, "w", encoding="utf-8") as f:
        json.dump({
            "project_id": project.id,
            "project_name": project.name,
            "total_rows": row_count,
            "column_definitions": column_definitions,
            "analysis_results": analysis_results,
            "all_records": records
        }, f, indent=2, ensure_ascii=False, default=json_serializer)
    
    print(f"✅ Successfully extracted analysis results:")
    print(f"   - Text file: {output_file}")
    print(f"   - JSON file: {json_output_file}")
    print(f"   - Total rows: {row_count}")
    print(f"   - Rows with analysis: {len(analysis_results)}")
    
    return output_file, json_output_file


def extract_project_flattened(project_name: str = None, project_id: str = None, output_file: str = None, output_dir: str = "outputs"):
    """Extract a single project from Caplena and flatten it to match the target format.
    
    Args:
        project_name: Name of the project to extract (searches for partial match)
        project_id: ID of the project to extract (takes precedence over project_name)
        output_file: Output file name (defaults to project_{id}_flattened.json)
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
    
    # Create client with API key
    client = Client(api_key=Config.API_KEY)
    
    # Find the project
    if project_id:
        print(f"📡 Retrieving project by ID: {project_id}...")
        try:
            project = client.projects.retrieve(id=project_id)
            project_name_found = project.name
        except Exception as e:
            print(f"❌ Error retrieving project {project_id}: {e}")
            raise
    elif project_name:
        print(f"📡 Searching for project: {project_name}...")
        projects = client.projects.list()
        project = None
        project_name_found = None
        
        # Search for project by name (case-insensitive partial match)
        for proj_summary in projects:
            if project_name.lower() in proj_summary.name.lower():
                project_name_found = proj_summary.name
                project_id = proj_summary.id
                print(f"   Found: {project_name_found} (ID: {project_id})")
                project = client.projects.retrieve(id=project_id)
                break
        
        if not project:
            print(f"❌ Project '{project_name}' not found")
            print(f"   Available projects (first 10):")
            for i, proj in enumerate(list(projects)[:10], 1):
                print(f"   {i}. {proj.name} (ID: {proj.id})")
            raise ValueError(f"Project '{project_name}' not found")
    else:
        raise ValueError("Either project_name or project_id must be provided")
    
    # Set default output file if not provided
    if output_file is None:
        safe_name = project_name_found.replace(" ", "_").replace("/", "_")[:50] if project_name_found else project_id
        output_file = os.path.join(output_dir, f"{safe_name}_flattened.json")
    else:
        output_file = os.path.join(output_dir, output_file)
    
    print(f"📊 Processing project: {project_name_found}")
    
    # Get client information
    client_id = getattr(project, 'client_id', None)
    client_name = getattr(project, 'client_name', None)
    if not client_id and hasattr(project, 'client'):
        # Try to get from client object if it exists
        client_obj = getattr(project, 'client', None)
        if client_obj:
            client_id = getattr(client_obj, 'id', None)
            client_name = getattr(client_obj, 'name', None)
    
    # Get data source
    data_source = getattr(project, 'data_source', None)
    if not data_source and hasattr(project, 'source'):
        data_source = getattr(project, 'source', None)
    
    # Create a mapping from column ref to column name (question text)
    # Also create a reverse mapping from column name to ref for metadata lookup
    column_map = {}
    column_name_to_ref = {}
    if hasattr(project, 'columns') and project.columns:
        for col in project.columns:
            if hasattr(col, 'ref') and hasattr(col, 'name'):
                column_map[col.ref] = col.name
                column_name_to_ref[col.name] = col.ref
    
    # Count text_to_analyze dimensions first
    dimensions_count = 0
    if hasattr(project, 'columns') and project.columns:
        dimensions = [c for c in project.columns if getattr(c, 'type', None) == 'text_to_analyze']
        dimensions_count = len(dimensions)
    
    # List all rows
    print("Loading rows...", end=" ", flush=True)
    rows = project.list_rows()
    row_count = 0
    flattened_results = []
    
    # Identify text_to_analyze column refs (these are dimensions, not metadata)
    text_column_refs = set()
    if hasattr(project, 'columns') and project.columns:
        for col in project.columns:
            if getattr(col, 'type', None) == 'text_to_analyze':
                text_column_refs.add(col.ref)

    # Process each row
    rows_processed = 0
    for row in rows:
        row_count += 1
        rows_processed += 1

        # Show progress every 500 rows
        if rows_processed % 500 == 0:
            print(f"row {rows_processed}...", end=" ", flush=True)

        # Get all column values and build survey_metadata from non-text columns
        row_data = {}
        survey_metadata = {}
        for col in row.columns:
            row_data[col.ref] = col.value
            # Collect all non-text_to_analyze columns as metadata
            if col.ref not in text_column_refs and col.value is not None and col.value != "":
                col_name = column_map.get(col.ref, col.ref)
                survey_metadata[col_name] = col.value

        # Extract row-level timestamps
        row_created = getattr(row, 'created', None)
        row_last_modified = getattr(row, 'last_modified', None)

        # Convert datetime objects to ISO format strings
        if row_created and isinstance(row_created, datetime):
            row_created = row_created.isoformat()
        if row_last_modified and isinstance(row_last_modified, datetime):
            row_last_modified = row_last_modified.isoformat()

        # Process each text_to_analyze column (dimension) and create a flattened entry
        for col in row.columns:
            if col.type == "text_to_analyze":
                # Extract topics
                topics = []
                for topic in col.topics:
                    topic_data = {
                        "category": topic.category,
                        "label": topic.label,
                    }
                    topics.append(topic_data)

                # Create flattened entry
                flattened_entry = {
                    "respondent_id": row.id,
                    "created": row_created,
                    "last_modified": row_last_modified,
                    "client_id": client_id,
                    "client_name": client_name,
                    "project_id": project.id,
                    "project_name": project.name,
                    "total_rows": row_count,  # Will be updated to final count after processing
                    "data_source": data_source,
                    "survey_metadata": survey_metadata if survey_metadata else None,
                    "dimension_ref": col.ref,
                    "dimension_name": column_map.get(col.ref, None),
                    "value": col.value if col.value else "",
                    "overall_sentiment": getattr(col, 'sentiment_overall', None),
                    "topics": topics
                }

                flattened_results.append(flattened_entry)
    
    # Update total_rows for all entries from this project
    for i in range(len(flattened_results)):
        flattened_results[i]["total_rows"] = row_count
    
    entries_added = len(flattened_results)
    print(f"✓ Complete! ({row_count} rows, {dimensions_count} dimensions, {entries_added} flattened entries)")
    
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


if __name__ == "__main__":
    # Extract all projects and flatten them to match the target format
    extract_all_projects_flattened()

