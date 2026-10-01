#!/usr/bin/env python3
"""
Script to extract "USF - 2024 Reviews" from Caplena, process it, and upload to DB.
Sets proper metadata:
- Client: Online Stores
- Project: United States Flag
- Source: Reviews
- Dimension: Site Jabber
"""

import json
import os
import sys
from main import extract_project_flattened
from upload_to_db import upload_flattened_data

# Try to load dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def update_metadata_for_usf_reviews(json_file: str):
    """Update metadata in the flattened JSON to match requirements.
    
    Args:
        json_file: Path to the flattened JSON file
    """
    print(f"\n📝 Updating metadata in {json_file}...")
    
    # Load JSON data
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    flattened_results = data.get('flattened_results', [])
    if not flattened_results:
        print("❌ Error: No 'flattened_results' found in JSON file")
        return
    
    updated_count = 0
    
    for entry in flattened_results:
        # Update metadata according to requirements
        entry['client_name'] = 'Online Stores'
        entry['project_name'] = 'United States Flag'
        entry['data_source'] = 'Reviews'
        
        # Update dimension_name to "Site Jabber" as required
        # (Caplena has it as "Review Content" but we need "Site Jabber")
        entry['dimension_name'] = 'Site Jabber'
        
        updated_count += 1
    
    # Save updated data
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Updated {updated_count:,} entries with correct metadata")
    return json_file


def main():
    """Main function to extract, process, and upload USF - 2024 Reviews."""
    
    # Search terms - try different variations
    search_terms = [
        "USF - 2024 Reviews",
        "USF 2024 Reviews",
        "US Flag 2024",
        "US Flag - 2024"
    ]
    
    project_id = None
    project_name = None
    
    # Try to find the project
    print("🔍 Searching for project...")
    from caplena import Client
    from config import Config
    
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
    
    # Extract the project
    print(f"\n📥 Extracting project: {project_name}...")
    output_file = extract_project_flattened(
        project_id=project_id,
        output_file="usf_2024_reviews_flattened.json",
        output_dir="outputs"
    )
    
    # Update metadata
    update_metadata_for_usf_reviews(output_file)
    
    # Upload to database
    print(f"\n📤 Uploading to database...")
    upload_flattened_data(output_file, batch_size=1000)
    
    print(f"\n✅ Complete! Data extracted and uploaded successfully.")
    print(f"   📁 JSON file: {output_file}")


if __name__ == "__main__":
    main()
