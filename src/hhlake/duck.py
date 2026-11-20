import duckdb

from hhlake.settings import S3Settings


def connect(threads: int | None = None, memory_limit: str | None = None) -> duckdb.DuckDBPyConnection:
    s = S3Settings()
    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(
        f"""
        CREATE OR REPLACE SECRET hh_lake (
            TYPE s3, KEY_ID '{s.access_key}', SECRET '{s.secret_key}', REGION '{s.region}',
            ENDPOINT '{s.host}', URL_STYLE 'path', USE_SSL false
        )
        """
    )
    if threads:
        con.execute(f"SET threads = {threads}")
    if memory_limit:
        con.execute(f"SET memory_limit = '{memory_limit}'")
    return con
