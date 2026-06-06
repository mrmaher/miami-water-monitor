"""Initialize (or migrate) the SQLite database from schema.sql."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'water_monitor.db')
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), 'schema.sql')


def get_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = get_db(db_path)
    with open(SCHEMA_PATH, 'r') as f:
        conn.executescript(f.read())
    conn.commit()
    return conn


if __name__ == '__main__':
    db_path = os.path.abspath(DB_PATH)
    conn = init_db(db_path)
    print(f"Database initialized at: {db_path}")
    for row in conn.execute("SELECT name, veracity_tier FROM sources"):
        print(f"  source: {row['name']} ({row['veracity_tier']})")
    for row in conn.execute("SELECT name, location_type FROM sites"):
        print(f"  site:   {row['name']} ({row['location_type']})")
    conn.close()
