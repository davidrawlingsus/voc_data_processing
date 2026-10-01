#!/usr/bin/env python3
"""Interactive script to assign client names and UUIDs to projects."""

import json
import uuid
import sys
from collections import defaultdict

JSON_FILE = 'outputs/all_projects_flattened.json'
BACKUP_FILE = 'outputs/all_projects_flattened.json.backup'

def load_data():
    """Load the JSON file."""
    try:
        with open(JSON_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ Error: {JSON_FILE} not found!")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON - {e}")
        sys.exit(1)

def save_data(data):
    """Save the JSON file."""
    with open(JSON_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def backup_data():
    """Create a backup of the current file."""
    import shutil
    try:
        shutil.copy2(JSON_FILE, BACKUP_FILE)
        print(f"📦 Backup created: {BACKUP_FILE}")
    except Exception as e:
        print(f"⚠️  Warning: Could not create backup: {e}")

def get_unique_projects(data):
    """Get unique projects and their current info."""
    projects = {}
    for entry in data['flattened_results']:
        project_name = entry.get('project_name', 'Unknown')
        if project_name not in projects:
            projects[project_name] = {
                'client_name': entry.get('client_name'),
                'client_id': entry.get('client_id'),
                'client_uuid': entry.get('client_uuid'),
                'count': 0
            }
        projects[project_name]['count'] += 1
    return projects

def update_project_client(data, project_name, client_name, client_uuid):
    """Update all entries for a project with new client info."""
    updated = 0
    for entry in data['flattened_results']:
        if entry.get('project_name') == project_name:
            entry['client_name'] = client_name
            entry['client_uuid'] = client_uuid
            updated += 1
    return updated

def main():
    print("=" * 70)
    print("Client Name Assignment Tool")
    print("=" * 70)
    print()
    
    # Load data
    print("📂 Loading data...")
    data = load_data()
    projects = get_unique_projects(data)
    
    print(f"✅ Loaded {len(data['flattened_results']):,} entries")
    print(f"📊 Found {len(projects)} unique projects")
    print()
    
    # Create backup
    backup_data()
    print()
    
    # Group projects by current client name (if any)
    projects_by_client = defaultdict(list)
    projects_needing_assignment = []
    
    for project_name, info in sorted(projects.items()):
        client_name = info['client_name']
        if client_name:
            projects_by_client[client_name].append(project_name)
        else:
            projects_needing_assignment.append(project_name)
    
    print(f"📋 Projects already assigned to clients: {len(projects_by_client)}")
    print(f"📋 Projects needing assignment: {len(projects_needing_assignment)}")
    print()
    
    # Show existing client assignments
    if projects_by_client:
        print("Existing client assignments:")
        for client_name, project_list in sorted(projects_by_client.items()):
            print(f"  {client_name}: {len(project_list)} project(s)")
        print()
    
    # Build existing client UUID map from already assigned projects
    existing_client_uuid_map = {}
    for project_name, info in projects.items():
        if info['client_name'] and info['client_uuid']:
            if info['client_name'] not in existing_client_uuid_map:
                existing_client_uuid_map[info['client_name']] = info['client_uuid']
    
    # Track client UUIDs (start with existing ones)
    client_uuid_map = existing_client_uuid_map.copy()
    
    # Interactive assignment
    print("=" * 70)
    print("INTERACTIVE ASSIGNMENT")
    print("=" * 70)
    print()
    print("For each project, enter a client name.")
    print("Projects with the same client name will share the same client_uuid.")
    print("If a project already has a client name, you can change it by entering a new one.")
    print()
    if existing_client_uuid_map:
        print("Existing client assignments:")
        for client_name, client_uuid in sorted(existing_client_uuid_map.items()):
            print(f"  {client_name}: {client_uuid}")
        print()
    print("Commands:")
    print("  - Press Enter to skip a project (keep current assignment if exists)")
    print("  - Type 'skip' to skip remaining projects")
    print("  - Type 'list' to see all projects")
    print("  - Type 'show' to see current client assignments")
    print("  - Type 'done' to finish and save")
    print()
    
    # Process all projects (both assigned and unassigned)
    all_projects_list = sorted(projects.keys())
    for i, project_name in enumerate(all_projects_list, 1):
        project_info = projects[project_name]
        current_client = project_info['client_name'] or 'None'
        print(f"[{i}/{len(all_projects_list)}] Project: {project_name}")
        print(f"    Current: client_name={current_client}, "
              f"entries={project_info['count']}")
        
        while True:
            client_name = input("    Enter client name (or skip/list/done): ").strip()
            
            if client_name.lower() == 'done':
                print("\n💾 Saving changes...")
                save_data(data)
                print("✅ Saved successfully!")
                print(f"\n📊 Summary:")
                print(f"   Total clients: {len(client_uuid_map)}")
                for cn, cuuid in sorted(client_uuid_map.items()):
                    print(f"   {cn}: {cuuid}")
                return
            
            elif client_name.lower() == 'skip':
                print("⏭️  Skipping remaining projects...")
                break
            
            elif client_name.lower() == 'list':
                print("\n📋 Remaining projects:")
                for j, pn in enumerate(all_projects_list[i-1:], i):
                    current = projects[pn]['client_name'] or 'None'
                    print(f"   {j}. {pn} ({projects[pn]['count']} entries) - client: {current}")
                print()
                continue
            
            elif client_name.lower() == 'show':
                print("\n📋 Current client assignments:")
                for cn, cuuid in sorted(client_uuid_map.items()):
                    project_count = sum(1 for e in data['flattened_results'] 
                                       if e.get('client_name') == cn)
                    print(f"   {cn}: {cuuid} ({project_count} entries)")
                print()
                continue
            
            elif client_name == '':
                if project_info['client_name']:
                    print(f"   ✅ Keeping current assignment: {project_info['client_name']}")
                else:
                    print("⏭️  Skipping this project (no client name assigned)")
                break
            
            else:
                # Assign client
                # Generate or reuse UUID for this client name
                if client_name not in client_uuid_map:
                    client_uuid_map[client_name] = str(uuid.uuid4())
                    print(f"   ✅ Assigned to new client: {client_name}")
                    print(f"   📝 Generated UUID: {client_uuid_map[client_name]}")
                else:
                    print(f"   ✅ Assigned to existing client: {client_name}")
                    print(f"   📝 Using UUID: {client_uuid_map[client_name]}")
                
                # Update all entries for this project
                updated = update_project_client(
                    data, project_name, client_name, client_uuid_map[client_name]
                )
                print(f"   ✏️  Updated {updated} entries")
                break
        
        print()
    
    # Final save
    print("\n💾 Saving changes...")
    save_data(data)
    print("✅ Saved successfully!")
    
    # Summary
    print(f"\n📊 Summary:")
    print(f"   Total clients: {len(client_uuid_map)}")
    
    # Count projects per client
    client_projects = defaultdict(list)
    for entry in data['flattened_results']:
        client_name = entry.get('client_name')
        project_name = entry.get('project_name')
        if client_name and project_name:
            if project_name not in client_projects[client_name]:
                client_projects[client_name].append(project_name)
    
    for client_name, client_uuid in sorted(client_uuid_map.items()):
        projects_for_client = client_projects.get(client_name, [])
        entry_count = sum(1 for e in data['flattened_results'] 
                         if e.get('client_name') == client_name)
        print(f"   {client_name}:")
        print(f"      UUID: {client_uuid}")
        print(f"      Projects: {len(projects_for_client)}")
        print(f"      Total entries: {entry_count:,}")
        for p in sorted(projects_for_client)[:5]:
            print(f"        - {p}")
        if len(projects_for_client) > 5:
            print(f"        ... and {len(projects_for_client) - 5} more")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user. Changes not saved.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

