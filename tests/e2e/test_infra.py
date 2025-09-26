import os


def test_postgres_connection():
    """Stub test: connect to Postgres started by infra."""
    db_url = os.environ.get("DB_URL")
    assert db_url, "DB_URL not set in environment"
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute("SELECT 1;")
    result = cur.fetchone()
    assert result == (1,)
    cur.close()
    conn.close()
