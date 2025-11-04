"""Main script to connect to Caplena API and extract project list."""
import json
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


if __name__ == "__main__":
    # Extract results for the Collagen Research - Never Used - UK/US project
    extract_analyzed_results("pj_y6voz")

