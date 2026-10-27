import os

import mysql.connector
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    """Create a new connection using environment-based configuration."""
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", "root"),
        database=os.environ.get("DB_NAME", "sales_management_app"),
        connection_timeout=8,
    )
