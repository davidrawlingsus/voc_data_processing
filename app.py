#!/usr/bin/env python3
"""
Flask web application to view process_voc data.
"""
import os
import uuid
from flask import Flask, render_template_string, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from tenant_context import TenantContext

# Try to load dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)

# Get database credentials
DATABASE_URL = os.getenv('DATABASE_PUBLIC_URL') or os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_PUBLIC_URL or DATABASE_URL must be set")

def get_db():
    """Get database connection."""
    return psycopg2.connect(DATABASE_URL)

def get_founder_user_id(conn):
    """Get the founder user ID."""
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id FROM users 
            WHERE is_founder = TRUE AND is_active = TRUE 
            LIMIT 1
        """)
        result = cursor.fetchone()
        return uuid.UUID(result[0]) if result else None
    finally:
        cursor.close()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Process VOC Data Viewer</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: #f5f5f5;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            padding: 30px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            margin-bottom: 10px;
        }
        .stats {
            display: flex;
            gap: 20px;
            margin: 20px 0;
            flex-wrap: wrap;
        }
        .stat-card {
            background: #f8f9fa;
            padding: 15px 20px;
            border-radius: 6px;
            flex: 1;
            min-width: 200px;
        }
        .stat-label {
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .stat-value {
            font-size: 24px;
            font-weight: bold;
            color: #333;
            margin-top: 5px;
        }
        .filters {
            display: flex;
            gap: 15px;
            margin: 20px 0;
            flex-wrap: wrap;
            align-items: flex-end;
        }
        .filter-group {
            flex: 1;
            min-width: 200px;
        }
        label {
            display: block;
            font-size: 12px;
            font-weight: 600;
            color: #555;
            margin-bottom: 5px;
        }
        input, select {
            width: 100%;
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
        }
        button {
            padding: 8px 20px;
            background: #007bff;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
        }
        button:hover {
            background: #0056b3;
        }
        .table-container {
            overflow-x: auto;
            margin-top: 20px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }
        th {
            background: #f8f9fa;
            padding: 12px;
            text-align: left;
            font-weight: 600;
            color: #555;
            border-bottom: 2px solid #dee2e6;
            position: sticky;
            top: 0;
        }
        td {
            padding: 10px 12px;
            border-bottom: 1px solid #e9ecef;
        }
        tr:hover {
            background: #f8f9fa;
        }
        .pagination {
            display: flex;
            justify-content: center;
            gap: 10px;
            margin-top: 20px;
            align-items: center;
        }
        .pagination button {
            padding: 6px 12px;
            background: white;
            border: 1px solid #ddd;
            color: #333;
        }
        .pagination button:hover:not(:disabled) {
            background: #f8f9fa;
        }
        .pagination button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .loading {
            text-align: center;
            padding: 40px;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Process VOC Data Viewer</h1>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-label">Total Rows</div>
                <div class="stat-value">{{ stats.total_rows | default('0') }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Clients</div>
                <div class="stat-value">{{ stats.clients | default('0') }}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Projects</div>
                <div class="stat-value">{{ stats.projects | default('0') }}</div>
            </div>
        </div>

        <form method="GET" action="/">
            <div class="filters">
                <div class="filter-group">
                    <label>Client</label>
                    <select name="client_name">
                        <option value="">All Clients</option>
                        {% for client in clients %}
                        <option value="{{ client }}" {{ 'selected' if client == request.args.get('client_name') }}>{{ client }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="filter-group">
                    <label>Project</label>
                    <input type="text" name="project_name" value="{{ request.args.get('project_name', '') }}" placeholder="Filter by project name">
                </div>
                <div class="filter-group">
                    <label>Limit</label>
                    <select name="limit">
                        <option value="100" {{ 'selected' if request.args.get('limit', '100') == '100' }}>100</option>
                        <option value="500" {{ 'selected' if request.args.get('limit', '100') == '500' }}>500</option>
                        <option value="1000" {{ 'selected' if request.args.get('limit', '100') == '1000' }}>1000</option>
                    </select>
                </div>
                <div class="filter-group">
                    <button type="submit">Filter</button>
                </div>
            </div>
        </form>

        <div class="table-container">
            {% if data %}
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Client</th>
                        <th>Project</th>
                        <th>Dimension</th>
                        <th>Value</th>
                        <th>Sentiment</th>
                        <th>Topics</th>
                    </tr>
                </thead>
                <tbody>
                    {% for row in data %}
                    <tr>
                        <td>{{ row.id }}</td>
                        <td>{{ row.client_name or '-' }}</td>
                        <td>{{ row.project_name or '-' }}</td>
                        <td>{{ row.dimension_name or row.dimension_ref or '-' }}</td>
                        <td style="max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                            {{ (row.value or '')[:100] }}{% if row.value and row.value|length > 100 %}...{% endif %}
                        </td>
                        <td>{{ row.overall_sentiment or '-' }}</td>
                        <td>
                            {% if row.topics %}
                                {% for topic in row.topics[:3] %}
                                    <span style="background: #e9ecef; padding: 2px 6px; border-radius: 3px; font-size: 11px; margin-right: 4px;">
                                        {{ topic.label }}
                                    </span>
                                {% endfor %}
                                {% if row.topics|length > 3 %}...{% endif %}
                            {% else %}
                                -
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <div class="loading">No data found</div>
            {% endif %}
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    """Main page showing process_voc data."""
    conn = get_db()
    try:
        founder_user_id = get_founder_user_id(conn)
        
        # Get stats
        with TenantContext(conn, founder_user_id):
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            # Get total count
            cursor.execute("SELECT COUNT(*) as count FROM process_voc")
            total_rows = cursor.fetchone()['count']
            
            # Get unique clients
            cursor.execute("""
                SELECT DISTINCT client_name 
                FROM process_voc 
                WHERE client_name IS NOT NULL 
                ORDER BY client_name
            """)
            clients = [row['client_name'] for row in cursor.fetchall()]
            clients_count = len(clients)
            
            # Get unique projects
            cursor.execute("""
                SELECT COUNT(DISTINCT project_id) as count 
                FROM process_voc 
                WHERE project_id IS NOT NULL
            """)
            projects_count = cursor.fetchone()['count']
            
            # Get filter parameters
            client_name = request.args.get('client_name', '')
            project_name = request.args.get('project_name', '')
            limit = int(request.args.get('limit', 100))
            
            # Build query
            query = "SELECT id, client_name, project_name, dimension_name, dimension_ref, value, overall_sentiment, topics FROM process_voc WHERE 1=1"
            params = []
            
            if client_name:
                query += " AND client_name = %s"
                params.append(client_name)
            
            if project_name:
                query += " AND project_name ILIKE %s"
                params.append(f"%{project_name}%")
            
            query += " ORDER BY id DESC LIMIT %s"
            params.append(limit)
            
            cursor.execute(query, params)
            data = cursor.fetchall()
            
            # Convert topics from JSONB to list if it's a string
            for row in data:
                if row['topics'] and isinstance(row['topics'], str):
                    import json
                    try:
                        row['topics'] = json.loads(row['topics'])
                    except:
                        row['topics'] = []
            
            cursor.close()
        
        return render_template_string(HTML_TEMPLATE, 
            data=data,
            clients=clients,
            stats={
                'total_rows': total_rows,
                'clients': clients_count,
                'projects': projects_count
            }
        )
    finally:
        conn.close()

@app.route('/api/data')
def api_data():
    """API endpoint for JSON data."""
    conn = get_db()
    try:
        founder_user_id = get_founder_user_id(conn)
        
        with TenantContext(conn, founder_user_id):
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            limit = int(request.args.get('limit', 100))
            offset = int(request.args.get('offset', 0))
            
            cursor.execute("""
                SELECT * FROM process_voc 
                ORDER BY id DESC 
                LIMIT %s OFFSET %s
            """, (limit, offset))
            
            data = cursor.fetchall()
            cursor.close()
            
            return jsonify({
                'data': data,
                'limit': limit,
                'offset': offset
            })
    finally:
        conn.close()

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8000))
    print(f"🚀 Starting server on http://localhost:{port}")
    app.run(debug=True, host='0.0.0.0', port=port)
