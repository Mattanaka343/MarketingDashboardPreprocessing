import os

from dotenv import load_dotenv
from pandas import DataFrame
from sqlalchemy import create_engine, text

from sqlalchemy.engine import Engine

load_dotenv()

DB_USER = os.getenv('DATABASE_USER')
DB_PASS = os.getenv('MYSQL_PASSWORD')
DB_HOST = os.getenv('DATABASE_HOST')


def pass_to_sql(df:DataFrame, table: str, engine: Engine, primary_key:str = 'row_hash', timestamp_col:str = 'updated_at'):
    if df.empty:
        return

    columns = df.columns.tolist()

    if primary_key not in columns:
        raise ValueError(f"'{primary_key}' not found in DataFrame")

    if timestamp_col not in columns:
        raise ValueError(f"'{timestamp_col}' not found in DataFrame")

    # Build SQL parts
    column_names = ", ".join(columns)
    value_names = ", ".join([f":{col}" for col in columns])

    # Columns to update (exclude PK)
    update_columns = [
        col for col in columns if col != primary_key
    ]

    update_clause = ", ".join(
    [
        f"""{col} = IF(
            VALUES({timestamp_col}) > {table}.{timestamp_col},
            VALUES({col}),
            {table}.{col}
        )"""
        for col in columns
        if col != timestamp_col
    ])

    update_clause += f""",
    {timestamp_col} = GREATEST(
        VALUES({timestamp_col}),
        {table}.{timestamp_col}
    )
    """

    # Only update if incoming timestamp is newer
    sql = f"""
    INSERT INTO {table} ({column_names})
    VALUES ({value_names})
    ON DUPLICATE KEY UPDATE
        {update_clause}
    """

    records = df.to_dict(orient="records")

    with engine.begin() as conn:
        conn.execute(text(sql), records)

def get_conn() -> Engine:
    """
    """
    engine = create_engine(f'mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:3306/Marketing')
    return engine