import hashlib
from datetime import datetime
import os

from glob import glob
from sqlalchemy import text, String

def pass_to_sql(
    df,
    engine,
    table_name,
    unique_cols=None,  
    timestamp_col="updated_at"
):

    df = df.copy()

    if unique_cols is None:
        df = add_row_hash(df)
        unique_cols = ["row_hash"]

    else:
        df["row_hash"] = add_row_hash(df[unique_cols])['row_hash']
        unique_cols = ["row_hash"]

    df[timestamp_col] = datetime.now()

    df.head(0).to_sql(
        table_name,
        con=engine,
        if_exists="append",
        index=False,
        dtype={
            "row_hash": String(32)
        }
    )

    constraint_name = f"unique_row_{table_name}"


    with engine.connect() as conn:

        col_exists = conn.execute(text(f"""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = 'mkt'
            AND table_name = '{table_name}'
            AND column_name = 'row_hash';
        """)).scalar()

        if not col_exists:
            conn.execute(text(f"""
                ALTER TABLE {table_name}
                ADD COLUMN row_hash VARCHAR(32);
            """))

        ts_exists = conn.execute(text(f"""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = 'mkt'
            AND table_name = '{table_name}'
            AND column_name = '{timestamp_col}';
        """)).scalar()

        if not ts_exists:
            conn.execute(text(f"""
                ALTER TABLE {table_name}
                ADD COLUMN {timestamp_col} DATETIME;
            """))

        exists = conn.execute(text(f"""
            SELECT COUNT(*)
            FROM information_schema.statistics
            WHERE table_schema = 'mkt'
            AND table_name = '{table_name}'
            AND index_name = '{constraint_name}';
        """)).scalar()

        if not exists:
            conn.execute(text(f"""
                ALTER TABLE {table_name}
                ADD CONSTRAINT {constraint_name}
                UNIQUE (`row_hash`);
            """))

    temp_table = f"{table_name}_temp"

    df.to_sql(
        temp_table,
        con=engine,
        if_exists="replace",
        index=False
    )


    with engine.connect() as conn:

        cols = ", ".join(df.columns)
        updates = ", ".join(
            [f"{col}=VALUES({col})" for col in df.columns]
        )

        conn.execute(text(f"""
            INSERT INTO {table_name} ({cols})
            SELECT {cols}
            FROM {temp_table}
            ON DUPLICATE KEY UPDATE
            {updates};
        """))

        conn.execute(text(f"DROP TABLE {temp_table}"))

def add_row_hash(df):
    df = df.copy()
    df = df.sort_index(axis=1) 
    
    df["row_hash"] = df.apply(
        lambda row: hashlib.md5(
            "|".join([str(v) for v in row.values]).encode()
        ).hexdigest(),
        axis=1
    )
    return df

def upsert(engine):
    with engine.connect() as conn:
        query = text(
        """
        UPDATE Metrics m
        JOIN (
            SELECT
                acc,
                chan,
                date,
                SUM(
                    COALESCE(followersGained, 0) 
                    - COALESCE(unfollows, 0)
                ) OVER (
                    PARTITION BY acc, chan
                    ORDER BY date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS followersTotal_calc
            FROM Metrics
        ) t
        ON m.acc = t.acc
        AND m.chan = t.chan
        AND m.date = t.date
        SET m.followersTotal = t.followersTotal_calc;
        """)
        conn.execute(query)
        conn.commit()

def clear_temp_files():
    excels = glob('Data/**/**.xls')
    csv = glob('Data/**/**.csv')

    allFiles = excels + csv
    for file in allFiles:
        os.remove(file) 
