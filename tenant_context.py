"""
Multi-Tenant Context Management

This module provides utilities for setting up database session context
for Row-Level Security (RLS) policies.

Usage:
    # In your request middleware (Flask/FastAPI/Django):
    
    from tenant_context import set_tenant_context, clear_tenant_context
    
    @app.before_request
    def setup_tenant_context():
        # Get user_id from your auth system (JWT, session, etc.)
        user_id = get_current_user_id()  # Your auth function
        set_tenant_context(conn, user_id)
    
    @app.after_request
    def cleanup_tenant_context(response):
        clear_tenant_context(conn)
        return response
"""
import psycopg2
from typing import Optional, List
import uuid


def set_tenant_context(connection: psycopg2.extensions.connection, user_id: Optional[uuid.UUID]):
    """
    Set the tenant context for the current database connection.
    This sets the app.user_id session variable that RLS policies use.
    
    Note: Uses SET (not SET LOCAL) so it persists for the connection session.
    For connection pooling, consider using SET LOCAL within transactions instead.
    
    Args:
        connection: Active psycopg2 connection
        user_id: UUID of the current user (None for no access)
    
    Example:
        set_tenant_context(conn, uuid.UUID('123e4567-e89b-12d3-a456-426614174000'))
    """
    cursor = connection.cursor()
    try:
        if user_id:
            cursor.execute("SET app.user_id = %s", (str(user_id),))
        else:
            cursor.execute("SET app.user_id = NULL")
        connection.commit()
    finally:
        cursor.close()


def clear_tenant_context(connection: psycopg2.extensions.connection):
    """
    Clear the tenant context from the current database connection.
    
    Args:
        connection: Active psycopg2 connection
    """
    cursor = connection.cursor()
    try:
        cursor.execute("RESET app.user_id")
        connection.commit()
    finally:
        cursor.close()


def get_user_context(connection: psycopg2.extensions.connection) -> Optional[uuid.UUID]:
    """
    Get the current user_id from the database session.
    
    Args:
        connection: Active psycopg2 connection
    
    Returns:
        UUID of current user, or None if not set
    """
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT current_setting('app.user_id', true)")
        result = cursor.fetchone()
        if result and result[0]:
            return uuid.UUID(result[0])
        return None
    except (psycopg2.Error, ValueError):
        return None
    finally:
        cursor.close()


class TenantContext:
    """
    Context manager for automatic tenant context setup/cleanup.
    
    Example:
        with TenantContext(conn, user_id):
            # All queries here will use RLS policies for this user
            cursor.execute("SELECT * FROM process_voc LIMIT 10")
    """
    
    def __init__(self, connection: psycopg2.extensions.connection, user_id: Optional[uuid.UUID]):
        self.connection = connection
        self.user_id = user_id
    
    def __enter__(self):
        set_tenant_context(self.connection, self.user_id)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        clear_tenant_context(self.connection)
        return False


def get_user_client_ids(connection: psycopg2.extensions.connection, user_id: uuid.UUID) -> List[uuid.UUID]:
    """
    Get list of client UUIDs the user can access.
    Useful for pre-filtering queries or UI display.
    
    Args:
        connection: Active psycopg2 connection
        user_id: UUID of the user
    
    Returns:
        List of client UUIDs the user can access
    """
    cursor = connection.cursor()
    try:
        # Temporarily set context to get accessible clients
        with TenantContext(connection, user_id):
            cursor.execute("SELECT get_accessible_client_ids()")
            result = cursor.fetchone()
            if result and result[0]:
                return result[0]  # Returns UUID[] from PostgreSQL
            return []
    finally:
        cursor.close()


def get_user_role_for_client(connection: psycopg2.extensions.connection, 
                             user_id: uuid.UUID, 
                             client_id: uuid.UUID) -> Optional[str]:
    """
    Get the role of a user for a specific client.
    
    Args:
        connection: Active psycopg2 connection
        user_id: UUID of the user
        client_id: UUID of the client
    
    Returns:
        Role string ('owner', 'admin', 'editor', 'viewer') or None
    """
    cursor = connection.cursor()
    try:
        with TenantContext(connection, user_id):
            cursor.execute("SELECT get_user_role_for_client(%s)", (str(client_id),))
            result = cursor.fetchone()
            if result and result[0]:
                return result[0]
            return None
    finally:
        cursor.close()


def can_user_access_client(connection: psycopg2.extensions.connection,
                           user_id: uuid.UUID,
                           client_id: uuid.UUID) -> bool:
    """
    Check if a user can access a specific client.
    
    Args:
        connection: Active psycopg2 connection
        user_id: UUID of the user
        client_id: UUID of the client
    
    Returns:
        True if user can access the client, False otherwise
    """
    cursor = connection.cursor()
    try:
        with TenantContext(connection, user_id):
            cursor.execute("SELECT can_access_client(%s)", (str(client_id),))
            result = cursor.fetchone()
            return result[0] if result else False
    finally:
        cursor.close()
