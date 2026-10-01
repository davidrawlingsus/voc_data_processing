#!/usr/bin/env python3
"""
Script to extract "Naked Paper - Success" from Caplena, process it, and upload to DB.
Sets proper metadata:
- Client: Naked Paper
- Project: Naked Paper
- Source: Success Page
- Includes all available metadata (survey_metadata, question_text, question_type)
"""

import json
import os
import sys
from datetime import datetime
from caplena import Client
from main import extract_project_flattened
from upload_to_db import upload_flattened_data

# Try to load dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from config import Config


def update_metadata_for_naked_paper(json_file: str):
    """Update metadata in the flattened JSON to set correct client/project/source.

    Also enriches entries with question_text and question_type from dimension info.

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

    # Print a sample entry to understand available fields
    if flattened_results:
        sample = flattened_results[0]
        print(f"\n📋 Sample entry fields:")
        for key, value in sample.items():
            val_preview = str(value)[:100] if value else "None"
            print(f"   {key}: {val_preview}")

        # Show all unique dimension names
        dim_names = set(entry.get('dimension_name') for entry in flattened_results if entry.get('dimension_name'))
        print(f"\n📊 Found {len(dim_names)} unique dimensions:")
        for name in sorted(dim_names):
            count = sum(1 for e in flattened_results if e.get('dimension_name') == name)
            print(f"   - {name} ({count} entries)")

        # Show survey_metadata keys from first entry that has them
        for entry in flattened_results:
            if entry.get('survey_metadata'):
                print(f"\n📋 Survey metadata keys:")
                for key in sorted(entry['survey_metadata'].keys()):
                    print(f"   - {key}: {str(entry['survey_metadata'][key])[:80]}")
                break

    for entry in flattened_results:
        # Set correct client/project/source metadata
        entry['client_name'] = 'Naked Paper'
        entry['project_name'] = 'Naked Paper'
        entry['data_source'] = 'Success Page'

        # Set question_text from dimension_name if not already set
        if not entry.get('question_text') and entry.get('dimension_name'):
            entry['question_text'] = entry['dimension_name']

        # Classify question_type based on the dimension content
        if not entry.get('question_type'):
            value = entry.get('value', '')
            if value and len(value) > 50:
                entry['question_type'] = 'open_text'
            elif value:
                entry['question_type'] = 'open_text'

        updated_count += 1

    # Save updated data
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Updated {updated_count:,} entries with correct metadata")
    return json_file


def main():
    """Main function to extract, process, and upload Naked Paper - Success."""

    # Search terms - try different variations
    search_terms = [
        "Naked Paper - Success",
        "Naked Paper Success",
        "Naked Paper",
    ]

    project_id = None
    project_name = None

    # Try to find the project
    print("🔍 Searching for project in Caplena...")
    client = Client(api_key=Config.API_KEY)
    projects = list(client.projects.list())

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
        print("❌ Could not find 'Naked Paper' project. Available projects:")
        for i, proj in enumerate(projects, 1):
            print(f"   {i}. {proj.name} (ID: {proj.id})")
        sys.exit(1)

    # Extract the project
    print(f"\n📥 Extracting project: {project_name}...")
    output_file = extract_project_flattened(
        project_id=project_id,
        output_file="naked_paper_success_flattened.json",
        output_dir="outputs"
    )

    # Update metadata
    update_metadata_for_naked_paper(output_file)

    # Upload to database
    print(f"\n📤 Uploading to database...")
    upload_flattened_data(output_file, batch_size=1000)

    print(f"\n✅ Complete! Naked Paper - Success data extracted and uploaded successfully.")
    print(f"   📁 JSON file: {output_file}")


if __name__ == "__main__":
    main()
