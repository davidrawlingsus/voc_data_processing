#!/usr/bin/env python3
"""Script to standardize data_source values in the flattened JSON file."""

import json
import shutil
from datetime import datetime

JSON_FILE = 'outputs/all_projects_flattened.json'
BACKUP_FILE = 'outputs/all_projects_flattened.json.backup'

# Mapping from inferred sources to standardized names
SOURCE_MAPPING = {
    # Success Page Survey
    'success_page': 'Success Page Survey',
    'magic_question': 'Success Page Survey',
    'hotjar': 'Success Page Survey',
    
    # Email Survey
    'email_survey': 'Email Survey',
    'survey': 'Email Survey',
    'value_map': 'Email Survey',
    'verbatims': 'Email Survey',
    
    # Review Data
    'trustpilot': 'Review Data',
    'reviews': 'Review Data',
    'yotpo': 'Review Data',
    
    # NPS
    'nps': 'NPS',
    
    # Amazon Reviews
    'amazon': 'Amazon Reviews',
    
    # Facebook Survey
    'facebook': 'Facebook Survey',
    
    # Livechat Transcripts
    'chat': 'Livechat Transcripts',
    'intercom': 'Livechat Transcripts',
    
    # Pollfish
    'pollfish': 'Pollfish',  # Keep as is, or add to mapping if needed
}

# Patterns to infer data source from project name
PROJECT_PATTERNS = {
    'success_page': ['Success Page', 'success page', 'Success'],
    'magic_question': ['Magic Question', 'magic question'],
    'hotjar': ['Hotjar', 'hotjar'],
    'email_survey': ['Email Survey', 'email survey', 'Email'],
    'survey': ['Survey', 'survey'],
    'value_map': ['ValueMap', 'Value Map', 'value map'],
    'verbatims': ['Verbatims', 'verbatims'],
    'trustpilot': ['Trustpilot', 'Trust Pilot', 'trustpilot'],
    'reviews': ['Reviews', 'reviews'],
    'yotpo': ['Yotpo', 'yotpo'],
    'nps': ['NPS', 'nps'],
    'amazon': ['Amazon', 'amazon'],
    'facebook': ['FB ', 'Facebook', 'facebook'],
    'chat': ['Chat', 'chat', 'chats'],
    'intercom': ['Intercom', 'intercom'],
    'pollfish': ['Pollfish', 'pollfish'],
}

def infer_source_from_project_name(project_name):
    """Infer data source from project name."""
    if not project_name:
        return None
    
    for source, patterns in PROJECT_PATTERNS.items():
        if any(pattern in project_name for pattern in patterns):
            return source
    return None

def standardize_data_source(inferred_source):
    """Map inferred source to standardized name."""
    if not inferred_source:
        return None
    return SOURCE_MAPPING.get(inferred_source, None)

def load_data():
    """Load the JSON file."""
    try:
        with open(JSON_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ Error: {JSON_FILE} not found!")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON - {e}")
        return None

def save_data(data):
    """Save the JSON file."""
    with open(JSON_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def backup_data():
    """Create a backup of the current file."""
    try:
        shutil.copy2(JSON_FILE, BACKUP_FILE)
        print(f"📦 Backup created: {BACKUP_FILE}")
        return True
    except Exception as e:
        print(f"⚠️  Warning: Could not create backup: {e}")
        return False

def main():
    print("=" * 70)
    print("Data Source Standardization Tool")
    print("=" * 70)
    print()
    
    # Load data
    print("📂 Loading data...")
    data = load_data()
    if not data:
        return
    
    total_entries = len(data['flattened_results'])
    print(f"✅ Loaded {total_entries:,} entries")
    print()
    
    # Create backup
    if not backup_data():
        response = input("Continue without backup? (y/n): ").strip().lower()
        if response != 'y':
            print("Cancelled.")
            return
    print()
    
    # Process entries
    print("🔍 Processing entries...")
    updated_count = 0
    unchanged_count = 0
    no_source_count = 0
    
    # Track statistics
    source_stats = {}
    project_source_map = {}
    
    for entry in data['flattened_results']:
        project_name = entry.get('project_name', '')
        current_source = entry.get('data_source')
        
        # Infer source from project name
        inferred_source = infer_source_from_project_name(project_name)
        standardized_source = standardize_data_source(inferred_source)
        
        # Track project to source mapping
        if project_name and project_name not in project_source_map:
            project_source_map[project_name] = standardized_source
        
        # Update entry
        if standardized_source:
            entry['data_source'] = standardized_source
            updated_count += 1
            
            # Track statistics
            if standardized_source not in source_stats:
                source_stats[standardized_source] = 0
            source_stats[standardized_source] += 1
        else:
            if current_source:
                unchanged_count += 1
            else:
                no_source_count += 1
    
    print(f"✅ Processed {total_entries:,} entries")
    print()
    
    # Show statistics
    print("=" * 70)
    print("STATISTICS")
    print("=" * 70)
    print(f"Updated entries: {updated_count:,}")
    print(f"Unchanged entries: {unchanged_count:,}")
    print(f"Entries without source: {no_source_count:,}")
    print()
    
    print("Data sources assigned:")
    print("-" * 70)
    for source, count in sorted(source_stats.items(), key=lambda x: -x[1]):
        percentage = (count / total_entries) * 100
        print(f"  {source:30s} {count:>8,} entries ({percentage:>5.1f}%)")
    print()
    
    # Show projects without source
    projects_without_source = [p for p, s in project_source_map.items() if not s]
    if projects_without_source:
        print(f"Projects without assigned data source ({len(projects_without_source)}):")
        print("-" * 70)
        for project in sorted(projects_without_source):
            entry_count = sum(1 for e in data['flattened_results'] 
                            if e.get('project_name') == project)
            print(f"  {project:60s} ({entry_count:,} entries)")
        print()
    
    # Save changes
    print("💾 Saving changes...")
    save_data(data)
    print("✅ Saved successfully!")
    print()
    print(f"📁 Updated file: {JSON_FILE}")
    print(f"📦 Backup file: {BACKUP_FILE}")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user. Changes not saved.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

