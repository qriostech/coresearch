from connections.postgres import get_cursor

def test_cursor_query():
    with get_cursor() as cur:
        cur.execute("SELECT 1 AS val")
        row = cur.fetchone()
    assert row["val"] == 1

def test_tables_exist():
    tables = {"sessions", "seeds", "branches", "iterations", "iteration_metrics"}
    with get_cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
        """)
        existing = {row["table_name"] for row in cur.fetchall()}
    assert tables <= existing, f"Missing tables: {tables - existing}"
